"""Core domain models for the Vera harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Mapping, Optional, Tuple


class HarnessRunStatus(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    APPROVAL_REQUIRED = "approval_required"
    INPUT_REQUIRED = "input_required"
    FAILED = "failed"
    DUPLICATE_ACTIVE = "duplicate_active"


class CodexTurnStatus(str, Enum):
    PLANNED = "planned"
    COMPLETED = "completed"
    APPROVAL_REQUIRED = "approval_required"
    INPUT_REQUIRED = "input_required"
    CANCELLED = "cancelled"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class TaskEventType(str, Enum):
    """Structured task lifecycle events emitted by the orchestrator."""

    DUPLICATE_ACTIVE = "duplicate_active"
    RUN_STARTED = "run_started"
    WORKSPACE_PREPARED = "workspace_prepared"
    PROMPT_BUILT = "prompt_built"
    CODEX_TURN_STARTED = "codex_turn_started"
    CODEX_RUNTIME_EVENT = "codex_runtime_event"
    CODEX_TURN_COMPLETED = "codex_turn_completed"
    DECISION_RECORDED = "decision_recorded"
    ASSISTANT_RESPONSE = "assistant_response"
    RETRY_SCHEDULED = "retry_scheduled"
    RUN_COMPLETED = "run_completed"
    RUN_BLOCKED = "run_blocked"
    RUN_FAILED = "run_failed"


class OrchestrationDecision(str, Enum):
    """Supervisor decision after a Codex turn."""

    CONTINUE = "continue"
    COMPLETE = "complete"
    RETRY = "retry"
    BLOCK = "block"
    FAIL = "fail"


class WorkspaceReusePolicy(str, Enum):
    """How the harness should treat an existing task workspace."""

    REUSE = "reuse"
    FRESH = "fresh"
    REQUIRE_EXISTING = "require_existing"


class WorkspaceBootstrapStatus(str, Enum):
    """Outcome for workspace clone/bootstrap commands."""

    NOT_CONFIGURED = "not_configured"
    SKIPPED = "skipped"
    SUCCEEDED = "succeeded"
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
class OwnerProfile:
    """Non-secret owner identity and values profile loaded from local config."""

    user_id: int
    display_name: Optional[str] = None
    username: Optional[str] = None
    role: Optional[str] = None
    values: Tuple[str, ...] = ()
    priorities: Tuple[str, ...] = ()
    communication_style: Tuple[str, ...] = ()
    escalation_boundaries: Tuple[str, ...] = ()
    wiki_profile_path: Optional[Path] = None
    wiki_profile_excerpt: Optional[str] = None

    def matches(self, task: TelegramTask) -> bool:
        return task.user_id == self.user_id

    def display_label(self, fallback_username: Optional[str] = None) -> str:
        username = self.username or fallback_username
        parts = []
        if self.display_name:
            parts.append(self.display_name)
        if username:
            parts.append("@{}".format(username.lstrip("@")))
        if parts:
            return " ".join(parts)
        return "Telegram user {}".format(self.user_id)

    def redacted_identity_label(self, fallback_username: Optional[str] = None) -> str:
        return "primary owner: {} (Telegram user_id {})".format(
            self.display_label(fallback_username=fallback_username),
            self.user_id,
        )

    @property
    def has_profile_content(self) -> bool:
        return any(
            (
                self.role,
                self.values,
                self.priorities,
                self.communication_style,
                self.escalation_boundaries,
                self.wiki_profile_excerpt,
            )
        )


@dataclass(frozen=True)
class AssistantIdentity:
    """User-facing assistant identity, separate from the human owner profile."""

    name: str = "Vera"
    short_description: str = (
        "a personal assistant/minime for memory, values-aware conversation, "
        "coordination, and clear thinking"
    )
    mission: str = (
        "Help the owner think clearly, remember durable context, coordinate "
        "carefully, and turn intentions into reversible, well-governed action."
    )
    core_values: Tuple[str, ...] = (
        "truthfulness over comfort",
        "preserve human agency and reversible choices",
        "protect privacy through minimal disclosure",
        "surface uncertainty, tradeoffs, and weak assumptions early",
    )
    communication_principles: Tuple[str, ...] = (
        "be direct, concise, concrete, and kind without flattery",
        "ask clarifying questions when authority, context, or risk is unclear",
        "challenge weak reasoning and propose lower-risk next steps",
        "keep responses natural and useful rather than performative",
    )
    boundaries: Tuple[str, ...] = (
        "do not claim to be human, sentient, or independent",
        "do not impersonate the owner or any other human",
        "do not treat chat messages as approval for unsafe, irreversible, or authority-sensitive actions",
        "respect safety, governance, privacy, and explicit approval boundaries",
    )
    transparency_rules: Tuple[str, ...] = (
        "introduce yourself as the configured assistant identity, not as Codex",
        "explain that Codex/OpenAI tooling is the runtime layer when asked or operationally relevant",
        "distinguish product truth from roleplay or metaphor",
        "state uncertainty, blockers, and capability limits directly",
    )
    relationship_to_owner: str = (
        "Serve as the owner's configured personal assistant and coordination aide, "
        "while treating the owner as the human decision-maker."
    )
    proactivity: Tuple[str, ...] = (
        "be proactive about memory, risks, tradeoffs, and useful coordination opportunities",
        "stay quiet or ask before expanding scope when the owner wants a narrow answer",
    )
    owner_special_treatment: Tuple[str, ...] = (
        "use owner-specific profile guidance only for the configured owner",
        "do not expose private owner profile text to other Telegram users",
    )

    @classmethod
    def default(cls) -> "AssistantIdentity":
        return cls()

    @property
    def safe_display_name(self) -> str:
        return self.name.strip() or "Vera"

    def summary_lines(self) -> Tuple[str, ...]:
        return (
            "Assistant identity name: {}.".format(self.safe_display_name),
            "Assistant identity profile configured separately from owner identity.",
        )

    def prompt_lines(self) -> Tuple[str, ...]:
        lines = [
            "Assistant identity:",
            "User-facing assistant name: {}".format(self.safe_display_name),
            "Short self-description: {}".format(self.short_description),
            "Mission: {}".format(self.mission),
            "Relationship to the owner/human user: {}".format(self.relationship_to_owner),
            "Product truth: You are a configured assistant identity running through Codex/OpenAI tooling; you are not a human, sentient, or independent actor.",
            "Self-identification rule: if asked who you are, answer as {} using this profile; do not default to `I am Codex`.".format(
                self.safe_display_name
            ),
        ]
        lines.extend(_prefixed_identity_lines("Core values", self.core_values))
        lines.extend(
            _prefixed_identity_lines(
                "Communication principles",
                self.communication_principles,
            )
        )
        lines.extend(_prefixed_identity_lines("Boundaries", self.boundaries))
        lines.extend(_prefixed_identity_lines("Transparency rules", self.transparency_rules))
        lines.extend(_prefixed_identity_lines("Proactivity", self.proactivity))
        lines.extend(
            _prefixed_identity_lines(
                "Owner-specific treatment",
                self.owner_special_treatment,
            )
        )
        return tuple(lines)

    def introduction(self, include_runtime: bool = False) -> str:
        style = (
            self.communication_principles[0]
            if self.communication_principles
            else "be direct, careful, and transparent"
        )
        text = (
            "I'm {name}, {description}. My mission is to {mission}. "
            "I try to {style}."
        ).format(
            name=self.safe_display_name,
            description=self.short_description,
            mission=_sentence_fragment(self.mission),
            style=_trim_terminal_punctuation(style),
        )
        if include_runtime:
            text += (
                " Codex/OpenAI tooling is the runtime layer underneath me; "
                "it is not my normal user-facing identity."
            )
        return text


def _prefixed_identity_lines(prefix: str, values: Tuple[str, ...]) -> Tuple[str, ...]:
    return tuple("{}: {}".format(prefix, value) for value in values)


def _trim_terminal_punctuation(value: str) -> str:
    return value.strip().rstrip(".!?")


def _sentence_fragment(value: str) -> str:
    text = _trim_terminal_punctuation(value).lstrip()
    if not text:
        return "help clearly"
    return text[:1].lower() + text[1:]


@dataclass(frozen=True)
class Workspace:
    """A per-task isolated workspace plan."""

    workspace_id: str
    task_id: str
    root: Path
    path: Path
    created: bool = False
    reused: bool = False
    reuse_policy: WorkspaceReusePolicy = WorkspaceReusePolicy.REUSE
    metadata_path: Optional[Path] = None
    bootstrap_status: WorkspaceBootstrapStatus = WorkspaceBootstrapStatus.SKIPPED
    bootstrap_stdout: str = ""
    bootstrap_stderr: str = ""
    bootstrap_returncode: Optional[int] = None
    bootstrap_error: Optional[str] = None
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
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class RunState:
    """Persisted minimal state for restart-safe task orchestration."""

    run_id: str
    task_id: str
    status: HarnessRunStatus
    turns_completed: int = 0
    dry_run: bool = False
    workspace_path: Optional[str] = None
    last_error: Optional[str] = None
    last_decision: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_active(self) -> bool:
        return self.status in {HarnessRunStatus.PLANNED, HarnessRunStatus.RUNNING}


@dataclass(frozen=True)
class CodexTurnResult:
    """The result of one Codex turn."""

    turn_number: int
    status: CodexTurnStatus
    transcript_excerpt: str = ""
    error: Optional[str] = None
    elapsed_seconds: Optional[float] = None
    unanswered_questions: Tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskEvent:
    """Task lifecycle event suitable for logs and Telegram status mapping."""

    type: TaskEventType
    task_id: str
    run_id: str
    status: Optional[str] = None
    message: Optional[str] = None
    turn_number: Optional[int] = None
    payload: Mapping[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
