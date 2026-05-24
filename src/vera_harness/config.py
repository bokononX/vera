"""Configuration loading for the Vera harness."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
from dataclasses import dataclass, field, replace as dataclass_replace
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .assistant_identity import (
    AssistantIdentityConfigError,
    assistant_identity_from_mapping,
    load_assistant_identity_file,
)
from .models import AssistantIdentity, OwnerProfile


class ConfigError(ValueError):
    """Raised when harness configuration is invalid."""


class CommandResolutionError(ConfigError):
    """Raised when a configured command cannot be resolved to an executable."""


DEFAULT_RUNTIME_DIR = "./runtime"
DEFAULT_TELEGRAM_CONFIG_PATH = "{}/telegram_config.json".format(DEFAULT_RUNTIME_DIR)
DEFAULT_ASSISTANT_IDENTITY_PATH = "{}/assistant_identity.json".format(DEFAULT_RUNTIME_DIR)
DEFAULT_ASSISTANT_IDENTITY_INTERVIEW_STATE_PATH = (
    "{}/assistant_identity_interviews.json".format(DEFAULT_RUNTIME_DIR)
)
DEFAULT_TELEGRAM_STATE_PATH = "{}/telegram_state.json".format(DEFAULT_RUNTIME_DIR)
DEFAULT_RUN_STATE_PATH = "{}/run_state.json".format(DEFAULT_RUNTIME_DIR)
DEFAULT_CHAT_SESSION_STATE_PATH = "{}/chat_sessions.json".format(DEFAULT_RUNTIME_DIR)
DEFAULT_IDENTITY_PROFILE_PATH = "{}/identity_profile.json".format(DEFAULT_RUNTIME_DIR)
DEFAULT_IDENTITY_INTERVIEW_STATE_PATH = "{}/identity_interviews.json".format(DEFAULT_RUNTIME_DIR)
DEFAULT_EVENT_LOG_PATH = "{}/events.jsonl".format(DEFAULT_RUNTIME_DIR)
DEFAULT_HEARTBEAT_STATE_PATH = "{}/heartbeat_state.json".format(DEFAULT_RUNTIME_DIR)
DEFAULT_WORKSPACE_ROOT = "{}/workspaces".format(DEFAULT_RUNTIME_DIR)
DEFAULT_IMESSAGE_CHAT_DB_PATH = "~/Library/Messages/chat.db"


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
class HeartbeatConfig:
    """Opt-in configuration for proactive Vera heartbeat ticks."""

    enabled: bool = False
    dry_run: bool = True
    interval_seconds: int = 6 * 60 * 60
    timezone: str = "UTC"
    quiet_hours_start: Optional[str] = "22:00"
    quiet_hours_end: Optional[str] = "08:00"
    max_daily_initiations: int = 2
    owner_chat_id: Optional[int] = None
    state_path: Path = field(
        default_factory=lambda: Path(DEFAULT_HEARTBEAT_STATE_PATH).expanduser().resolve()
    )
    repeat_cooldown_seconds: int = 24 * 60 * 60
    max_recent_topics: int = 20


@dataclass(frozen=True)
class TelegramUserConfig:
    """One human/user Telegram bot runtime in a multi-user deployment."""

    id: str
    bot_token_env: str
    bot_token: Optional[str]
    bot_username: Optional[str] = None
    allowed_chat_ids: Tuple[int, ...] = ()
    allowed_user_ids: Tuple[int, ...] = ()
    shared_chat_ids: Tuple[int, ...] = ()
    command_prefixes: Tuple[str, ...] = ()
    known_bot_usernames: Tuple[str, ...] = ()
    known_command_prefixes: Tuple[str, ...] = ()
    telegram_api_base_url: str = "https://api.telegram.org"
    telegram_poll_timeout_seconds: int = 30
    telegram_request_timeout_seconds: int = 35
    telegram_state_path: Path = field(default_factory=lambda: Path(DEFAULT_TELEGRAM_STATE_PATH).expanduser().resolve())
    assistant_identity: AssistantIdentity = field(default_factory=AssistantIdentity.default)
    assistant_identity_path: Path = field(default_factory=lambda: Path(DEFAULT_ASSISTANT_IDENTITY_PATH).expanduser().resolve())
    assistant_identity_interview_state_path: Path = field(
        default_factory=lambda: Path(DEFAULT_ASSISTANT_IDENTITY_INTERVIEW_STATE_PATH).expanduser().resolve()
    )
    owner_profile: Optional[OwnerProfile] = None
    run_state_path: Path = field(default_factory=lambda: Path(DEFAULT_RUN_STATE_PATH).expanduser().resolve())
    chat_session_state_path: Path = field(default_factory=lambda: Path(DEFAULT_CHAT_SESSION_STATE_PATH).expanduser().resolve())
    identity_profile_path: Path = field(default_factory=lambda: Path(DEFAULT_IDENTITY_PROFILE_PATH).expanduser().resolve())
    identity_interview_state_path: Path = field(default_factory=lambda: Path(DEFAULT_IDENTITY_INTERVIEW_STATE_PATH).expanduser().resolve())
    user_memory_root: Optional[Path] = None
    workspace_root: Path = field(default_factory=lambda: Path(DEFAULT_WORKSPACE_ROOT).expanduser().resolve())
    event_log_path: Path = field(default_factory=lambda: Path(DEFAULT_EVENT_LOG_PATH).expanduser().resolve())

    @property
    def redacted_bot_label(self) -> str:
        username = " @{}".format(self.bot_username) if self.bot_username else ""
        return "{}{} ({})".format(self.id, username, self.bot_token_env)


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
    assistant_identity: AssistantIdentity
    assistant_identity_path: Path
    assistant_identity_interview_state_path: Path
    owner_profile: Optional[OwnerProfile]
    run_state_path: Path
    chat_session_state_path: Path
    identity_profile_path: Path
    identity_interview_state_path: Path
    user_memory_root: Optional[Path]
    imessage_contact_ingestion_enabled: bool
    imessage_chat_db_path: Path
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
    heartbeat: HeartbeatConfig = field(default_factory=HeartbeatConfig)
    telegram_runtime_id: Optional[str] = None
    telegram_bot_username: Optional[str] = None
    telegram_command_prefixes: Tuple[str, ...] = ()
    telegram_shared_chat_ids: Tuple[int, ...] = ()
    telegram_known_bot_usernames: Tuple[str, ...] = ()
    telegram_known_command_prefixes: Tuple[str, ...] = ()
    telegram_users: Tuple[TelegramUserConfig, ...] = ()

    def config_for_telegram_user(self, user: Union[TelegramUserConfig, str]) -> "HarnessConfig":
        """Return a single-bot runtime config for one configured Telegram user."""

        selected = self.telegram_user(user) if isinstance(user, str) else user
        return dataclass_replace(
            self,
            telegram_bot_token=selected.bot_token,
            allowed_chat_ids=selected.allowed_chat_ids,
            allowed_user_ids=selected.allowed_user_ids,
            telegram_api_base_url=selected.telegram_api_base_url,
            telegram_poll_timeout_seconds=selected.telegram_poll_timeout_seconds,
            telegram_request_timeout_seconds=selected.telegram_request_timeout_seconds,
            telegram_state_path=selected.telegram_state_path,
            assistant_identity=selected.assistant_identity,
            assistant_identity_path=selected.assistant_identity_path,
            assistant_identity_interview_state_path=selected.assistant_identity_interview_state_path,
            owner_profile=selected.owner_profile,
            run_state_path=selected.run_state_path,
            chat_session_state_path=selected.chat_session_state_path,
            identity_profile_path=selected.identity_profile_path,
            identity_interview_state_path=selected.identity_interview_state_path,
            user_memory_root=selected.user_memory_root,
            workspace_root=selected.workspace_root,
            event_log_path=selected.event_log_path,
            telegram_runtime_id=selected.id,
            telegram_bot_username=selected.bot_username,
            telegram_command_prefixes=selected.command_prefixes,
            telegram_shared_chat_ids=selected.shared_chat_ids,
            telegram_known_bot_usernames=selected.known_bot_usernames,
            telegram_known_command_prefixes=selected.known_command_prefixes,
            telegram_users=(),
        )

    def telegram_user(self, user_id: str) -> TelegramUserConfig:
        for user in self.telegram_users:
            if user.id == user_id:
                return user
        raise ConfigError("unknown telegram user id: {}".format(user_id))

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
        assistant_config = _assistant_config_from_local(local_config)
        imessage_config = _imessage_config_from_local(local_config)
        heartbeat_config = _heartbeat_config_from_local(local_config)
        return cls.from_env(
            source,
            require_secrets=require_secrets,
            telegram_config=telegram_config,
            owner_config=owner_config,
            assistant_config=assistant_config,
            imessage_config=imessage_config,
            heartbeat_config=heartbeat_config,
        )

    @classmethod
    def from_env(
        cls,
        env: Optional[Mapping[str, str]] = None,
        require_secrets: bool = True,
        telegram_config: Optional[Mapping[str, Any]] = None,
        owner_config: Optional[Mapping[str, Any]] = None,
        assistant_config: Optional[Mapping[str, Any]] = None,
        imessage_config: Optional[Mapping[str, Any]] = None,
        heartbeat_config: Optional[Mapping[str, Any]] = None,
    ) -> "HarnessConfig":
        source = os.environ if env is None else env
        telegram_source = telegram_config or {}
        assistant_source = assistant_config or {}
        imessage_source = imessage_config or {}
        assistant_identity_path = _parse_path(
            _setting_value(
                assistant_source,
                "identity_path",
                source.get("VERA_ASSISTANT_IDENTITY_PATH", DEFAULT_ASSISTANT_IDENTITY_PATH),
            ),
            "assistant.identity_path",
        )
        assistant_identity_interview_state_path = Path(
            source.get(
                "VERA_ASSISTANT_IDENTITY_INTERVIEW_STATE_PATH",
                DEFAULT_ASSISTANT_IDENTITY_INTERVIEW_STATE_PATH,
            )
        ).expanduser().resolve()
        assistant_identity = _parse_assistant_identity(
            assistant_config,
            assistant_identity_path,
        )
        owner_profile = _parse_owner_profile(owner_config)
        heartbeat = _parse_heartbeat_config(heartbeat_config, source)
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
                source.get("VERA_TELEGRAM_STATE_PATH", DEFAULT_TELEGRAM_STATE_PATH),
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
        if (
            heartbeat.owner_chat_id is not None
            and allowed_chat_ids
            and heartbeat.owner_chat_id not in allowed_chat_ids
        ):
            raise ConfigError(
                "heartbeat.owner_chat_id must be included in telegram.allowed_chat_ids"
            )
        run_state_path = Path(
            source.get("VERA_RUN_STATE_PATH", DEFAULT_RUN_STATE_PATH)
        ).expanduser().resolve()
        chat_session_state_path = Path(
            source.get("VERA_CHAT_SESSION_STATE_PATH", DEFAULT_CHAT_SESSION_STATE_PATH)
        ).expanduser().resolve()
        identity_profile_path = Path(
            source.get("VERA_IDENTITY_PROFILE_PATH", DEFAULT_IDENTITY_PROFILE_PATH)
        ).expanduser().resolve()
        identity_interview_state_path = Path(
            source.get("VERA_IDENTITY_INTERVIEW_STATE_PATH", DEFAULT_IDENTITY_INTERVIEW_STATE_PATH)
        ).expanduser().resolve()
        user_memory_root = _parse_optional_path(
            _setting_value(
                owner_config or {},
                "user_memory_root",
                source.get("VERA_USER_MEMORY_ROOT"),
            ),
            "owner.user_memory_root",
        )
        imessage_contact_ingestion_enabled = _parse_bool(
            _setting_value(
                imessage_source,
                "contact_ingestion_enabled",
                source.get("VERA_IMESSAGE_CONTACT_INGESTION_ENABLED"),
            ),
            "imessage.contact_ingestion_enabled",
            default=False,
        )
        imessage_chat_db_path = _parse_path(
            _setting_value(
                imessage_source,
                "chat_db_path",
                source.get("VERA_IMESSAGE_CHAT_DB_PATH", DEFAULT_IMESSAGE_CHAT_DB_PATH),
            ),
            "imessage.chat_db_path",
        )
        event_log_path = Path(
            source.get("VERA_EVENT_LOG_PATH", DEFAULT_EVENT_LOG_PATH)
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

        workspace_root = Path(
            source.get("VERA_WORKSPACE_ROOT", DEFAULT_WORKSPACE_ROOT)
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

        telegram_users = _parse_telegram_user_configs(
            telegram_source,
            source,
            telegram_api_base_url=telegram_api_base_url,
            telegram_poll_timeout_seconds=telegram_poll_timeout_seconds,
            telegram_request_timeout_seconds=telegram_request_timeout_seconds,
        )

        if require_secrets and telegram_users:
            missing_tokens = [
                "{} ({})".format(user.id, user.bot_token_env)
                for user in telegram_users
                if not user.bot_token
            ]
            if missing_tokens:
                raise ConfigError(
                    "Telegram bot token environment variables are required for configured users: {}".format(
                        ", ".join(missing_tokens)
                    )
                )
            missing_allow_lists = [
                user.id
                for user in telegram_users
                if not user.allowed_chat_ids and not user.allowed_user_ids
            ]
            if missing_allow_lists:
                raise ConfigError(
                    "telegram.users entries must configure allowed_chat_ids or allowed_user_ids: {}".format(
                        ", ".join(missing_allow_lists)
                    )
                )
        elif require_secrets and not telegram_bot_token:
            raise ConfigError("VERA_TELEGRAM_BOT_TOKEN is required for live runs")
        elif require_secrets and not allowed_chat_ids and not allowed_user_ids:
            raise ConfigError(
                "telegram.allowed_chat_ids or telegram.allowed_user_ids is required for live runs"
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
            assistant_identity=assistant_identity,
            assistant_identity_path=assistant_identity_path,
            assistant_identity_interview_state_path=assistant_identity_interview_state_path,
            owner_profile=owner_profile,
            run_state_path=run_state_path,
            chat_session_state_path=chat_session_state_path,
            identity_profile_path=identity_profile_path,
            identity_interview_state_path=identity_interview_state_path,
            user_memory_root=user_memory_root,
            imessage_contact_ingestion_enabled=imessage_contact_ingestion_enabled,
            imessage_chat_db_path=imessage_chat_db_path,
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
            heartbeat=heartbeat,
            telegram_shared_chat_ids=_parse_int_list(
                telegram_source.get("shared_chat_ids"),
                "telegram.shared_chat_ids",
            ),
            telegram_known_bot_usernames=tuple(
                user.bot_username for user in telegram_users if user.bot_username is not None
            ),
            telegram_known_command_prefixes=tuple(
                prefix for user in telegram_users for prefix in user.command_prefixes
            ),
            telegram_users=telegram_users,
        )


def _parse_telegram_user_configs(
    telegram_source: Mapping[str, Any],
    env: Mapping[str, str],
    telegram_api_base_url: str,
    telegram_poll_timeout_seconds: int,
    telegram_request_timeout_seconds: int,
) -> Tuple[TelegramUserConfig, ...]:
    raw_users = telegram_source.get("users")
    if raw_users is None:
        return ()
    if not isinstance(raw_users, list):
        raise ConfigError("telegram.users must be an array")

    global_shared_chat_ids = _parse_int_list(
        telegram_source.get("shared_chat_ids"),
        "telegram.shared_chat_ids",
    )
    users = []
    seen_ids = set()
    seen_token_envs = set()
    seen_usernames = set()
    seen_prefixes = set()
    for index, raw_user in enumerate(raw_users):
        field_prefix = "telegram.users[{}]".format(index)
        if not isinstance(raw_user, Mapping):
            raise ConfigError("{} must be a JSON object".format(field_prefix))
        _validate_telegram_user_keys(raw_user, field_prefix)

        raw_id = raw_user.get("id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise ConfigError("{}.id must be a non-empty string".format(field_prefix))
        user_id = _safe_runtime_id(raw_id.strip(), "{}.id".format(field_prefix))
        if user_id in seen_ids:
            raise ConfigError("telegram.users contains duplicate id: {}".format(user_id))
        seen_ids.add(user_id)

        bot_token_env = _parse_bot_token_env(raw_user.get("bot_token_env"), field_prefix)
        if bot_token_env in seen_token_envs:
            raise ConfigError(
                "telegram.users contains duplicate bot_token_env: {}".format(bot_token_env)
            )
        seen_token_envs.add(bot_token_env)
        bot_username = _parse_bot_username(raw_user.get("bot_username"), field_prefix)
        if bot_username is not None:
            username_key = bot_username.lower()
            if username_key in seen_usernames:
                raise ConfigError(
                    "telegram.users contains duplicate bot_username: {}".format(bot_username)
                )
            seen_usernames.add(username_key)

        command_prefixes = _parse_command_prefixes(
            raw_user.get("command_prefixes"),
            "{}.command_prefixes".format(field_prefix),
        )
        for prefix in command_prefixes:
            if prefix in seen_prefixes:
                raise ConfigError(
                    "telegram.users contains duplicate command_prefix: {}".format(prefix)
                )
            seen_prefixes.add(prefix)

        shared_chat_ids = _parse_int_list(
            raw_user.get("shared_chat_ids", global_shared_chat_ids),
            "{}.shared_chat_ids".format(field_prefix),
        )
        if shared_chat_ids and bot_username is None and not command_prefixes:
            raise ConfigError(
                "{} must configure bot_username or command_prefixes for shared chats".format(
                    field_prefix
                )
            )

        assistant_source = _optional_mapping(
            raw_user.get("assistant"),
            "{}.assistant".format(field_prefix),
        )
        owner_source = _optional_mapping(raw_user.get("owner"), "{}.owner".format(field_prefix))
        base_path = Path(DEFAULT_RUNTIME_DIR, "telegram_users", user_id)
        assistant_identity_path = _parse_path(
            _setting_value(
                assistant_source or {},
                "identity_path",
                raw_user.get(
                    "assistant_identity_path",
                    str(base_path / "assistant_identity.json"),
                ),
            ),
            "{}.assistant.identity_path".format(field_prefix),
        )
        assistant_identity_interview_state_path = _parse_path(
            raw_user.get(
                "assistant_identity_interview_state_path",
                str(base_path / "assistant_identity_interviews.json"),
            ),
            "{}.assistant_identity_interview_state_path".format(field_prefix),
        )
        owner_profile = _parse_owner_profile(owner_source)
        user_memory_root = _parse_optional_path(
            _setting_value(
                raw_user,
                "user_memory_root",
                (owner_source or {}).get("user_memory_root"),
            ),
            "{}.user_memory_root".format(field_prefix),
        )

        user = TelegramUserConfig(
            id=user_id,
            bot_token_env=bot_token_env,
            bot_token=_optional_text(env.get(bot_token_env)),
            bot_username=bot_username,
            allowed_chat_ids=_parse_int_list(
                raw_user.get("allowed_chat_ids"),
                "{}.allowed_chat_ids".format(field_prefix),
            ),
            allowed_user_ids=_parse_int_list(
                raw_user.get("allowed_user_ids"),
                "{}.allowed_user_ids".format(field_prefix),
            ),
            shared_chat_ids=shared_chat_ids,
            command_prefixes=command_prefixes,
            telegram_api_base_url=_parse_url_base(
                raw_user.get("api_base_url", telegram_api_base_url),
                "{}.api_base_url".format(field_prefix),
            ),
            telegram_poll_timeout_seconds=_parse_positive_int(
                raw_user.get("poll_timeout_seconds"),
                "{}.poll_timeout_seconds".format(field_prefix),
                telegram_poll_timeout_seconds,
            ),
            telegram_request_timeout_seconds=_parse_positive_int(
                raw_user.get("request_timeout_seconds"),
                "{}.request_timeout_seconds".format(field_prefix),
                telegram_request_timeout_seconds,
            ),
            telegram_state_path=_parse_path(
                raw_user.get("state_path", str(base_path / "telegram_state.json")),
                "{}.state_path".format(field_prefix),
            ),
            assistant_identity=_parse_assistant_identity(
                assistant_source,
                assistant_identity_path,
            ),
            assistant_identity_path=assistant_identity_path,
            assistant_identity_interview_state_path=assistant_identity_interview_state_path,
            owner_profile=owner_profile,
            run_state_path=_parse_path(
                raw_user.get("run_state_path", str(base_path / "run_state.json")),
                "{}.run_state_path".format(field_prefix),
            ),
            chat_session_state_path=_parse_path(
                raw_user.get("chat_session_state_path", str(base_path / "chat_sessions.json")),
                "{}.chat_session_state_path".format(field_prefix),
            ),
            identity_profile_path=_parse_path(
                raw_user.get("identity_profile_path", str(base_path / "identity_profile.json")),
                "{}.identity_profile_path".format(field_prefix),
            ),
            identity_interview_state_path=_parse_path(
                raw_user.get("identity_interview_state_path", str(base_path / "identity_interviews.json")),
                "{}.identity_interview_state_path".format(field_prefix),
            ),
            user_memory_root=user_memory_root,
            workspace_root=_parse_path(
                raw_user.get("workspace_root", str(base_path / "workspaces")),
                "{}.workspace_root".format(field_prefix),
            ),
            event_log_path=_parse_path(
                raw_user.get("event_log_path", str(base_path / "events.jsonl")),
                "{}.event_log_path".format(field_prefix),
            ),
        )
        users.append(user)

    known_usernames = tuple(user.bot_username for user in users if user.bot_username is not None)
    known_prefixes = tuple(prefix for user in users for prefix in user.command_prefixes)
    return tuple(
        dataclass_replace(
            user,
            known_bot_usernames=known_usernames,
            known_command_prefixes=known_prefixes,
        )
        for user in users
    )


def _validate_telegram_user_keys(raw_user: Mapping[str, Any], field_prefix: str) -> None:
    forbidden = {
        "bot_token",
        "telegram_bot_token",
        "token",
        "VERA_TELEGRAM_BOT_TOKEN",
    }
    present_forbidden = sorted(forbidden.intersection(raw_user.keys()))
    if present_forbidden:
        raise ConfigError(
            "{} must not contain secret fields: {}".format(
                field_prefix,
                ", ".join(present_forbidden),
            )
        )
    allowed = {
        "id",
        "bot_username",
        "bot_token_env",
        "allowed_chat_ids",
        "allowed_user_ids",
        "shared_chat_ids",
        "command_prefixes",
        "api_base_url",
        "poll_timeout_seconds",
        "request_timeout_seconds",
        "state_path",
        "assistant",
        "assistant_identity_path",
        "assistant_identity_interview_state_path",
        "owner",
        "run_state_path",
        "chat_session_state_path",
        "identity_profile_path",
        "identity_interview_state_path",
        "user_memory_root",
        "workspace_root",
        "event_log_path",
    }
    unknown = sorted(set(raw_user.keys()) - allowed)
    if unknown:
        raise ConfigError(
            "{} contains unknown fields: {}".format(field_prefix, ", ".join(unknown))
        )


def _optional_mapping(value: Any, field_name: str) -> Optional[Mapping[str, Any]]:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ConfigError("{} must be a JSON object".format(field_name))
    return value


def _parse_bot_token_env(value: Any, field_prefix: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("{}.bot_token_env must be a non-empty string".format(field_prefix))
    text = value.strip()
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", text):
        raise ConfigError("{}.bot_token_env must be an environment variable name".format(field_prefix))
    return text


def _parse_bot_username(value: Any, field_prefix: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError("{}.bot_username must be a string".format(field_prefix))
    text = value.strip().lstrip("@")
    if not text:
        return None
    if not re.match(r"^[A-Za-z0-9_]{5,32}$", text):
        raise ConfigError("{}.bot_username must be a Telegram username".format(field_prefix))
    return text


def _parse_command_prefixes(value: Any, field_name: str) -> Tuple[str, ...]:
    prefixes = _parse_string_tuple(value, field_name)
    parsed = []
    for prefix in prefixes:
        if any(character.isspace() for character in prefix):
            raise ConfigError("{} entries must not contain whitespace".format(field_name))
        if not prefix.startswith(("/", "!")):
            raise ConfigError("{} entries must start with / or !".format(field_name))
        parsed.append(prefix)
    return tuple(parsed)


def _safe_runtime_id(value: str, field_name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")
    if not normalized or normalized in {".", ".."}:
        raise ConfigError("{} must contain usable identifier characters".format(field_name))
    return normalized[:80]


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
        "shared_chat_ids",
        "users",
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
        "user_memory_root",
    }
    unknown = sorted(set(owner_config.keys()) - allowed)
    if unknown:
        raise ConfigError("Owner config contains unknown fields: {}".format(", ".join(unknown)))
    return owner_config


def _assistant_config_from_local(local_config: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    if not local_config or "assistant" not in local_config:
        return None
    assistant_config = local_config["assistant"]
    if not isinstance(assistant_config, dict):
        raise ConfigError("assistant must be a JSON object")
    forbidden = {
        "api_key",
        "bot_token",
        "password",
        "secret",
        "telegram_bot_token",
        "token",
        "VERA_TELEGRAM_BOT_TOKEN",
    }
    present_forbidden = sorted(forbidden.intersection(assistant_config.keys()))
    if present_forbidden:
        raise ConfigError(
            "Assistant config must not contain secret fields: {}".format(
                ", ".join(present_forbidden)
            )
        )
    allowed = {
        "identity_path",
        "name",
        "short_description",
        "mission",
        "core_values",
        "communication_principles",
        "boundaries",
        "transparency_rules",
        "relationship_to_owner",
        "proactivity",
        "owner_special_treatment",
    }
    unknown = sorted(set(assistant_config.keys()) - allowed)
    if unknown:
        raise ConfigError("Assistant config contains unknown fields: {}".format(", ".join(unknown)))
    return assistant_config


def _imessage_config_from_local(local_config: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    if not local_config or "imessage" not in local_config:
        return None
    imessage_config = local_config["imessage"]
    if not isinstance(imessage_config, dict):
        raise ConfigError("imessage must be a JSON object")

    forbidden = {
        "api_key",
        "bot_token",
        "password",
        "secret",
        "telegram_bot_token",
        "token",
        "VERA_TELEGRAM_BOT_TOKEN",
    }
    present_forbidden = sorted(forbidden.intersection(imessage_config.keys()))
    if present_forbidden:
        raise ConfigError(
            "iMessage config must not contain secret fields: {}".format(
                ", ".join(present_forbidden)
            )
        )
    allowed = {
        "contact_ingestion_enabled",
        "chat_db_path",
    }
    unknown = sorted(set(imessage_config.keys()) - allowed)
    if unknown:
        raise ConfigError("iMessage config contains unknown fields: {}".format(", ".join(unknown)))
    return imessage_config


def _heartbeat_config_from_local(local_config: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    if not local_config or "heartbeat" not in local_config:
        return None
    heartbeat_config = local_config["heartbeat"]
    if not isinstance(heartbeat_config, dict):
        raise ConfigError("heartbeat must be a JSON object")

    forbidden = {
        "api_key",
        "bot_token",
        "password",
        "secret",
        "telegram_bot_token",
        "token",
        "VERA_TELEGRAM_BOT_TOKEN",
    }
    present_forbidden = sorted(forbidden.intersection(heartbeat_config.keys()))
    if present_forbidden:
        raise ConfigError(
            "Heartbeat config must not contain secret fields: {}".format(
                ", ".join(present_forbidden)
            )
        )
    allowed = {
        "enabled",
        "dry_run",
        "interval_seconds",
        "timezone",
        "quiet_hours",
        "quiet_hours_start",
        "quiet_hours_end",
        "max_daily_initiations",
        "owner_chat_id",
        "state_path",
        "repeat_cooldown_seconds",
        "max_recent_topics",
    }
    unknown = sorted(set(heartbeat_config.keys()) - allowed)
    if unknown:
        raise ConfigError("Heartbeat config contains unknown fields: {}".format(", ".join(unknown)))
    quiet_hours = heartbeat_config.get("quiet_hours")
    if quiet_hours is not None:
        if not isinstance(quiet_hours, dict):
            raise ConfigError("heartbeat.quiet_hours must be a JSON object")
        unknown_quiet = sorted(set(quiet_hours.keys()) - {"start", "end"})
        if unknown_quiet:
            raise ConfigError(
                "heartbeat.quiet_hours contains unknown fields: {}".format(
                    ", ".join(unknown_quiet)
                )
            )
    return heartbeat_config


def _parse_assistant_identity(
    assistant_config: Optional[Mapping[str, Any]],
    assistant_identity_path: Path,
) -> AssistantIdentity:
    identity = AssistantIdentity.default()
    try:
        if assistant_config is not None:
            inline_config = {
                key: value
                for key, value in assistant_config.items()
                if key != "identity_path"
            }
            identity = assistant_identity_from_mapping(
                inline_config,
                base=identity,
                source_name="assistant",
            )
        if assistant_identity_path.exists():
            identity = load_assistant_identity_file(assistant_identity_path, base=identity)
    except AssistantIdentityConfigError as exc:
        raise ConfigError(str(exc))
    return identity


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


def _parse_heartbeat_config(
    heartbeat_config: Optional[Mapping[str, Any]],
    source: Mapping[str, str],
) -> HeartbeatConfig:
    config = heartbeat_config or {}
    quiet_hours = config.get("quiet_hours")
    quiet_start_default = None
    quiet_end_default = None
    if isinstance(quiet_hours, Mapping):
        quiet_start_default = quiet_hours.get("start")
        quiet_end_default = quiet_hours.get("end")
    quiet_hours_start = _parse_optional_time(
        _setting_value(
            config,
            "quiet_hours_start",
            source.get("VERA_HEARTBEAT_QUIET_HOURS_START", quiet_start_default or "22:00"),
        ),
        "heartbeat.quiet_hours_start",
    )
    quiet_hours_end = _parse_optional_time(
        _setting_value(
            config,
            "quiet_hours_end",
            source.get("VERA_HEARTBEAT_QUIET_HOURS_END", quiet_end_default or "08:00"),
        ),
        "heartbeat.quiet_hours_end",
    )
    if (quiet_hours_start is None) != (quiet_hours_end is None):
        raise ConfigError("heartbeat quiet hours require both start and end")
    if quiet_hours_start is not None and quiet_hours_start == quiet_hours_end:
        raise ConfigError("heartbeat quiet hours start and end must differ")

    timezone = _parse_timezone(
        _setting_value(config, "timezone", source.get("VERA_HEARTBEAT_TIMEZONE", "UTC")),
        "heartbeat.timezone",
    )
    return HeartbeatConfig(
        enabled=_parse_bool(
            _setting_value(config, "enabled", source.get("VERA_HEARTBEAT_ENABLED")),
            "heartbeat.enabled",
            False,
        ),
        dry_run=_parse_bool(
            _setting_value(config, "dry_run", source.get("VERA_HEARTBEAT_DRY_RUN")),
            "heartbeat.dry_run",
            True,
        ),
        interval_seconds=_parse_positive_int(
            _setting_value(
                config,
                "interval_seconds",
                source.get("VERA_HEARTBEAT_INTERVAL_SECONDS"),
            ),
            "heartbeat.interval_seconds",
            6 * 60 * 60,
        ),
        timezone=timezone,
        quiet_hours_start=quiet_hours_start,
        quiet_hours_end=quiet_hours_end,
        max_daily_initiations=_parse_nonnegative_int_value(
            _setting_value(
                config,
                "max_daily_initiations",
                source.get("VERA_HEARTBEAT_MAX_DAILY_INITIATIONS"),
            ),
            "heartbeat.max_daily_initiations",
            2,
        ),
        owner_chat_id=_parse_optional_int(
            _setting_value(config, "owner_chat_id", source.get("VERA_HEARTBEAT_OWNER_CHAT_ID")),
            "heartbeat.owner_chat_id",
        ),
        state_path=_parse_path(
            _setting_value(
                config,
                "state_path",
                source.get("VERA_HEARTBEAT_STATE_PATH", DEFAULT_HEARTBEAT_STATE_PATH),
            ),
            "heartbeat.state_path",
        ),
        repeat_cooldown_seconds=_parse_positive_int(
            _setting_value(
                config,
                "repeat_cooldown_seconds",
                source.get("VERA_HEARTBEAT_REPEAT_COOLDOWN_SECONDS"),
            ),
            "heartbeat.repeat_cooldown_seconds",
            24 * 60 * 60,
        ),
        max_recent_topics=_parse_positive_int(
            _setting_value(
                config,
                "max_recent_topics",
                source.get("VERA_HEARTBEAT_MAX_RECENT_TOPICS"),
            ),
            "heartbeat.max_recent_topics",
            20,
        ),
    )


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


def _parse_bool(value: Any, field_name: str, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if not isinstance(value, str):
        raise ConfigError("{} must be a boolean".format(field_name))
    text = value.strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ConfigError("{} must be a boolean".format(field_name))


def _parse_timezone(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ConfigError("{} must be a string".format(field_name))
    text = value.strip()
    if not text:
        raise ConfigError("{} must not be empty".format(field_name))
    try:
        ZoneInfo(text)
    except ZoneInfoNotFoundError:
        raise ConfigError("{} must be a valid IANA timezone".format(field_name))
    return text


def _parse_optional_time(value: Any, field_name: str) -> Optional[str]:
    if value is not None and not isinstance(value, str):
        raise ConfigError("{} must be a string or null".format(field_name))
    text = _optional_text(value)
    if text is None:
        return None
    parts = text.split(":")
    if len(parts) != 2:
        raise ConfigError("{} must use HH:MM format".format(field_name))
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        raise ConfigError("{} must use HH:MM format".format(field_name))
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ConfigError("{} must use HH:MM with a 00:00-23:59 time".format(field_name))
    return "{:02d}:{:02d}".format(hour, minute)


def _parse_optional_int(value: Any, field_name: str) -> Optional[int]:
    if isinstance(value, bool):
        raise ConfigError("{} must be an integer".format(field_name))
    if isinstance(value, int):
        return value
    if value is not None and not isinstance(value, str):
        raise ConfigError("{} must be an integer".format(field_name))
    text = _optional_text(value)
    if text is None:
        return None
    try:
        parsed = int(text)
    except (TypeError, ValueError):
        raise ConfigError("{} must be an integer".format(field_name))
    return parsed


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


def _parse_bool(value: Any, field_name: str, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if not isinstance(value, str):
        raise ConfigError("{} must be a boolean".format(field_name))
    text = value.strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    raise ConfigError("{} must be a boolean".format(field_name))


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


def _parse_nonnegative_int_value(value: Any, field_name: str, default: int) -> int:
    if isinstance(value, bool):
        raise ConfigError("{} must be an integer".format(field_name))
    if isinstance(value, int):
        if value < 0:
            raise ConfigError("{} must be zero or greater".format(field_name))
        return value
    if value is not None and not isinstance(value, str):
        raise ConfigError("{} must be an integer".format(field_name))
    return _parse_nonnegative_int(value, field_name, default)
