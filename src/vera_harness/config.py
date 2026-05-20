"""Configuration loading for the Vera harness."""

from __future__ import annotations

import json
import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple


class ConfigError(ValueError):
    """Raised when harness configuration is invalid."""


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
    workspace_root: Path
    codex_app_server_command: CommandSpec
    max_turns: int
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
        telegram_config = _load_telegram_config(config_path, explicit_path)
        return cls.from_env(
            source,
            require_secrets=require_secrets,
            telegram_config=telegram_config,
        )

    @classmethod
    def from_env(
        cls,
        env: Optional[Mapping[str, str]] = None,
        require_secrets: bool = True,
        telegram_config: Optional[Mapping[str, Any]] = None,
    ) -> "HarnessConfig":
        source = os.environ if env is None else env
        telegram_source = telegram_config or {}
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
            workspace_root=workspace_root,
            codex_app_server_command=codex_command,
            max_turns=max_turns,
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


def _parse_optional_string(value: Any, field_name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError("{} must be a string or null".format(field_name))
    return _optional_text(value)


def _load_telegram_config(config_path: Path, explicit_path: bool) -> Mapping[str, Any]:
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
    if "telegram" not in loaded:
        raise ConfigError("Telegram config file must contain a 'telegram' object")
    telegram_config = loaded["telegram"]
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
