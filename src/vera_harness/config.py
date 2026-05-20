"""Configuration loading for the Vera harness."""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Tuple


class ConfigError(ValueError):
    """Raised when harness configuration is invalid."""


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
    workspace_root: Path
    codex_app_server_command: CommandSpec
    max_turns: int
    turn_timeout_seconds: int
    run_timeout_seconds: int
    approval_policy: str
    sandbox_mode: str
    repo_clone_command: Optional[CommandSpec] = None
    repo_bootstrap_command: Optional[CommandSpec] = None

    @classmethod
    def from_env(
        cls,
        env: Optional[Mapping[str, str]] = None,
        require_secrets: bool = True,
    ) -> "HarnessConfig":
        source = os.environ if env is None else env
        telegram_bot_token = _optional_text(source.get("VERA_TELEGRAM_BOT_TOKEN"))
        allowed_chat_ids = _parse_int_list(source.get("VERA_ALLOWED_CHAT_IDS"), "VERA_ALLOWED_CHAT_IDS")
        allowed_user_ids = _parse_int_list(source.get("VERA_ALLOWED_USER_IDS"), "VERA_ALLOWED_USER_IDS")

        if require_secrets and not telegram_bot_token:
            raise ConfigError("VERA_TELEGRAM_BOT_TOKEN is required for live runs")
        if require_secrets and not allowed_chat_ids and not allowed_user_ids:
            raise ConfigError(
                "VERA_ALLOWED_CHAT_IDS or VERA_ALLOWED_USER_IDS is required for live runs"
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
        approval_policy = source.get("VERA_APPROVAL_POLICY", "on-request").strip()
        if approval_policy not in {"untrusted", "on-request", "on-failure", "never"}:
            raise ConfigError(
                "VERA_APPROVAL_POLICY must be one of: never, on-failure, on-request, untrusted"
            )
        sandbox_mode = source.get("VERA_SANDBOX_MODE", "workspace-write").strip()
        if sandbox_mode not in {"read-only", "workspace-write", "danger-full-access"}:
            raise ConfigError(
                "VERA_SANDBOX_MODE must be one of: danger-full-access, read-only, workspace-write"
            )

        return cls(
            telegram_bot_token=telegram_bot_token,
            allowed_chat_ids=allowed_chat_ids,
            allowed_user_ids=allowed_user_ids,
            workspace_root=workspace_root,
            codex_app_server_command=codex_command,
            max_turns=max_turns,
            turn_timeout_seconds=turn_timeout_seconds,
            run_timeout_seconds=run_timeout_seconds,
            approval_policy=approval_policy,
            sandbox_mode=sandbox_mode,
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


def _parse_int_list(value: Optional[str], field_name: str) -> Tuple[int, ...]:
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


def _parse_positive_int(value: Optional[str], field_name: str, default: int) -> int:
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
