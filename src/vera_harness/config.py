"""Configuration loading for the Vera harness."""

from __future__ import annotations

import json
import os
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

from .models import OwnerProfile


class ConfigError(ValueError):
    """Raised when harness configuration is invalid."""


class CommandResolutionError(ConfigError):
    """Raised when a configured command cannot be resolved to an executable."""


DEFAULT_TELEGRAM_CONFIG_PATH = "./.vera/telegram_config.json"


@dataclass(frozen=True)
class CommandSpec:
    """A shell-style command parsed into argv for later execution."""

    raw: str
    argv: Tuple[str, ...]

    @classmethod
    def parse(cls, value: str, field_name: str) -> "CommandSpec":
        raw = value.strip()
        if not raw:
            raise ConfigError("{} must not be empty".format(field_name))
        try:
            argv = tuple(shlex.split(raw))
        except ValueError as exc:
            raise ConfigError("{} is not a valid shell command: {}".format(field_name, exc))
        if not argv:
            raise ConfigError("{} must contain an executable".format(field_name))
        return cls(raw=raw, argv=argv)

    @property
    def display(self) -> str:
        return shlex.join(self.argv)

    def resolve_executable(
        self,
        field_name: str,
        cwd: Optional[Path] = None,
    ) -> "CommandResolution":
        return resolve_command_executable(self, field_name, cwd=cwd)


@dataclass(frozen=True)
class CommandResolution:
    """A command with argv[0] resolved to an executable path."""

    command: CommandSpec
    field_name: str
    executable: str
    resolved_executable: Path
    argv: Tuple[str, ...]

    @property
    def display(self) -> str:
        return shlex.join(self.argv)


@dataclass(frozen=True)
class HarnessConfig:
    """Runtime configuration for Telegram intake, workspaces, and Codex."""

    telegram_bot_token: Optional[str]
    allowed_chat_ids: Tuple[int, ...]
    allowed_user_ids: Tuple[int, ...]
    telegram_api_base_url: str
    telegram_poll_timeout_seconds: int
    telegram_request_timeout_seconds: int
    telegram_state_path: Path
    telegram_unauthorized_response: Optional[str]
    owner_profile: Optional[OwnerProfile]
    run_state_path: Path
    chat_session_state_path: Path
    identity_profile_path: Path
    identity_interview_state_path: Path
    event_log_path: Path
    budget_snapshot_path: Optional[Path]
    monthly_budget_usd: Optional[float]
    project_budget_usd: Optional[float]
    workspace_root: Path
    codex_app_server_command: CommandSpec
    max_turns: int
    max_retries: int
    turn_timeout_seconds: int
    run_timeout_seconds: int
    workspace_bootstrap_timeout_seconds: int
    workspace_retention_policy: str
    approval_policy: str
    sandbox_mode: str
    codex_approval_decision: Optional[str] = None
    codex_auto_input_response: Optional[str] = None
    repo_clone_command: Optional[CommandSpec] = None
    repo_bootstrap_command: Optional[CommandSpec] = None

    @classmethod
    def load(
        cls,
        env: Optional[Mapping[str, str]] = None,
        require_secrets: bool = True,
        telegram_config_path: Optional[str] = None,
    ) -> "HarnessConfig":
        source = os.environ if env is None else env
        path_text = telegram_config_path or _optional_text(source.get("VERA_TELEGRAM_CONFIG_PATH"))
        explicit_path = path_text is not None
        config_path = Path(path_text or DEFAULT_TELEGRAM_CONFIG_PATH).expanduser().resolve()
        local_config = _load_local_config(config_path, explicit_path)
        telegram_config = _telegram_config_from_local(local_config)
        owner_config = _owner_config_from_local(local_config)
        return cls.from_env(
            source,
            require_secrets=require_secrets,
            telegram_config=telegram_config,
            owner_config=owner_config,
        )

    @classmethod
    def from_env(
        cls,
        env: Optional[Mapping[str, str]] = None,
        require_secrets: bool = True,
        telegram_config: Optional[Mapping[str, Any]] = None,
        owner_config: Optional[Mapping[str, Any]] = None,
    ) -> "HarnessConfig":
        source = os.environ if env is None else env
        telegram_source = telegram_config or {}
        owner_profile = _parse_owner_profile(owner_config)
        telegram_bot_token = _optional_text(source.get("VERA_TELEGRAM_BOT_TOKEN"))
        allowed_chat_ids = _parse_int_list(
            _setting_value(
                telegram_source,
                "allowed_chat_ids",
                source.get("VERA_ALLOWED_CHAT_IDS"),
            ),
            "telegram.allowed_chat_ids",
        )
        allowed_user_ids = _parse_int_list(
            _setting_value(
                telegram_source,
                "allowed_user_ids",
                source.get("VERA_ALLOWED_USER_IDS"),
            ),
            "telegram.allowed_user_ids",
        )
        telegram_api_base_url = _parse_url_base(
            _setting_value(
                telegram_source,
                "api_base_url",
                source.get("VERA_TELEGRAM_API_BASE_URL", "https://api.telegram.org"),
            ),
            "telegram.api_base_url",
        )
        telegram_poll_timeout_seconds = _parse_positive_int(
            _setting_value(
                telegram_source,
                "poll_timeout_seconds",
                source.get("VERA_TELEGRAM_POLL_TIMEOUT_SECONDS"),
            ),
            "telegram.poll_timeout_seconds",
            30,
        )
        telegram_request_timeout_seconds = _parse_positive_int(
            _setting_value(
                telegram_source,
                "request_timeout_seconds",
                source.get("VERA_TELEGRAM_REQUEST_TIMEOUT_SECONDS"),
            ),
            "telegram.request_timeout_seconds",
            35,
        )
        telegram_state_path = _parse_path(
            _setting_value(
                telegram_source,
                "state_path",
                source.get("VERA_TELEGRAM_STATE_PATH", "./.vera/telegram_state.json"),
            ),
            "telegram.state_path",
        )
        telegram_unauthorized_response = _parse_optional_string(
            _setting_value(
                telegram_source,
                "unauthorized_response",
                source.get("VERA_TELEGRAM_UNAUTHORIZED_RESPONSE"),
            ),
            "telegram.unauthorized_response",
        )
        run_state_path = Path(
            source.get("VERA_RUN_STATE_PATH", "./.vera/run_state.json")
        ).expanduser().resolve()
        chat_session_state_path = Path(
            source.get("VERA_CHAT_SESSION_STATE_PATH", "./.vera/chat_sessions.json")
        ).expanduser().resolve()
        identity_profile_path = Path(
            source.get("VERA_IDENTITY_PROFILE_PATH", "./.vera/identity_profile.json")
        ).expanduser().resolve()
        identity_interview_state_path = Path(
            source.get("VERA_IDENTITY_INTERVIEW_STATE_PATH", "./.vera/identity_interviews.json")
        ).expanduser().resolve()
        event_log_path = Path(
            source.get("VERA_EVENT_LOG_PATH", "./.vera/events.jsonl")
        ).expanduser().resolve()
        budget_snapshot_path = _parse_optional_path(
            source.get("VERA_BUDGET_SNAPSHOT_PATH"),
            "VERA_BUDGET_SNAPSHOT_PATH",
        )
        monthly_budget_usd = _parse_optional_float(
            source.get("VERA_MONTHLY_BUDGET_USD"),
            "VERA_MONTHLY_BUDGET_USD",
        )
        project_budget_usd = _parse_optional_float(
            source.get("VERA_PROJECT_BUDGET_USD"),
            "VERA_PROJECT_BUDGET_USD",
        )

        if require_secrets and not telegram_bot_token:
            raise ConfigError("VERA_TELEGRAM_BOT_TOKEN is required for live runs")
        if require_secrets and not allowed_chat_ids and not allowed_user_ids:
            raise ConfigError(
                "telegram.allowed_chat_ids or telegram.allowed_user_ids is required for live runs"
            )

        workspace_root = Path(
            source.get("VERA_WORKSPACE_ROOT", "./.vera/workspaces")
        ).expanduser().resolve()
        codex_command = CommandSpec.parse(
            source.get("VERA_CODEX_APP_SERVER_COMMAND", "codex app-server"),
            "VERA_CODEX_APP_SERVER_COMMAND",
        )
        max_turns = _parse_positive_int(source.get("VERA_MAX_TURNS"), "VERA_MAX_TURNS", 20)
        max_retries = _parse_nonnegative_int(
            source.get("VERA_MAX_RETRIES"),
            "VERA_MAX_RETRIES",
            1,
        )
        turn_timeout_seconds = _parse_positive_int(
            source.get("VERA_TURN_TIMEOUT_SECONDS"),
            "VERA_TURN_TIMEOUT_SECONDS",
            300,
        )
        run_timeout_seconds = _parse_positive_int(
            source.get("VERA_RUN_TIMEOUT_SECONDS"),
            "VERA_RUN_TIMEOUT_SECONDS",
            1800,
        )
        workspace_bootstrap_timeout_seconds = _parse_positive_int(
            source.get("VERA_WORKSPACE_BOOTSTRAP_TIMEOUT_SECONDS"),
            "VERA_WORKSPACE_BOOTSTRAP_TIMEOUT_SECONDS",
            300,
        )
        workspace_retention_policy = source.get(
            "VERA_WORKSPACE_RETENTION_POLICY",
            "retain",
        ).strip()
        if workspace_retention_policy not in {"retain", "cleanup_on_success", "cleanup_on_completion"}:
            raise ConfigError(
                "VERA_WORKSPACE_RETENTION_POLICY must be one of: cleanup_on_completion, cleanup_on_success, retain"
            )
        approval_policy = source.get("VERA_APPROVAL_POLICY", "on-request").strip()
        if approval_policy not in {"untrusted", "on-request", "on-failure", "never"}:
            raise ConfigError(
                "VERA_APPROVAL_POLICY must be one of: never, on-failure, on-request, untrusted"
            )
        sandbox_mode = source.get("VERA_SANDBOX_MODE", "read-only").strip()
        if sandbox_mode not in {"read-only", "workspace-write", "danger-full-access"}:
            raise ConfigError(
                "VERA_SANDBOX_MODE must be one of: danger-full-access, read-only, workspace-write"
            )
        codex_approval_decision = _optional_text(source.get("VERA_CODEX_APPROVAL_DECISION"))
        if codex_approval_decision is not None and codex_approval_decision not in {
            "accept",
            "acceptForSession",
            "decline",
            "cancel",
        }:
            raise ConfigError(
                "VERA_CODEX_APPROVAL_DECISION must be one of: accept, acceptForSession, cancel, decline"
            )

        return cls(
            telegram_bot_token=telegram_bot_token,
            allowed_chat_ids=allowed_chat_ids,
            allowed_user_ids=allowed_user_ids,
            telegram_api_base_url=telegram_api_base_url,
            telegram_poll_timeout_seconds=telegram_poll_timeout_seconds,
            telegram_request_timeout_seconds=telegram_request_timeout_seconds,
            telegram_state_path=telegram_state_path,
            telegram_unauthorized_response=telegram_unauthorized_response,
            owner_profile=owner_profile,
            run_state_path=run_state_path,
            chat_session_state_path=chat_session_state_path,
            identity_profile_path=identity_profile_path,
            identity_interview_state_path=identity_interview_state_path,
            event_log_path=event_log_path,
            budget_snapshot_path=budget_snapshot_path,
            monthly_budget_usd=monthly_budget_usd,
            project_budget_usd=project_budget_usd,
            workspace_root=workspace_root,
            codex_app_server_command=codex_command,
            max_turns=max_turns,
            max_retries=max_retries,
            turn_timeout_seconds=turn_timeout_seconds,
            run_timeout_seconds=run_timeout_seconds,
            workspace_bootstrap_timeout_seconds=workspace_bootstrap_timeout_seconds,
            workspace_retention_policy=workspace_retention_policy,
            approval_policy=approval_policy,
            sandbox_mode=sandbox_mode,
            codex_approval_decision=codex_approval_decision,
            codex_auto_input_response=_optional_text(source.get("VERA_CODEX_AUTO_INPUT_RESPONSE")),
            repo_clone_command=_optional_command(source.get("VERA_REPO_CLONE_COMMAND"), "VERA_REPO_CLONE_COMMAND"),
            repo_bootstrap_command=_optional_command(
                source.get("VERA_REPO_BOOTSTRAP_COMMAND"),
                "VERA_REPO_BOOTSTRAP_COMMAND",
            ),
        )


def _optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _optional_command(value: Optional[str], field_name: str) -> Optional[CommandSpec]:
    text = _optional_text(value)
    if text is None:
        return None
    return CommandSpec.parse(text, field_name)


def resolve_command_executable(
    command: CommandSpec,
    field_name: str,
    cwd: Optional[Path] = None,
) -> CommandResolution:
    executable = command.argv[0]
    resolved = _resolve_executable_path(executable, cwd=cwd)
    if resolved is None:
        raise CommandResolutionError(
            _missing_executable_message(field_name, executable, cwd=cwd)
        )
    return CommandResolution(
        command=command,
        field_name=field_name,
        executable=executable,
        resolved_executable=resolved,
        argv=(str(resolved), *command.argv[1:]),
    )


def _resolve_executable_path(executable: str, cwd: Optional[Path]) -> Optional[Path]:
    if _uses_explicit_path(executable):
        candidate = _executable_candidate_path(executable, cwd=cwd)
        if _is_executable_file(candidate):
            return candidate
        return None
    found = shutil.which(executable)
    if found is None:
        return None
    return Path(found).expanduser().resolve()


def _uses_explicit_path(executable: str) -> bool:
    return (
        executable.startswith("~")
        or os.sep in executable
        or (os.altsep is not None and os.altsep in executable)
    )


def _executable_candidate_path(executable: str, cwd: Optional[Path]) -> Path:
    candidate = Path(executable).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    base = cwd or Path.cwd()
    return (base / candidate).resolve()


def _is_executable_file(path: Path) -> bool:
    try:
        return path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False


def _missing_executable_message(field_name: str, executable: str, cwd: Optional[Path]) -> str:
    displayed = shlex.quote(executable)
    if _uses_explicit_path(executable):
        candidate = _executable_candidate_path(executable, cwd=cwd)
        return (
            "{} executable not found or not executable: {} (resolved to {}). "
            "Install the command or set {} to an absolute executable path. "
            "For Codex, a typical value is '/path/to/codex app-server'."
        ).format(field_name, displayed, candidate, field_name)
    return (
        "{} executable not found on PATH: {}. Install the command or set {} "
        "to an absolute executable path. For Codex, a typical value is "
        "'/path/to/codex app-server'."
    ).format(field_name, displayed, field_name)


def _parse_optional_string(value: Any, field_name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError("{} must be a string or null".format(field_name))
    return _optional_text(value)


def _load_local_config(config_path: Path, explicit_path: bool) -> Mapping[str, Any]:
    if not config_path.exists():
        if explicit_path:
            raise ConfigError("Telegram config file does not exist: {}".format(config_path))
        return {}
    try:
        raw = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError("Telegram config file cannot be read: {}".format(exc))
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError("Telegram config file is not valid JSON: {}".format(exc))
    if not isinstance(loaded, dict):
        raise ConfigError("Telegram config file must contain a JSON object")
    return loaded


def _telegram_config_from_local(local_config: Mapping[str, Any]) -> Mapping[str, Any]:
    if not local_config:
        return {}
    if "telegram" not in local_config:
        raise ConfigError("Telegram config file must contain a 'telegram' object")
    telegram_config = local_config["telegram"]
    if not isinstance(telegram_config, dict):
        raise ConfigError("telegram must be a JSON object")
    forbidden = {"bot_token", "telegram_bot_token", "VERA_TELEGRAM_BOT_TOKEN"}
    present_forbidden = sorted(forbidden.intersection(telegram_config.keys()))
    if present_forbidden:
        raise ConfigError(
            "Telegram config must not contain secret fields: {}".format(
                ", ".join(present_forbidden)
            )
        )
    allowed = {
        "allowed_chat_ids",
        "allowed_user_ids",
        "api_base_url",
        "poll_timeout_seconds",
        "request_timeout_seconds",
        "state_path",
        "unauthorized_response",
    }
    unknown = sorted(set(telegram_config.keys()) - allowed)
    if unknown:
        raise ConfigError("Telegram config contains unknown fields: {}".format(", ".join(unknown)))
    return telegram_config


def _owner_config_from_local(local_config: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    if not local_config or "owner" not in local_config:
        return None
    owner_config = local_config["owner"]
    if not isinstance(owner_config, dict):
        raise ConfigError("owner must be a JSON object")
    forbidden = {
        "api_key",
        "bot_token",
        "password",
        "secret",
        "telegram_bot_token",
        "token",
        "VERA_TELEGRAM_BOT_TOKEN",
    }
    present_forbidden = sorted(forbidden.intersection(owner_config.keys()))
    if present_forbidden:
        raise ConfigError(
            "Owner config must not contain secret fields: {}".format(
                ", ".join(present_forbidden)
            )
        )
    allowed = {
        "user_id",
        "display_name",
        "username",
        "role",
        "values",
        "priorities",
        "communication_style",
        "escalation_boundaries",
        "wiki_profile_path",
    }
    unknown = sorted(set(owner_config.keys()) - allowed)
    if unknown:
        raise ConfigError("Owner config contains unknown fields: {}".format(", ".join(unknown)))
    return owner_config


def _parse_owner_profile(owner_config: Optional[Mapping[str, Any]]) -> Optional[OwnerProfile]:
    if owner_config is None:
        return None
    user_id = owner_config.get("user_id")
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        raise ConfigError("owner.user_id must be an integer")
    wiki_profile_path = _parse_optional_path(
        owner_config.get("wiki_profile_path"),
        "owner.wiki_profile_path",
    )
    return OwnerProfile(
        user_id=user_id,
        display_name=_parse_optional_string(
            owner_config.get("display_name"),
            "owner.display_name",
        ),
        username=_parse_optional_string(owner_config.get("username"), "owner.username"),
        role=_parse_optional_string(owner_config.get("role"), "owner.role"),
        values=_parse_string_tuple(owner_config.get("values"), "owner.values"),
        priorities=_parse_string_tuple(owner_config.get("priorities"), "owner.priorities"),
        communication_style=_parse_string_tuple(
            owner_config.get("communication_style"),
            "owner.communication_style",
        ),
        escalation_boundaries=_parse_string_tuple(
            owner_config.get("escalation_boundaries"),
            "owner.escalation_boundaries",
        ),
        wiki_profile_path=wiki_profile_path,
        wiki_profile_excerpt=_load_owner_profile_excerpt(wiki_profile_path),
    )


def _parse_string_tuple(value: Any, field_name: str) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if not isinstance(value, (list, tuple)):
        raise ConfigError("{} must be a string or an array of strings".format(field_name))
    parsed = []
    for item in value:
        if not isinstance(item, str):
            raise ConfigError("{} must contain only strings".format(field_name))
        text = item.strip()
        if text:
            parsed.append(text)
    return tuple(parsed)


def _load_owner_profile_excerpt(path: Optional[Path], max_chars: int = 2000) -> Optional[str]:
    if path is None:
        return None
    if not path.exists():
        raise ConfigError("owner.wiki_profile_path does not exist: {}".format(path))
    if not path.is_file():
        raise ConfigError("owner.wiki_profile_path must be a file: {}".format(path))
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError("owner.wiki_profile_path cannot be read: {}".format(exc))
    text = text.strip()
    if not text:
        return None
    if len(text) <= max_chars:
        return text
    return "{}\n[truncated to {} characters]".format(text[:max_chars].rstrip(), max_chars)


def _setting_value(
    config: Mapping[str, Any],
    key: str,
    env_value: Optional[str],
) -> Any:
    if key in config:
        return config[key]
    return env_value


def _parse_int_list(value: Any, field_name: str) -> Tuple[int, ...]:
    if isinstance(value, (list, tuple)):
        result = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, int):
                raise ConfigError("{} must contain only integers".format(field_name))
            result.append(item)
        return tuple(result)
    if value is not None and not isinstance(value, str):
        raise ConfigError("{} must be an array of integers or a comma-separated string".format(field_name))
    text = _optional_text(value)
    if text is None:
        return ()
    result = []
    for part in text.split(","):
        item = part.strip()
        if not item:
            continue
        try:
            result.append(int(item))
        except ValueError:
            raise ConfigError("{} contains a non-integer value: {!r}".format(field_name, item))
    return tuple(result)


def _parse_url_base(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ConfigError("{} must be a string".format(field_name))
    text = value.strip().rstrip("/")
    if not text:
        raise ConfigError("{} must not be empty".format(field_name))
    if not (text.startswith("https://") or text.startswith("http://")):
        raise ConfigError("{} must start with http:// or https://".format(field_name))
    return text


def _parse_path(value: Any, field_name: str) -> Path:
    if not isinstance(value, str):
        raise ConfigError("{} must be a string".format(field_name))
    return Path(value).expanduser().resolve()


def _parse_optional_path(value: Any, field_name: str) -> Optional[Path]:
    text = _optional_text(value)
    if text is None:
        return None
    return _parse_path(text, field_name)


def _parse_optional_float(value: Any, field_name: str) -> Optional[float]:
    text = _optional_text(value)
    if text is None:
        return None
    try:
        parsed = float(text)
    except ValueError:
        raise ConfigError("{} must be a number".format(field_name))
    if parsed < 0:
        raise ConfigError("{} must be zero or greater".format(field_name))
    return parsed


def _parse_positive_int(value: Any, field_name: str, default: int) -> int:
    if isinstance(value, bool):
        raise ConfigError("{} must be an integer".format(field_name))
    if isinstance(value, int):
        parsed = value
        if parsed <= 0:
            raise ConfigError("{} must be greater than zero".format(field_name))
        return parsed
    if value is not None and not isinstance(value, str):
        raise ConfigError("{} must be an integer".format(field_name))
    text = _optional_text(value)
    if text is None:
        return default
    try:
        parsed = int(text)
    except ValueError:
        raise ConfigError("{} must be an integer".format(field_name))
    if parsed <= 0:
        raise ConfigError("{} must be greater than zero".format(field_name))
    return parsed


def _parse_nonnegative_int(value: Optional[str], field_name: str, default: int) -> int:
    text = _optional_text(value)
    if text is None:
        return default
    try:
        parsed = int(text)
    except ValueError:
        raise ConfigError("{} must be an integer".format(field_name))
    if parsed < 0:
        raise ConfigError("{} must be zero or greater".format(field_name))
    return parsed
