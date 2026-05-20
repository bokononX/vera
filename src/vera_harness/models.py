"""Core domain models for the Vera harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple


class HarnessRunStatus(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CodexTurnStatus(str, Enum):
    PLANNED = "planned"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class TelegramTask:
    """A minimal task derived from a Telegram message."""

    task_id: str
    chat_id: int
    user_id: int
    message_id: int
    text: str
    username: Optional[str] = None
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_message(
        cls,
        chat_id: int,
        user_id: int,
        message_id: int,
        text: str,
        username: Optional[str] = None,
        received_at: Optional[datetime] = None,
    ) -> "TelegramTask":
        if not isinstance(chat_id, int):
            raise ValueError("chat_id must be an integer")
        if not isinstance(user_id, int):
            raise ValueError("user_id must be an integer")
        if not isinstance(message_id, int):
            raise ValueError("message_id must be an integer")
        normalized_text = text.strip()
        if not normalized_text:
            raise ValueError("Telegram task text must not be empty")
        return cls(
            task_id="telegram-{}-{}".format(chat_id, message_id),
            chat_id=chat_id,
            user_id=user_id,
            message_id=message_id,
            text=normalized_text,
            username=username.strip() if username else None,
            received_at=received_at or datetime.now(timezone.utc),
        )

    def summary(self, limit: int = 120) -> str:
        if len(self.text) <= limit:
            return self.text
        return "{}...".format(self.text[: max(0, limit - 3)])


@dataclass(frozen=True)
class Workspace:
    """A per-task isolated workspace plan."""

    workspace_id: str
    task_id: str
    root: Path
    path: Path
    created: bool = False
    repo_clone_command: Optional[str] = None
    repo_bootstrap_command: Optional[str] = None


@dataclass(frozen=True)
class HarnessRun:
    """A harness run that regulates Codex turns for one task."""

    run_id: str
    task: TelegramTask
    workspace: Workspace
    max_turns: int
    status: HarnessRunStatus = HarnessRunStatus.PLANNED
    dry_run: bool = False
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class CodexTurnResult:
    """The result of one Codex turn."""

    turn_number: int
    status: CodexTurnStatus
    transcript_excerpt: str = ""
    error: Optional[str] = None
    elapsed_seconds: Optional[float] = None
    unanswered_questions: Tuple[str, ...] = ()
