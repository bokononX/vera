"""Deterministic conversation-to-user-memory wiki ingest helpers."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .models import TelegramTask


class UserMemoryIngestError(RuntimeError):
    """Raised when a user-memory ingest cannot be planned or applied."""


class UserMemoryLintError(RuntimeError):
    """Raised when a user-memory lint/consolidation pass cannot be planned."""


class PageType(str, Enum):
    CONCEPT = "concept"
    VALUE = "value"
    PREFERENCE = "preference"
    PROJECT = "project"
    PERSON = "person"
    ORG = "org"
    DECISION = "decision"
    CORRECTION = "correction"
    OPEN_QUESTION = "open_question"
    OBSERVATION = "observation"


class MemoryState(str, Enum):
    CONFIRMED = "confirmed"
    INFERRED = "inferred"
    OBSERVED_PATTERN = "observed_pattern"
    OPEN_QUESTION = "open_question"
    CORRECTION = "correction"


class SourceRetention(str, Enum):
    HASH_ONLY = "hash_only"
    STORE = "store"


class UserMemoryTaskType(str, Enum):
    """Broad task scopes used to bias user-memory retrieval."""

    GENERAL = "general"
    PROJECT_EXECUTION = "project_execution"
    USER_REPRESENTATION = "user_representation"
    SOCIAL_COORDINATION = "social_coordination"
    CORRECTION_HANDLING = "correction_handling"
    MEMORY_MAINTENANCE = "memory_maintenance"


class RelationshipType(str, Enum):
    SIMILAR_TO = "similar-to"
    CONTAINS = "contains"
    CONTRADICTS = "contradicts"
    REFINES = "refines"
    DEPENDS_ON = "depends-on"
    EXAMPLE_OF = "example-of"


PAGE_DIRECTORIES: Mapping[PageType, str] = {
    PageType.CONCEPT: "concepts",
    PageType.VALUE: "values",
    PageType.PREFERENCE: "preferences",
    PageType.PROJECT: "projects",
    PageType.PERSON: "people",
    PageType.ORG: "orgs",
    PageType.DECISION: "decisions",
    PageType.CORRECTION: "corrections",
    PageType.OPEN_QUESTION: "questions",
    PageType.OBSERVATION: "observations",
}

INDEX_HEADINGS: Mapping[PageType, str] = {
    PageType.CONCEPT: "Concepts",
    PageType.VALUE: "Values",
    PageType.PREFERENCE: "Preferences",
    PageType.PROJECT: "Projects",
    PageType.PERSON: "People",
    PageType.ORG: "Organizations",
    PageType.DECISION: "Decisions",
    PageType.CORRECTION: "Corrections",
    PageType.OPEN_QUESTION: "Open Questions",
    PageType.OBSERVATION: "Observations",
}

SECRET_RE = re.compile(
    r"\b(password|passcode|secret|api[_ -]?key|private key|token|credential)\b",
    re.IGNORECASE,
)

USER_SPEAKERS = {"user", "human", "owner", "telegram"}
ASSISTANT_SPEAKERS = {"assistant", "vera", "herald", "codex", "system"}

STOPWORDS = {
    "a",
    "about",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "do",
    "for",
    "from",
    "help",
    "i",
    "in",
    "into",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "please",
    "that",
    "the",
    "this",
    "to",
    "use",
    "we",
    "when",
    "with",
    "you",
}

HIGH_STAKES_TASK_RE = re.compile(
    r"\b(delete|publish|send|email|sign|pay|buy|sell|transfer|legal|medical|"
    r"financial|finance|fire|hire|irreversible|credential|password|token|secret)\b",
    re.IGNORECASE,
)

REQUIRED_WIKI_FRONTMATTER_FIELDS = (
    "id",
    "title",
    "page_type",
    "owner_user",
    "status",
    "memory_state",
    "confidence_level",
    "confidence_score",
    "sensitivity",
    "prompt_visibility",
    "review_status",
    "created_at",
    "updated_at",
    "last_observed_at",
    "last_confirmed_at",
    "stale_after",
    "source_refs",
    "related",
    "supersedes",
    "superseded_by",
    "contradictions",
    "corrections",
    "tags",
)

WIKI_STATUS_VALUES = {"active", "draft", "contested", "stale", "archived", "deleted"}
WIKI_MEMORY_STATE_VALUES = {
    "confirmed",
    "inferred",
    "observed_pattern",
    "open_question",
    "correction",
    "retracted",
}
WIKI_CONFIDENCE_LEVELS = {"high", "medium", "low"}
WIKI_SENSITIVITY_VALUES = {"public", "internal", "private", "restricted", "secret"}
WIKI_PROMPT_VISIBILITY_VALUES = {"safe", "task_only", "confirm_first", "never"}
WIKI_REVIEW_STATUS_VALUES = {
    "unreviewed",
    "llm_reviewed",
    "user_confirmed",
    "needs_user_review",
    "disputed",
    "deletion_pending",
}
WIKI_RELATIONSHIP_LIST_FIELDS = (
    "related",
    "supersedes",
    "superseded_by",
    "contradictions",
    "corrections",
)


@dataclass(frozen=True)
class ConversationMessage:
    """Normalized memory-ingest message."""

    speaker: str
    text: str
    message_id: Optional[str] = None
    timestamp: Optional[datetime] = None
    channel: Optional[str] = None

    @property
    def locator(self) -> str:
        if self.message_id:
            return "message:{}".format(self.message_id)
        return "message:unknown"


@dataclass(frozen=True)
class CandidateSourceRef:
    """A non-raw source reference attached to one candidate claim."""

    source_id: str
    path: str
    locator: str
    claim: str
    support: str
    excerpt_hash: str


@dataclass(frozen=True)
class MemoryCandidate:
    """A proposed wiki memory update extracted from messages."""

    page_type: PageType
    title: str
    claim: str
    memory_state: MemoryState
    confidence_level: str
    confidence_score: float
    sensitivity: str
    prompt_visibility: str
    review_status: str
    source_refs: Tuple[CandidateSourceRef, ...]
    tags: Tuple[str, ...] = ()
    related: Tuple[str, ...] = ()
    correction_target: Optional[Tuple[PageType, str]] = None
    from_correction: bool = False

    @property
    def slug(self) -> str:
        return slugify(self.title)

    @property
    def relative_path(self) -> str:
        return "wiki/{}/{}.md".format(PAGE_DIRECTORIES[self.page_type], self.slug)

    @property
    def stable_id(self) -> str:
        return "mem-{}-{}".format(self.page_type.value.replace("_", "-"), self.slug)


@dataclass(frozen=True)
class SourceRecord:
    """Source manifest record for an ingest."""

    source_id: str
    path: str
    source_type: str
    channel: str
    captured_at: datetime
    source_event_at: Optional[datetime]
    sha256: str
    sensitivity: str
    consent_scope: str
    retention: SourceRetention
    redaction_state: str
    message_count: int


@dataclass(frozen=True)
class ProposedWikiEdit:
    """A planned page mutation."""

    action: str
    path: Path
    relative_path: str
    candidate: MemoryCandidate
    contradiction: bool = False


@dataclass(frozen=True)
class ContradictionRecord:
    """A planned contradiction/review queue entry."""

    path: str
    title: str
    existing_summary: str
    new_summary: str
    source_id: str
    proposed_resolution: str


@dataclass(frozen=True)
class IngestPlan:
    """A deterministic user-memory ingest plan."""

    root: Path
    owner_user: str
    source_record: SourceRecord
    candidates: Tuple[MemoryCandidate, ...]
    edits: Tuple[ProposedWikiEdit, ...]
    contradictions: Tuple[ContradictionRecord, ...]
    withheld_secret_count: int
    source_text: str
    apply: bool = False

    def format_human_readable(self) -> str:
        mode = "apply" if self.apply else "dry-run"
        lines = [
            "User memory ingest plan ({})".format(mode),
            "root: {}".format(self.root),
            "owner_user: {}".format(self.owner_user),
            "source_id: {}".format(self.source_record.source_id),
            "source_retention: {}".format(self.source_record.retention.value),
            "raw_content_written: {}".format(
                "yes" if self.source_record.retention == SourceRetention.STORE else "no"
            ),
            "candidates: {}".format(len(self.candidates)),
            "withheld_secret_candidates: {}".format(self.withheld_secret_count),
            "",
            "Proposed wiki edits:",
        ]
        if not self.edits:
            lines.append("- none")
        for edit in self.edits:
            suffix = ""
            if edit.contradiction:
                suffix = " (contradiction/correction review)"
            lines.append(
                "- {} {}: {} [{}; confidence: {}]{}".format(
                    edit.action,
                    edit.relative_path,
                    edit.candidate.title,
                    edit.candidate.memory_state.value,
                    edit.candidate.confidence_level,
                    suffix,
                )
            )
            lines.append("  claim: {}".format(edit.candidate.claim))
        lines.extend(["", "Review queue changes:"])
        if not self.contradictions:
            lines.append("- none")
        for contradiction in self.contradictions:
            lines.append(
                "- review/contradictions.md: {} conflicts with existing {}".format(
                    contradiction.new_summary,
                    contradiction.path,
                )
            )
        lines.extend(["", "Index/log changes:"])
        lines.append("- rebuild index.md from active wiki pages")
        lines.append("- append log.md ingest entry for {}".format(self.source_record.source_id))
        if not self.apply:
            lines.extend(["", "Dry-run only: no files were mutated."])
        return "\n".join(lines)


@dataclass(frozen=True)
class IngestOptions:
    """Options for planning or applying an ingest."""

    root: Path
    owner_user: str
    channel: str = "codex"
    source_id: Optional[str] = None
    captured_at: Optional[datetime] = None
    source_retention: SourceRetention = SourceRetention.HASH_ONLY
    consent_scope: str = "store"


@dataclass(frozen=True)
class WikiLintOptions:
    """Options for a user-memory wiki lint/consolidation pass."""

    root: Path
    owner_user: Optional[str] = None
    as_of: Optional[datetime] = None
    apply: bool = False


@dataclass(frozen=True)
class WikiLintIssue:
    """One concrete lint finding."""

    category: str
    severity: str
    path: str
    message: str
    details: Tuple[str, ...] = ()


@dataclass(frozen=True)
class WikiDuplicateCandidate:
    """A duplicate/consolidation candidate that requires review."""

    paths: Tuple[str, str]
    reason: str
    confidence: float


@dataclass(frozen=True)
class WikiRelationshipSuggestion:
    """Suggested explicit relationship type for a generic wiki link."""

    source_path: str
    target_path: str
    suggested_type: RelationshipType
    reason: str


@dataclass(frozen=True)
class WikiReviewItem:
    """Judgment-requiring consolidation work item."""

    category: str
    path: str
    summary: str
    context: Tuple[str, ...]
    alternatives: Tuple[str, ...]


@dataclass(frozen=True)
class WikiSafeFix:
    """A mechanical fix that lint may apply in controlled mode."""

    action: str
    path: str
    description: str
    applied: bool = False


@dataclass(frozen=True)
class WikiPageRecord:
    """A raw wiki page plus parsed metadata used for linting."""

    path: Path
    relative_path: str
    frontmatter: Optional[str]
    metadata: Mapping[str, object]
    body_text: str
    page: Optional[UserMemoryPage]


@dataclass(frozen=True)
class WikiLintReport:
    """Reviewable report for one lint/consolidation pass."""

    root: Path
    as_of: datetime
    apply: bool
    issues: Tuple[WikiLintIssue, ...]
    duplicate_candidates: Tuple[WikiDuplicateCandidate, ...]
    orphan_pages: Tuple[str, ...]
    stale_pages: Tuple[str, ...]
    missing_metadata: Tuple[WikiLintIssue, ...]
    unresolved_contradictions: Tuple[WikiLintIssue, ...]
    relationship_type_suggestions: Tuple[WikiRelationshipSuggestion, ...]
    review_items: Tuple[WikiReviewItem, ...]
    safe_fixes: Tuple[WikiSafeFix, ...]

    @property
    def has_findings(self) -> bool:
        return bool(
            self.issues
            or self.duplicate_candidates
            or self.orphan_pages
            or self.stale_pages
            or self.relationship_type_suggestions
            or self.review_items
            or self.safe_fixes
        )

    def format_human_readable(self) -> str:
        mode = "apply" if self.apply else "dry-run"
        lines = [
            "User memory lint/consolidation report ({})".format(mode),
            "root: {}".format(self.root),
            "as_of: {}".format(_format_dt(self.as_of)),
            "issues: {}".format(len(self.issues)),
            "safe_fixes: {}".format(len(self.safe_fixes)),
            "review_items: {}".format(len(self.review_items)),
            "",
        ]
        _format_report_section(
            lines,
            "Duplicate candidates",
            (
                "- {} <-> {} (confidence {:.2f}): {}".format(
                    item.paths[0],
                    item.paths[1],
                    item.confidence,
                    item.reason,
                )
                for item in self.duplicate_candidates
            ),
        )
        _format_report_section(lines, "Orphan pages", ("- {}".format(path) for path in self.orphan_pages))
        _format_report_section(lines, "Stale pages", ("- {}".format(path) for path in self.stale_pages))
        _format_report_section(
            lines,
            "Missing metadata",
            ("- {}: {}".format(item.path, item.message) for item in self.missing_metadata),
        )
        _format_report_section(
            lines,
            "Unresolved contradictions",
            ("- {}: {}".format(item.path, item.message) for item in self.unresolved_contradictions),
        )
        _format_report_section(
            lines,
            "Relationship type suggestions",
            (
                "- {} -> {}: {} ({})".format(
                    item.source_path,
                    item.target_path,
                    item.suggested_type.value,
                    item.reason,
                )
                for item in self.relationship_type_suggestions
            ),
        )
        _format_report_section(
            lines,
            "Safe mechanical fixes",
            (
                "- {} {}: {}".format(
                    "applied" if item.applied else "proposed",
                    item.path,
                    item.description,
                )
                for item in self.safe_fixes
            ),
        )
        _format_report_section(
            lines,
            "Review items",
            (_format_review_item(item) for item in self.review_items),
        )
        if not self.apply:
            lines.extend(["", "Dry-run only: no files were mutated."])
        return "\n".join(lines).rstrip() + "\n"


@dataclass(frozen=True)
class UserMemorySourceRef:
    """Prompt-safe provenance for one wiki-page claim."""

    source_id: str
    path: Optional[str] = None
    locator: Optional[str] = None
    claim: Optional[str] = None
    support: Optional[str] = None


@dataclass(frozen=True)
class UserMemoryPage:
    """A synthesized wiki page loaded for retrieval."""

    id: str
    title: str
    page_type: PageType
    relative_path: str
    status: str
    memory_state: str
    confidence_level: str
    confidence_score: Optional[float]
    sensitivity: str
    prompt_visibility: str
    review_status: str
    source_refs: Tuple[UserMemorySourceRef, ...]
    tags: Tuple[str, ...]
    related: Tuple[str, ...]
    contradictions: Tuple[str, ...]
    corrections: Tuple[str, ...]
    summary: str
    body_text: str

    @property
    def provenance_label(self) -> str:
        source = self.source_refs[0].source_id if self.source_refs else self.relative_path
        return "page: {}; source: {}; confidence: {}; sensitivity: {}".format(
            self.relative_path,
            source,
            self.confidence_level,
            self.sensitivity,
        )

    @property
    def audit_ref(self) -> str:
        return "{}|{}".format(self.id, self.relative_path)


@dataclass(frozen=True)
class UserMemoryRetrievalOptions:
    """Options controlling prompt retrieval privacy and size."""

    root: Path
    max_pages: int = 5
    task_type: Optional[UserMemoryTaskType] = None
    allow_private: bool = False
    allow_restricted: bool = False


@dataclass(frozen=True)
class UserMemoryPromptContext:
    """Bounded, prompt-ready memory context for one task."""

    task_type: UserMemoryTaskType
    facts: Tuple[str, ...]
    caveats: Tuple[str, ...]
    confirmation_constraints: Tuple[str, ...]
    selected_pages: Tuple[UserMemoryPage, ...]
    omitted_private_count: int = 0
    omitted_sensitive_count: int = 0
    omitted_irrelevant_count: int = 0

    @property
    def used_page_refs(self) -> Tuple[str, ...]:
        return tuple(page.audit_ref for page in self.selected_pages)

    @property
    def has_prompt_content(self) -> bool:
        return bool(self.facts or self.caveats or self.confirmation_constraints)

    def render_prompt_block(self) -> str:
        """Render the compact user-memory packet for Codex prompts."""

        if not self.has_prompt_content:
            return ""
        lines = [
            "## User Memory Context",
            "",
            "Use only this task-relevant memory. Treat caveats as constraints, not facts.",
        ]
        if self.facts:
            lines.extend(["", "Relevant memory:"])
            lines.extend("- {}".format(item) for item in self.facts)
        if self.caveats:
            lines.extend(["", "Caveats and unresolved memory:"])
            lines.extend("- {}".format(item) for item in self.caveats)
        if self.confirmation_constraints:
            lines.extend(["", "Confirmation constraints:"])
            lines.extend("- {}".format(item) for item in self.confirmation_constraints)
        omitted = []
        if self.omitted_private_count:
            omitted.append("{} private".format(self.omitted_private_count))
        if self.omitted_sensitive_count:
            omitted.append("{} restricted/secret".format(self.omitted_sensitive_count))
        if self.omitted_irrelevant_count:
            omitted.append("{} irrelevant".format(self.omitted_irrelevant_count))
        if omitted:
            lines.extend(
                [
                    "",
                    "Omitted: {} memory page(s) were not included by privacy or relevance gates.".format(
                        ", ".join(omitted)
                    ),
                ]
            )
        return "\n".join(lines)


def retrieve_user_memory_for_task(
    task: TelegramTask,
    options: UserMemoryRetrievalOptions,
) -> UserMemoryPromptContext:
    """Retrieve a bounded, privacy-filtered memory packet for a Telegram task."""

    task_type = options.task_type or infer_user_memory_task_type(task.text)
    pages = load_user_memory_pages(options.root)
    query_tokens = _tokenize_for_retrieval(task.text)
    scored: List[Tuple[float, UserMemoryPage]] = []
    omitted_private = 0
    omitted_sensitive = 0
    omitted_irrelevant = 0
    relevant_but_gated: List[UserMemoryPage] = []

    for page in pages:
        if _page_is_deleted_or_unusable(page):
            continue
        score = _memory_relevance_score(page, query_tokens, task_type)
        if score <= 0:
            omitted_irrelevant += 1
            continue
        gate = _privacy_gate(page, options)
        if gate == "private":
            omitted_private += 1
            relevant_but_gated.append(page)
            continue
        if gate == "sensitive":
            omitted_sensitive += 1
            relevant_but_gated.append(page)
            continue
        scored.append((score, page))

    selected = _bounded_selection(scored, options.max_pages)
    selected = _include_related_guardrails(selected, pages, options, max_pages=options.max_pages)
    selected_paths = {page.relative_path for page in selected}
    facts: List[str] = []
    caveats: List[str] = []
    confirmation_constraints: List[str] = []

    for page in selected:
        if _page_is_caveat(page):
            caveats.append(_format_memory_caveat(page))
        else:
            facts.append(_format_memory_fact(page))
        if page.prompt_visibility == "confirm_first":
            confirmation_constraints.append(
                "Confirm before relying on {} because its prompt visibility is `confirm_first`.".format(
                    page.relative_path
                )
            )
        if page.status == "contested" or page.contradictions:
            confirmation_constraints.append(
                "Do not resolve contested memory from {} without explicit user confirmation.".format(
                    page.relative_path
                )
            )

    if selected and _task_high_stakes_signal(task.text):
        confirmation_constraints.append(
            "The task appears high-stakes or irreversible; ask for confirmation before external side effects or durable commitments."
        )

    for page in relevant_but_gated:
        if page.prompt_visibility == "confirm_first":
            caveats.append(
                "Relevant memory exists but requires confirmation before use [{}].".format(
                    page.provenance_label
                )
            )

    return UserMemoryPromptContext(
        task_type=task_type,
        facts=tuple(_dedupe_strings(facts)),
        caveats=tuple(_dedupe_strings(caveats)),
        confirmation_constraints=tuple(_dedupe_strings(confirmation_constraints)),
        selected_pages=tuple(page for page in selected if page.relative_path in selected_paths),
        omitted_private_count=omitted_private,
        omitted_sensitive_count=omitted_sensitive,
        omitted_irrelevant_count=omitted_irrelevant,
    )


def infer_user_memory_task_type(text: str) -> UserMemoryTaskType:
    """Infer a coarse task scope from Telegram task text."""

    lower = text.lower()
    if re.search(r"\b(memory|wiki|remember|retrieve|retrieval|preference|profile)\b", lower):
        return UserMemoryTaskType.MEMORY_MAINTENANCE
    if re.search(r"\b(actually|correction|correct|not that|instead)\b", lower):
        return UserMemoryTaskType.CORRECTION_HANDLING
    if re.search(r"\b(email|message|meeting|coordinate|intro|follow up|follow-up|negotiate)\b", lower):
        return UserMemoryTaskType.SOCIAL_COORDINATION
    if re.search(r"\b(value|values|style|preference|represent|for me|my view)\b", lower):
        return UserMemoryTaskType.USER_REPRESENTATION
    if re.search(r"\b(implement|test|code|repo|project|ticket|pr|pull request|debug|run)\b", lower):
        return UserMemoryTaskType.PROJECT_EXECUTION
    return UserMemoryTaskType.GENERAL


def load_user_memory_pages(root: Path) -> Tuple[UserMemoryPage, ...]:
    """Load synthesized wiki pages from a user-memory corpus root."""

    root = root.expanduser().resolve()
    wiki_root = root / "wiki"
    if not wiki_root.exists() or not wiki_root.is_dir():
        return ()
    index_paths = _paths_from_index(root / "index.md", root)
    discovered = sorted(wiki_root.glob("*/*.md"))
    by_path: Dict[str, Path] = {}
    for path in index_paths + tuple(discovered):
        try:
            relative = path.resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        by_path[relative] = path
    pages: List[UserMemoryPage] = []
    for relative in sorted(by_path):
        page = _load_user_memory_page(by_path[relative], root)
        if page is not None:
            pages.append(page)
    return tuple(pages)


def parse_conversation_text(text: str, channel: str = "codex") -> Tuple[ConversationMessage, ...]:
    """Parse a lightweight transcript into normalized messages."""

    messages: List[ConversationMessage] = []
    current_speaker = "user"
    current_lines: List[str] = []
    current_id: Optional[str] = None

    def flush() -> None:
        nonlocal current_lines, current_id, current_speaker
        joined = "\n".join(line.strip() for line in current_lines).strip()
        if joined:
            messages.append(
                ConversationMessage(
                    speaker=_normalize_speaker(current_speaker),
                    text=joined,
                    message_id=current_id,
                    channel=channel,
                )
            )
        current_lines = []
        current_id = None

    for index, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            flush()
            continue
        match = re.match(r"^([A-Za-z][A-Za-z _-]{0,24})\s*[:>-]\s*(.*)$", line)
        if match and _looks_like_speaker(match.group(1)):
            flush()
            current_speaker = match.group(1)
            current_id = str(index)
            if match.group(2).strip():
                current_lines.append(match.group(2).strip())
            continue
        if not current_lines:
            current_id = str(index)
        current_lines.append(line)
    flush()
    return tuple(messages)


def messages_from_telegram_tasks(tasks: Sequence[TelegramTask]) -> Tuple[ConversationMessage, ...]:
    """Convert normalized Telegram tasks into ingest messages."""

    return tuple(
        ConversationMessage(
            speaker="telegram",
            text=task.text,
            message_id=str(task.message_id),
            timestamp=task.received_at,
            channel="telegram",
        )
        for task in tasks
    )


def load_messages_from_file(path: Path, channel: str = "codex") -> Tuple[Tuple[ConversationMessage, ...], str]:
    """Load transcript text or normalized Telegram JSON from a file."""

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UserMemoryIngestError("conversation file cannot be read: {}".format(exc))
    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise UserMemoryIngestError("conversation JSON is invalid: {}".format(exc))
        return messages_from_json_payload(payload), _canonical_source_text(payload)
    return parse_conversation_text(raw_text, channel=channel), raw_text


def messages_from_json_payload(payload: Any) -> Tuple[ConversationMessage, ...]:
    """Parse supported normalized Telegram/chat JSON shapes."""

    if isinstance(payload, Mapping) and "messages" in payload:
        raw_messages = payload["messages"]
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        raw_messages = payload
    else:
        raw_messages = (payload,)
    if not isinstance(raw_messages, Sequence) or isinstance(raw_messages, (str, bytes, bytearray)):
        raise UserMemoryIngestError("conversation JSON must contain a message object or list")

    messages: List[ConversationMessage] = []
    for index, item in enumerate(raw_messages, start=1):
        if not isinstance(item, Mapping):
            raise UserMemoryIngestError("conversation JSON message {} must be an object".format(index))
        if "message" in item and isinstance(item["message"], Mapping):
            telegram = item["message"]
            sender = telegram.get("from") if isinstance(telegram.get("from"), Mapping) else {}
            text = _required_text(telegram.get("text"), "message.text")
            message_id = str(telegram.get("message_id", index))
            timestamp = _optional_datetime(item.get("received_at") or telegram.get("date"))
            speaker = "telegram"
            if isinstance(sender, Mapping) and sender.get("is_bot") is True:
                speaker = "assistant"
        else:
            text = _required_text(item.get("text") or item.get("message"), "text")
            message_id = str(item.get("message_id") or item.get("id") or index)
            timestamp = _optional_datetime(item.get("received_at") or item.get("timestamp"))
            speaker = _normalize_speaker(str(item.get("speaker") or item.get("role") or "telegram"))
        messages.append(
            ConversationMessage(
                speaker=speaker,
                text=text,
                message_id=message_id,
                timestamp=timestamp,
                channel="telegram",
            )
        )
    return tuple(messages)


def plan_user_memory_ingest(
    messages: Sequence[ConversationMessage],
    source_text: str,
    options: IngestOptions,
    apply: bool = False,
) -> IngestPlan:
    """Create a deterministic dry-run/apply plan without mutating files."""

    normalized_messages = tuple(messages)
    if not normalized_messages:
        raise UserMemoryIngestError("at least one conversation message is required")
    captured_at = options.captured_at or datetime.now(timezone.utc)
    source_hash = _sha256(source_text)
    source_id = options.source_id or _default_source_id(
        captured_at=captured_at,
        channel=options.channel,
        digest=source_hash,
    )
    source_path = _source_path(
        source_id=source_id,
        channel=options.channel,
        retention=options.source_retention,
    )
    source_record = SourceRecord(
        source_id=source_id,
        path=source_path,
        source_type="conversation",
        channel=options.channel,
        captured_at=captured_at,
        source_event_at=_first_event_at(normalized_messages),
        sha256=source_hash,
        sensitivity=_source_sensitivity(normalized_messages),
        consent_scope=options.consent_scope,
        retention=options.source_retention,
        redaction_state="none" if options.source_retention == SourceRetention.STORE else "redacted",
        message_count=len(normalized_messages),
    )
    candidates, withheld_secret_count = extract_memory_candidates(
        normalized_messages,
        source_record=source_record,
    )
    edits: List[ProposedWikiEdit] = []
    contradictions: List[ContradictionRecord] = []
    for candidate in candidates:
        relative_path = candidate.relative_path
        page_path = options.root / relative_path
        existing = _read_text_if_exists(page_path)
        action = "create"
        contradiction = False
        if existing is not None:
            action = "unchanged" if _candidate_already_present(existing, candidate) else "update"
            if candidate.from_correction and action == "update":
                contradiction = True
                contradictions.append(
                    ContradictionRecord(
                        path=relative_path,
                        title=candidate.title,
                        existing_summary=_first_claim_summary(existing),
                        new_summary=candidate.claim,
                        source_id=source_record.source_id,
                        proposed_resolution=(
                            "Record the user correction, keep the older claim visible for review, "
                            "and prefer the correction for prompt use unless a reviewer marks it ambiguous."
                        ),
                    )
                )
        edits.append(
            ProposedWikiEdit(
                action=action,
                path=page_path,
                relative_path=relative_path,
                candidate=candidate,
                contradiction=contradiction,
            )
        )
    return IngestPlan(
        root=options.root,
        owner_user=options.owner_user,
        source_record=source_record,
        candidates=candidates,
        edits=tuple(edits),
        contradictions=tuple(contradictions),
        withheld_secret_count=withheld_secret_count,
        source_text=source_text,
        apply=apply,
    )


def apply_ingest_plan(plan: IngestPlan) -> IngestPlan:
    """Apply a previously planned ingest to a user-memory wiki root."""

    plan.root.mkdir(parents=True, exist_ok=True)
    _ensure_memory_root(plan)
    _write_source_record(plan)
    changed_pages: List[str] = []
    for edit in plan.edits:
        if edit.action == "unchanged":
            continue
        edit.path.parent.mkdir(parents=True, exist_ok=True)
        if edit.action == "create":
            edit.path.write_text(_new_page_markdown(plan, edit.candidate), encoding="utf-8")
        elif edit.action == "update":
            existing = edit.path.read_text(encoding="utf-8")
            edit.path.write_text(
                _updated_page_markdown(plan, existing, edit.candidate, edit.contradiction),
                encoding="utf-8",
            )
        else:
            raise UserMemoryIngestError("unsupported edit action: {}".format(edit.action))
        changed_pages.append(edit.relative_path)
    _update_contradictions(plan)
    _rebuild_index(plan.root, plan.owner_user)
    _append_log(plan, changed_pages)
    return replace(plan, apply=True)


def ingest_user_memory(
    messages: Sequence[ConversationMessage],
    source_text: str,
    options: IngestOptions,
    apply: bool = False,
) -> IngestPlan:
    """Plan, and optionally apply, a user-memory ingest."""

    plan = plan_user_memory_ingest(
        messages=messages,
        source_text=source_text,
        options=options,
        apply=apply,
    )
    if not apply:
        return plan
    return apply_ingest_plan(plan)


def lint_user_memory(options: WikiLintOptions) -> WikiLintReport:
    """Plan, and optionally apply, a deterministic user-memory wiki lint pass."""

    report = plan_user_memory_lint(options)
    if not options.apply:
        return report
    return apply_user_memory_lint(report, options)


def plan_user_memory_lint(options: WikiLintOptions) -> WikiLintReport:
    """Create a reviewable user-memory lint/consolidation report without mutating files."""

    root = options.root.expanduser().resolve()
    as_of = (options.as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
    records = _load_wiki_page_records(root)
    records_by_path = {record.relative_path: record for record in records}
    index_paths = set(_index_relative_paths(root))
    inbound_refs = _inbound_wiki_references(root, records)
    manifest_sources = _manifest_sources(root)

    issues: List[WikiLintIssue] = []
    missing_metadata: List[WikiLintIssue] = []
    unresolved_contradictions: List[WikiLintIssue] = []
    stale_pages: List[str] = []
    orphan_pages: List[str] = []
    safe_fixes: List[WikiSafeFix] = []
    review_items: List[WikiReviewItem] = []

    for record in records:
        metadata_issues = _metadata_lint_issues(record)
        missing_metadata.extend(metadata_issues)
        issues.extend(metadata_issues)
        source_issues = _source_ref_lint_issues(record, root, manifest_sources)
        issues.extend(source_issues)
        if _is_prompt_eligible_secret(record, manifest_sources):
            issues.append(
                WikiLintIssue(
                    category="source-safety",
                    severity="error",
                    path=record.relative_path,
                    message="Prompt-eligible page cites a secret source.",
                    details=("Set prompt_visibility to `never` or remove the secret source citation.",),
                )
            )
        if _is_stale_record(record, as_of):
            stale_pages.append(record.relative_path)
            issues.append(
                WikiLintIssue(
                    category="stale",
                    severity="warning",
                    path=record.relative_path,
                    message="Page is older than its stale_after window.",
                    details=("Apply mode can mark the page stale without rewriting the claim.",),
                )
            )
            safe_fixes.append(
                WikiSafeFix(
                    action="mark_stale",
                    path=record.relative_path,
                    description="Set status to `stale` and review_status to `needs_user_review`.",
                )
            )
        if _is_unresolved_contradiction(record, root):
            issue = WikiLintIssue(
                category="contradiction",
                severity="warning",
                path=record.relative_path,
                message="Contradiction is unresolved and must remain reviewable.",
                details=("Do not smooth this into a consolidated claim without explicit review.",),
            )
            unresolved_contradictions.append(issue)
            issues.append(issue)
            review_items.append(
                WikiReviewItem(
                    category="contradiction",
                    path=record.relative_path,
                    summary="Resolve or preserve contested memory.",
                    context=_review_context(record),
                    alternatives=(
                        "Keep both claims visible and add/confirm review/contradictions.md context.",
                        "Resolve only with explicit user correction or reviewer decision.",
                    ),
                )
            )
        if record.page is not None and record.page.status == "active" and record.relative_path not in index_paths:
            safe_fixes.append(
                WikiSafeFix(
                    action="rebuild_index",
                    path="index.md",
                    description="Rebuild index.md so active page {} is indexed.".format(
                        record.relative_path
                    ),
                )
            )
        if _is_orphan_record(record, index_paths, inbound_refs):
            orphan_pages.append(record.relative_path)
            issues.append(
                WikiLintIssue(
                    category="orphan",
                    severity="warning",
                    path=record.relative_path,
                    message="Active page has no index entry or inbound wiki references.",
                    details=("Archive, link, or explicitly keep after review.",),
                )
            )
            review_items.append(
                WikiReviewItem(
                    category="orphan",
                    path=record.relative_path,
                    summary="Decide whether this page should be linked, archived, or kept as standalone memory.",
                    context=_review_context(record),
                    alternatives=(
                        "Link it from a relevant higher-level page and rebuild the index.",
                        "Archive it if it is no longer useful.",
                        "Keep it standalone only with an explicit review note.",
                    ),
                )
            )

    duplicate_candidates = _duplicate_candidates(records)
    for duplicate in duplicate_candidates:
        review_items.append(
            WikiReviewItem(
                category="duplicate",
                path=", ".join(duplicate.paths),
                summary="Review duplicate/consolidation candidate.",
                context=(duplicate.reason,),
                alternatives=(
                    "Merge pages while preserving all source_refs and correction links.",
                    "Keep separate and add distinguishing relationship/context notes.",
                ),
            )
        )

    relationship_suggestions = _relationship_type_suggestions(records_by_path)
    for suggestion in relationship_suggestions:
        review_items.append(
            WikiReviewItem(
                category="relationship",
                path=suggestion.source_path,
                summary="Replace generic `related` meaning with explicit `{}` relationship.".format(
                    suggestion.suggested_type.value
                ),
                context=(
                    "{} links to {} via generic `related`.".format(
                        suggestion.source_path,
                        suggestion.target_path,
                    ),
                    suggestion.reason,
                ),
                alternatives=(
                    "Record the relationship as `{}` in a review/apply proposal.".format(
                        suggestion.suggested_type.value
                    ),
                    "Leave as generic only if the typed relationship is genuinely ambiguous.",
                ),
            )
        )

    concept_level_items = _concept_level_review_items(records)
    review_items.extend(concept_level_items)
    for item in concept_level_items:
        issues.append(
            WikiLintIssue(
                category="concept-level",
                severity="info",
                path=item.path,
                message=item.summary,
                details=item.alternatives,
            )
        )

    missing_backlink_fixes = _missing_backlink_fixes(records_by_path)
    safe_fixes.extend(missing_backlink_fixes)
    if any(fix.action in {"rebuild_index", "add_backlink", "mark_stale"} for fix in safe_fixes):
        safe_fixes.append(
            WikiSafeFix(
                action="append_log",
                path="log.md",
                description="Append lint/consolidation activity with issue, review, and fix counts.",
            )
        )

    safe_fixes = _dedupe_safe_fixes(safe_fixes)
    return WikiLintReport(
        root=root,
        as_of=as_of,
        apply=False,
        issues=tuple(issues),
        duplicate_candidates=tuple(duplicate_candidates),
        orphan_pages=tuple(sorted(set(orphan_pages))),
        stale_pages=tuple(sorted(set(stale_pages))),
        missing_metadata=tuple(missing_metadata),
        unresolved_contradictions=tuple(unresolved_contradictions),
        relationship_type_suggestions=tuple(relationship_suggestions),
        review_items=tuple(review_items),
        safe_fixes=tuple(safe_fixes),
    )


def apply_user_memory_lint(report: WikiLintReport, options: WikiLintOptions) -> WikiLintReport:
    """Apply only the high-confidence mechanical fixes from a lint report."""

    root = report.root
    owner_user = options.owner_user or _owner_user_from_records(_load_wiki_page_records(root)) or "default"
    applied: List[WikiSafeFix] = []
    rebuild_needed = False
    log_needed = False
    for fix in report.safe_fixes:
        if fix.action == "rebuild_index":
            rebuild_needed = True
            applied.append(replace(fix, applied=True))
        elif fix.action == "add_backlink":
            target_path, field, source_path = _parse_backlink_fix(fix)
            if target_path is not None and field is not None and source_path is not None:
                _append_frontmatter_list_value(root / target_path, field, source_path)
                applied.append(replace(fix, applied=True))
        elif fix.action == "mark_stale":
            page_path = root / fix.path
            if page_path.exists():
                content = page_path.read_text(encoding="utf-8")
                content = _replace_frontmatter_scalar(content, "status", "stale")
                content = _replace_frontmatter_scalar(content, "review_status", "needs_user_review")
                page_path.write_text(content, encoding="utf-8")
                applied.append(replace(fix, applied=True))
        elif fix.action == "append_log":
            log_needed = True
    if rebuild_needed:
        _rebuild_index(root, owner_user)
    if log_needed:
        _append_lint_log(
            root=root,
            as_of=report.as_of,
            issue_count=len(report.issues),
            review_count=len(report.review_items),
            applied_fix_count=len(applied),
        )
        applied.append(
            WikiSafeFix(
                action="append_log",
                path="log.md",
                description="Append lint/consolidation activity with issue, review, and fix counts.",
                applied=True,
            )
        )
    applied_keys = {(fix.action, fix.path, fix.description) for fix in applied}
    safe_fixes = tuple(
        replace(fix, applied=True)
        if (fix.action, fix.path, fix.description) in applied_keys
        else fix
        for fix in report.safe_fixes
    )
    if log_needed and not any(fix.action == "append_log" and fix.applied for fix in safe_fixes):
        safe_fixes = safe_fixes + (applied[-1],)
    return replace(report, apply=True, safe_fixes=safe_fixes)


def _load_wiki_page_records(root: Path) -> Tuple[WikiPageRecord, ...]:
    wiki_root = root / "wiki"
    if not wiki_root.exists() or not wiki_root.is_dir():
        return ()
    records: List[WikiPageRecord] = []
    for path in sorted(wiki_root.glob("*/*.md")):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        frontmatter, body = _split_frontmatter(content)
        metadata = _parse_memory_frontmatter(frontmatter) if frontmatter is not None else {}
        try:
            relative_path = path.resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        records.append(
            WikiPageRecord(
                path=path,
                relative_path=relative_path,
                frontmatter=frontmatter,
                metadata=metadata,
                body_text=body,
                page=_load_user_memory_page(path, root),
            )
        )
    return tuple(records)


def _index_relative_paths(root: Path) -> Tuple[str, ...]:
    paths = []
    for path in _paths_from_index(root / "index.md", root):
        try:
            paths.append(path.resolve().relative_to(root.resolve()).as_posix())
        except ValueError:
            continue
    return tuple(paths)


def _inbound_wiki_references(
    root: Path,
    records: Sequence[WikiPageRecord],
) -> Mapping[str, Set[str]]:
    inbound: Dict[str, Set[str]] = {}
    for indexed_path in _index_relative_paths(root):
        inbound.setdefault(indexed_path, set()).add("index.md")
    for record in records:
        for target in _record_wiki_references(record):
            inbound.setdefault(target, set()).add(record.relative_path)
    return inbound


def _record_wiki_references(record: WikiPageRecord) -> Tuple[str, ...]:
    refs: List[str] = []
    for key in WIKI_RELATIONSHIP_LIST_FIELDS:
        refs.extend(_metadata_string_tuple(record.metadata.get(key)))
    refs.extend(re.findall(r"\]\((wiki/[^)]+\.md)\)", record.body_text))
    return tuple(_normalize_wiki_ref(ref) for ref in refs if _normalize_wiki_ref(ref))


def _metadata_lint_issues(record: WikiPageRecord) -> Tuple[WikiLintIssue, ...]:
    issues: List[WikiLintIssue] = []
    if record.frontmatter is None:
        return (
            WikiLintIssue(
                category="metadata",
                severity="error",
                path=record.relative_path,
                message="Page has no YAML frontmatter.",
            ),
        )
    missing = []
    for field in REQUIRED_WIKI_FRONTMATTER_FIELDS:
        value = record.metadata.get(field)
        if field == "source_refs":
            if not value and record.metadata.get("status") != "deleted":
                missing.append(field)
        elif value is None:
            missing.append(field)
    if missing:
        issues.append(
            WikiLintIssue(
                category="metadata",
                severity="error",
                path=record.relative_path,
                message="Missing required metadata: {}".format(", ".join(missing)),
                details=tuple(missing),
            )
        )
    issues.extend(_metadata_type_issues(record))
    return tuple(issues)


def _metadata_type_issues(record: WikiPageRecord) -> Tuple[WikiLintIssue, ...]:
    metadata = record.metadata
    checks = (
        ("page_type", {item.value for item in PageType}),
        ("status", WIKI_STATUS_VALUES),
        ("memory_state", WIKI_MEMORY_STATE_VALUES),
        ("confidence_level", WIKI_CONFIDENCE_LEVELS),
        ("sensitivity", WIKI_SENSITIVITY_VALUES),
        ("prompt_visibility", WIKI_PROMPT_VISIBILITY_VALUES),
        ("review_status", WIKI_REVIEW_STATUS_VALUES),
    )
    issues: List[WikiLintIssue] = []
    for field, allowed in checks:
        value = metadata.get(field)
        if value is not None and value not in allowed:
            issues.append(
                WikiLintIssue(
                    category="metadata",
                    severity="error",
                    path=record.relative_path,
                    message="Invalid {} metadata value `{}`.".format(field, value),
                    details=("Allowed: {}".format(", ".join(sorted(allowed))),),
                )
            )
    score = metadata.get("confidence_score")
    if score is not None:
        numeric_score = _optional_float_text(score)
        if numeric_score is None or numeric_score < 0.0 or numeric_score > 1.0:
            issues.append(
                WikiLintIssue(
                    category="metadata",
                    severity="error",
                    path=record.relative_path,
                    message="confidence.score must be a number between 0.0 and 1.0.",
                )
            )
    for field in ("created_at", "updated_at", "last_observed_at"):
        if metadata.get(field) and not _is_valid_datetime_or_null(str(metadata[field]), allow_null=False):
            issues.append(
                WikiLintIssue(
                    category="metadata",
                    severity="error",
                    path=record.relative_path,
                    message="{} must be an ISO-8601 timestamp.".format(field),
                )
            )
    if metadata.get("last_confirmed_at") and not _is_valid_datetime_or_null(
        str(metadata["last_confirmed_at"]),
        allow_null=True,
    ):
        issues.append(
            WikiLintIssue(
                category="metadata",
                severity="error",
                path=record.relative_path,
                message="last_confirmed_at must be an ISO-8601 timestamp or null.",
            )
        )
    stale_after = metadata.get("stale_after")
    if stale_after and _parse_duration_days(str(stale_after)) is None:
        issues.append(
            WikiLintIssue(
                category="metadata",
                severity="error",
                path=record.relative_path,
                message="stale_after must be an ISO-8601 day duration such as P90D.",
            )
        )
    return tuple(issues)


def _source_ref_lint_issues(
    record: WikiPageRecord,
    root: Path,
    manifest_sources: Mapping[str, Mapping[str, object]],
) -> Tuple[WikiLintIssue, ...]:
    issues: List[WikiLintIssue] = []
    for ref in _metadata_source_refs(record.metadata):
        if ref.source_id in manifest_sources:
            continue
        if ref.path and (root / ref.path).exists():
            continue
        issues.append(
            WikiLintIssue(
                category="provenance",
                severity="warning",
                path=record.relative_path,
                message="source_ref `{}` does not resolve to raw/manifest.jsonl or a tombstone file.".format(
                    ref.source_id
                ),
                details=(ref.path or "",),
            )
        )
    return tuple(issues)


def _metadata_source_refs(metadata: Mapping[str, object]) -> Tuple[UserMemorySourceRef, ...]:
    refs = metadata.get("source_refs")
    if not isinstance(refs, tuple):
        return ()
    return tuple(ref for ref in refs if isinstance(ref, UserMemorySourceRef))


def _manifest_sources(root: Path) -> Mapping[str, Mapping[str, object]]:
    path = root / "raw" / "manifest.jsonl"
    if not path.exists():
        return {}
    sources: Dict[str, Mapping[str, object]] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return sources
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping) and isinstance(payload.get("source_id"), str):
            sources[str(payload["source_id"])] = payload
    return sources


def _is_prompt_eligible_secret(
    record: WikiPageRecord,
    manifest_sources: Mapping[str, Mapping[str, object]],
) -> bool:
    prompt_visibility = str(record.metadata.get("prompt_visibility") or "")
    if prompt_visibility == "never":
        return False
    for ref in _metadata_source_refs(record.metadata):
        source = manifest_sources.get(ref.source_id)
        if source is not None and source.get("sensitivity") == "secret":
            return True
    return False


def _is_stale_record(record: WikiPageRecord, as_of: datetime) -> bool:
    if record.metadata.get("status") != "active":
        return False
    stale_after = record.metadata.get("stale_after")
    last_observed = record.metadata.get("last_observed_at") or record.metadata.get("updated_at")
    if not isinstance(stale_after, str) or not isinstance(last_observed, str):
        return False
    duration_days = _parse_duration_days(stale_after)
    if duration_days is None:
        return False
    try:
        observed_at = parse_datetime(last_observed)
    except UserMemoryIngestError:
        return False
    return observed_at + timedelta(days=duration_days) < as_of


def _parse_duration_days(value: str) -> Optional[int]:
    match = re.fullmatch(r"P(?P<days>\d+)D", value.strip())
    if not match:
        return None
    return int(match.group("days"))


def _is_unresolved_contradiction(record: WikiPageRecord, root: Path) -> bool:
    if record.metadata.get("status") == "contested" or record.metadata.get("review_status") == "disputed":
        return True
    if _metadata_string_tuple(record.metadata.get("contradictions")):
        return True
    review_path = root / "review" / "contradictions.md"
    if not review_path.exists():
        return False
    try:
        return record.relative_path in review_path.read_text(encoding="utf-8")
    except OSError:
        return False


def _is_orphan_record(
    record: WikiPageRecord,
    index_paths: Set[str],
    inbound_refs: Mapping[str, Set[str]],
) -> bool:
    if record.page is None:
        return False
    if record.page.status not in {"active", "stale"}:
        return False
    if record.relative_path in index_paths:
        return False
    inbound = inbound_refs.get(record.relative_path, set())
    return not inbound


def _duplicate_candidates(records: Sequence[WikiPageRecord]) -> Tuple[WikiDuplicateCandidate, ...]:
    candidates: List[WikiDuplicateCandidate] = []
    active = [record for record in records if record.page is not None and record.page.status != "deleted"]
    for left_index, left in enumerate(active):
        for right in active[left_index + 1 :]:
            if left.page is None or right.page is None:
                continue
            if left.page.page_type != right.page.page_type:
                continue
            reason = ""
            confidence = 0.0
            if _normalize_claim(left.page.title) == _normalize_claim(right.page.title):
                reason = "same normalized title"
                confidence = 0.95
            else:
                similarity = _page_similarity(left.page, right.page)
                if similarity >= 0.62:
                    reason = "high title/body token overlap"
                    confidence = min(0.90, similarity)
            if reason:
                candidates.append(
                    WikiDuplicateCandidate(
                        paths=(left.relative_path, right.relative_path),
                        reason=reason,
                        confidence=confidence,
                    )
                )
    return tuple(candidates)


def _page_similarity(left: UserMemoryPage, right: UserMemoryPage) -> float:
    left_tokens = _tokenize_for_retrieval("{} {}".format(left.title, left.summary))
    right_tokens = _tokenize_for_retrieval("{} {}".format(right.title, right.summary))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / float(len(left_tokens | right_tokens))


def _relationship_type_suggestions(
    records_by_path: Mapping[str, WikiPageRecord],
) -> Tuple[WikiRelationshipSuggestion, ...]:
    suggestions: List[WikiRelationshipSuggestion] = []
    for source_path, source in sorted(records_by_path.items()):
        for target_path in _metadata_string_tuple(source.metadata.get("related")):
            normalized_target = _normalize_wiki_ref(target_path)
            target = records_by_path.get(normalized_target)
            if target is None:
                continue
            relationship, reason = _suggest_relationship_type(source, target)
            suggestions.append(
                WikiRelationshipSuggestion(
                    source_path=source_path,
                    target_path=normalized_target,
                    suggested_type=relationship,
                    reason=reason,
                )
            )
    return tuple(suggestions)


def _suggest_relationship_type(
    source: WikiPageRecord,
    target: WikiPageRecord,
) -> Tuple[RelationshipType, str]:
    source_type = source.page.page_type if source.page is not None else None
    target_type = target.page.page_type if target.page is not None else None
    combined = "{} {}".format(source.body_text, target.body_text).lower()
    if source_type == PageType.CORRECTION or target_type == PageType.CORRECTION:
        return RelationshipType.CONTRADICTS, "correction pages preserve contradictions/refinements explicitly"
    if source_type == PageType.OBSERVATION and target_type in {PageType.PREFERENCE, PageType.VALUE}:
        return RelationshipType.EXAMPLE_OF, "observations are evidence examples for stronger synthesized pages"
    if source_type in {PageType.PREFERENCE, PageType.VALUE} and target_type == PageType.OBSERVATION:
        return RelationshipType.CONTAINS, "higher-level memory contains lower-level observations as evidence"
    if source_type == PageType.OPEN_QUESTION or target_type == PageType.OPEN_QUESTION:
        return RelationshipType.DEPENDS_ON, "open questions block confident use until resolved"
    if "instead" in combined or "not " in combined or "rather than" in combined:
        return RelationshipType.CONTRADICTS, "text contains corrective or negative contrast language"
    if source.page is not None and target.page is not None and _page_similarity(source.page, target.page) >= 0.45:
        return RelationshipType.SIMILAR_TO, "linked pages have overlapping titles or summaries"
    if source_type == PageType.CONCEPT or target_type == PageType.CONCEPT:
        return RelationshipType.REFINES, "concept links usually refine the meaning of related memory"
    return RelationshipType.REFINES, "generic `related` link should be reviewed for typed relationship semantics"


def _concept_level_review_items(records: Sequence[WikiPageRecord]) -> Tuple[WikiReviewItem, ...]:
    items: List[WikiReviewItem] = []
    for record in records:
        if record.page is None or record.page.status == "deleted":
            continue
        text = "{} {}".format(record.page.title, record.body_text).lower()
        suggested: Optional[str] = None
        reason: Optional[str] = None
        if record.page.page_type == PageType.PREFERENCE and re.search(
            r"\b(value|principle|identity|agency|long[- ]term|durable)\b",
            text,
        ):
            suggested = "value"
            reason = "preference page uses life-scale or user-defining language"
        elif record.page.page_type == PageType.VALUE and re.search(
            r"\b(status|format|tool|command|keyboard|theme|update|temporary|this task)\b",
            text,
        ):
            suggested = "preference"
            reason = "value page appears to describe tactical operating style"
        elif record.page.page_type in {PageType.VALUE, PageType.PREFERENCE} and re.search(
            r"\b(one[- ]off|one time|this task|temporary)\b",
            text,
        ):
            suggested = "observation"
            reason = "durable page appears to describe a one-off observation"
        elif record.page.page_type == PageType.OBSERVATION and len(record.page.source_refs) >= 2:
            suggested = "preference or value"
            reason = "observation has repeated evidence and may be ready for synthesis"
        if suggested is None or reason is None:
            continue
        items.append(
            WikiReviewItem(
                category="concept-level",
                path=record.relative_path,
                summary="Review concept level; suggested type: {}.".format(suggested),
                context=(reason,),
                alternatives=(
                    "Keep current page type and add scope text explaining why.",
                    "Move/split into {} while preserving provenance and backlinks.".format(suggested),
                ),
            )
        )
    return tuple(items)


def _missing_backlink_fixes(
    records_by_path: Mapping[str, WikiPageRecord],
) -> Tuple[WikiSafeFix, ...]:
    fixes: List[WikiSafeFix] = []
    for source_path, source in sorted(records_by_path.items()):
        for field in WIKI_RELATIONSHIP_LIST_FIELDS:
            for target_path in _metadata_string_tuple(source.metadata.get(field)):
                normalized_target = _normalize_wiki_ref(target_path)
                target = records_by_path.get(normalized_target)
                if target is None:
                    continue
                target_refs = set()
                for target_field in WIKI_RELATIONSHIP_LIST_FIELDS:
                    target_refs.update(
                        _normalize_wiki_ref(value)
                        for value in _metadata_string_tuple(target.metadata.get(target_field))
                    )
                if source_path in target_refs:
                    continue
                backlink_field = _backlink_field_for(source, field)
                fixes.append(
                    WikiSafeFix(
                        action="add_backlink",
                        path=normalized_target,
                        description="Add {} backlink to {} from {}.".format(
                            backlink_field,
                            normalized_target,
                            source_path,
                        ),
                    )
                )
    return tuple(fixes)


def _backlink_field_for(source: WikiPageRecord, field: str) -> str:
    if field == "contradictions":
        return "contradictions"
    if field == "corrections":
        return "corrections"
    if source.page is not None and source.page.page_type == PageType.CORRECTION:
        return "corrections"
    return "related"


def _dedupe_safe_fixes(fixes: Sequence[WikiSafeFix]) -> Tuple[WikiSafeFix, ...]:
    deduped: Dict[Tuple[str, str, str], WikiSafeFix] = {}
    for fix in fixes:
        deduped.setdefault((fix.action, fix.path, fix.description), fix)
    return tuple(deduped[key] for key in sorted(deduped))


def _parse_backlink_fix(fix: WikiSafeFix) -> Tuple[Optional[Path], Optional[str], Optional[str]]:
    match = re.search(r"Add (?P<field>[a-z_]+) backlink to (?P<target>wiki/[^ ]+\.md) from (?P<source>wiki/[^ ]+\.md)", fix.description)
    if not match:
        return None, None, None
    return Path(match.group("target")), match.group("field"), match.group("source")


def _append_frontmatter_list_value(path: Path, key: str, value: str) -> None:
    if not path.exists():
        return
    content = path.read_text(encoding="utf-8")
    updated = _frontmatter_list_value_appended(content, key, value)
    if updated != content:
        path.write_text(updated, encoding="utf-8")


def _frontmatter_list_value_appended(content: str, key: str, value: str) -> str:
    if not content.startswith("---\n"):
        return content
    end = content.find("\n---", 4)
    if end == -1:
        return content
    frontmatter = content[:end]
    rest = content[end:]
    parsed = _parse_memory_frontmatter(frontmatter[4:])
    current_values = _metadata_string_tuple(parsed.get(key))
    if value in current_values:
        return content
    lines = frontmatter.splitlines()
    key_index = None
    for index, line in enumerate(lines):
        if line.startswith("{}:".format(key)):
            key_index = index
            break
    if key_index is None:
        lines.append("{}:".format(key))
        lines.append("  - {}".format(value))
        return "\n".join(lines) + rest
    line = lines[key_index]
    if line.strip() == "{}: []".format(key):
        lines[key_index] = "{}:".format(key)
        lines.insert(key_index + 1, "  - {}".format(value))
        return "\n".join(lines) + rest
    if "[" in line and "]" in line:
        values = list(current_values) + [value]
        lines[key_index] = "{}: [{}]".format(key, ", ".join(values))
        return "\n".join(lines) + rest
    insert_at = key_index + 1
    while insert_at < len(lines) and (not lines[insert_at] or lines[insert_at].startswith(" ")):
        insert_at += 1
    lines.insert(insert_at, "  - {}".format(value))
    return "\n".join(lines) + rest


def _append_lint_log(
    root: Path,
    as_of: datetime,
    issue_count: int,
    review_count: int,
    applied_fix_count: int,
) -> None:
    path = root / "log.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else "# User Memory Log\n"
    entry = (
        "- {}: lint/consolidation pass; issues: {}; review_items: {}; "
        "safe_fixes_applied: {}."
    ).format(_format_dt(as_of), issue_count, review_count, applied_fix_count)
    if entry in existing:
        return
    path.write_text(existing.rstrip() + "\n" + entry + "\n", encoding="utf-8")


def _owner_user_from_records(records: Sequence[WikiPageRecord]) -> Optional[str]:
    for record in records:
        owner_user = record.metadata.get("owner_user")
        if isinstance(owner_user, str) and owner_user:
            return owner_user
    return None


def _review_context(record: WikiPageRecord) -> Tuple[str, ...]:
    if record.page is None:
        return (record.relative_path,)
    return (
        "title: {}".format(record.page.title),
        "page_type: {}".format(record.page.page_type.value),
        "memory_state: {}".format(record.page.memory_state),
        "summary: {}".format(record.page.summary),
    )


def _format_report_section(lines: List[str], heading: str, items: Iterable[str]) -> None:
    lines.append("{}:".format(heading))
    rendered = [item for item in items if item]
    if rendered:
        lines.extend(rendered)
    else:
        lines.append("- none")
    lines.append("")


def _format_review_item(item: WikiReviewItem) -> str:
    lines = ["- {}: {} ({})".format(item.category, item.summary, item.path)]
    if item.context:
        lines.append("  context: {}".format("; ".join(item.context)))
    if item.alternatives:
        lines.append("  alternatives: {}".format(" | ".join(item.alternatives)))
    return "\n".join(lines)


def _metadata_string_tuple(value: object) -> Tuple[str, ...]:
    if isinstance(value, tuple):
        return tuple(item for item in value if isinstance(item, str) and item)
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, str) and item)
    if isinstance(value, str) and value:
        return (value,)
    return ()


def _normalize_wiki_ref(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if text.startswith("./"):
        text = text[2:]
    return text


def _is_valid_datetime_or_null(value: str, allow_null: bool) -> bool:
    if allow_null and value in {"null", ""}:
        return True
    try:
        parse_datetime(value)
    except UserMemoryIngestError:
        return False
    return True


def extract_memory_candidates(
    messages: Sequence[ConversationMessage],
    source_record: SourceRecord,
) -> Tuple[Tuple[MemoryCandidate, ...], int]:
    """Extract candidate memories from normalized messages."""

    candidates: List[MemoryCandidate] = []
    withheld_secret_count = 0
    for message in messages:
        if not _is_user_message(message):
            continue
        for sentence in _sentences(message.text):
            if SECRET_RE.search(sentence):
                withheld_secret_count += 1
                continue
            extracted = _extract_from_sentence(sentence, message, source_record)
            candidates.extend(extracted)
            if _is_correction_sentence(sentence) and extracted:
                candidates.extend(
                    _correction_candidates(sentence, extracted, message, source_record)
                )
            elif _is_correction_sentence(sentence):
                candidates.append(
                    _build_candidate(
                        page_type=PageType.CORRECTION,
                        title=_title_from_phrase(sentence, prefix="Correction"),
                        claim="User corrected memory: {}.".format(_clean_sentence(sentence)),
                        state=MemoryState.CORRECTION,
                        message=message,
                        source_record=source_record,
                        support="correction",
                        tags=("correction",),
                    )
                )
    return _dedupe_candidates(candidates), withheld_secret_count


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value.lower()).strip("-")
    return slug[:80].strip("-") or "untitled"


def parse_datetime(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = "{}+00:00".format(normalized[:-1])
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise UserMemoryIngestError("invalid datetime {!r}: {}".format(value, exc))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_user_memory_page(path: Path, root: Path) -> Optional[UserMemoryPage]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    frontmatter, body = _split_frontmatter(content)
    if frontmatter is None:
        return None
    metadata = _parse_memory_frontmatter(frontmatter)
    page_type = _enum_or_none(PageType, metadata.get("page_type"))
    if page_type is None:
        return None
    relative_path = path.resolve().relative_to(root).as_posix()
    title = metadata.get("title") or _title_from_phrase(path.stem)
    page_id = metadata.get("id") or "mem-{}".format(slugify(relative_path))
    confidence_score = _optional_float_text(metadata.get("confidence_score"))
    summary = _page_prompt_summary(body)
    return UserMemoryPage(
        id=page_id,
        title=title,
        page_type=page_type,
        relative_path=relative_path,
        status=metadata.get("status", "active"),
        memory_state=metadata.get("memory_state", "unknown"),
        confidence_level=metadata.get("confidence_level", "unknown"),
        confidence_score=confidence_score,
        sensitivity=metadata.get("sensitivity", "private"),
        prompt_visibility=metadata.get("prompt_visibility", "task_only"),
        review_status=metadata.get("review_status", "unreviewed"),
        source_refs=tuple(metadata.get("source_refs", ())),
        tags=tuple(metadata.get("tags", ())),
        related=tuple(metadata.get("related", ())),
        contradictions=tuple(metadata.get("contradictions", ())),
        corrections=tuple(metadata.get("corrections", ())),
        summary=summary,
        body_text=body,
    )


def _split_frontmatter(content: str) -> Tuple[Optional[str], str]:
    if not content.startswith("---\n"):
        return None, content
    end = content.find("\n---", 4)
    if end == -1:
        return None, content
    frontmatter = content[4:end]
    body = content[end + 4 :].strip()
    return frontmatter, body


def _parse_memory_frontmatter(frontmatter: str) -> Dict[str, object]:
    metadata: Dict[str, object] = {}
    current_key: Optional[str] = None
    current_source_ref: Optional[Dict[str, str]] = None
    source_refs: List[UserMemorySourceRef] = []
    list_values: Dict[str, List[str]] = {
        "related": [],
        "supersedes": [],
        "superseded_by": [],
        "contradictions": [],
        "corrections": [],
        "tags": [],
    }
    for raw_line in frontmatter.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if not line.startswith(" "):
            current_source_ref = None
            if ":" not in line:
                current_key = None
                continue
            key, value = line.split(":", 1)
            current_key = key.strip()
            value = value.strip()
            if current_key in list_values:
                list_values[current_key].extend(_parse_yaml_scalar_list(value))
            elif current_key == "source_refs":
                metadata[current_key] = source_refs
            elif value:
                metadata[current_key] = _strip_yaml_scalar(value)
            continue
        stripped = line.strip()
        if current_key == "confidence" and ":" in stripped:
            key, value = stripped.split(":", 1)
            metadata["confidence_{}".format(key.strip())] = _strip_yaml_scalar(value.strip())
            continue
        if current_key == "source_refs":
            if stripped.startswith("- "):
                source_ref_data: Dict[str, str] = {}
                first = stripped[2:].strip()
                if ":" in first:
                    key, value = first.split(":", 1)
                    source_ref_data[key.strip()] = _strip_yaml_scalar(value.strip())
                current_source_ref = source_ref_data
                source_refs.append(
                    UserMemorySourceRef(
                        source_id=source_ref_data.get("source_id", "unknown-source"),
                        path=source_ref_data.get("path"),
                        locator=source_ref_data.get("locator"),
                        claim=source_ref_data.get("claim"),
                        support=source_ref_data.get("support"),
                    )
                )
                continue
            if current_source_ref is not None and ":" in stripped:
                key, value = stripped.split(":", 1)
                current_source_ref[key.strip()] = _strip_yaml_scalar(value.strip())
                source_refs[-1] = UserMemorySourceRef(
                    source_id=current_source_ref.get("source_id", "unknown-source"),
                    path=current_source_ref.get("path"),
                    locator=current_source_ref.get("locator"),
                    claim=current_source_ref.get("claim"),
                    support=current_source_ref.get("support"),
                )
                continue
        if current_key in list_values and stripped.startswith("- "):
            list_values[current_key].append(_strip_yaml_scalar(stripped[2:].strip()))
    for key, values in list_values.items():
        metadata[key] = tuple(value for value in values if value)
    metadata["source_refs"] = tuple(source_refs)
    return metadata


def _paths_from_index(index_path: Path, root: Path) -> Tuple[Path, ...]:
    if not index_path.exists():
        return ()
    try:
        index_text = index_path.read_text(encoding="utf-8")
    except OSError:
        return ()
    paths = []
    for match in re.finditer(r"\[[^\]]+\]\((wiki/[^)]+\.md)\)", index_text):
        candidate = (root / match.group(1)).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            continue
        paths.append(candidate)
    return tuple(paths)


def _parse_yaml_scalar_list(value: str) -> Tuple[str, ...]:
    if not value or value == "[]":
        return ()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return ()
        return tuple(_strip_yaml_scalar(part.strip()) for part in inner.split(",") if part.strip())
    return (_strip_yaml_scalar(value),)


def _strip_yaml_scalar(value: str) -> str:
    text = value.strip()
    if text in {"null", "~"}:
        return ""
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def _page_prompt_summary(body: str) -> str:
    lines: List[str] = []
    in_first_section = False
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            if lines:
                break
            continue
        if line.startswith("# "):
            in_first_section = True
            continue
        if line.startswith("## "):
            break
        if line.startswith("- "):
            continue
        if not in_first_section and line.startswith("#"):
            continue
        lines.append(line)
    if not lines:
        return _short_claim(_first_claim_summary(body))
    return _short_claim(" ".join(lines), limit=220)


def _enum_or_none(enum_type: Any, value: object) -> Optional[Any]:
    if not isinstance(value, str):
        return None
    try:
        return enum_type(value)
    except ValueError:
        return None


def _optional_float_text(value: object) -> Optional[float]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _tokenize_for_retrieval(text: str) -> Set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", text.lower())
        if token not in STOPWORDS
    }


def _memory_relevance_score(
    page: UserMemoryPage,
    query_tokens: Set[str],
    task_type: UserMemoryTaskType,
) -> float:
    if not query_tokens:
        return 0.0
    title_tokens = _tokenize_for_retrieval(page.title)
    tag_tokens = _tokenize_for_retrieval(" ".join(page.tags))
    path_tokens = _tokenize_for_retrieval(page.relative_path.replace("/", " "))
    body_tokens = _tokenize_for_retrieval("{} {}".format(page.summary, page.body_text))
    score = (
        3.0 * len(query_tokens & title_tokens)
        + 2.0 * len(query_tokens & tag_tokens)
        + 1.5 * len(query_tokens & path_tokens)
        + 1.0 * len(query_tokens & body_tokens)
    )
    if score == 0:
        return 0.0
    score += _task_type_boost(page, task_type)
    if page.memory_state == MemoryState.CORRECTION.value:
        score += 1.5
    if page.prompt_visibility == "confirm_first":
        score += 0.25
    return score


def _task_type_boost(page: UserMemoryPage, task_type: UserMemoryTaskType) -> float:
    boosts: Mapping[UserMemoryTaskType, Mapping[PageType, float]] = {
        UserMemoryTaskType.PROJECT_EXECUTION: {
            PageType.PROJECT: 1.5,
            PageType.DECISION: 1.25,
            PageType.PREFERENCE: 1.0,
            PageType.VALUE: 0.75,
            PageType.CONCEPT: 0.5,
            PageType.CORRECTION: 1.25,
            PageType.OPEN_QUESTION: 0.5,
        },
        UserMemoryTaskType.USER_REPRESENTATION: {
            PageType.VALUE: 1.5,
            PageType.PREFERENCE: 1.5,
            PageType.CORRECTION: 1.25,
            PageType.OPEN_QUESTION: 1.0,
            PageType.CONCEPT: 0.75,
        },
        UserMemoryTaskType.SOCIAL_COORDINATION: {
            PageType.PERSON: 1.5,
            PageType.ORG: 1.5,
            PageType.PREFERENCE: 1.0,
            PageType.VALUE: 0.75,
            PageType.CORRECTION: 1.25,
            PageType.OPEN_QUESTION: 1.0,
        },
        UserMemoryTaskType.CORRECTION_HANDLING: {
            PageType.CORRECTION: 2.0,
            PageType.PREFERENCE: 1.0,
            PageType.VALUE: 1.0,
            PageType.PROJECT: 0.75,
            PageType.OPEN_QUESTION: 0.75,
        },
        UserMemoryTaskType.MEMORY_MAINTENANCE: {
            PageType.CONCEPT: 1.5,
            PageType.PROJECT: 1.25,
            PageType.DECISION: 1.0,
            PageType.CORRECTION: 1.25,
            PageType.OPEN_QUESTION: 1.0,
            PageType.PREFERENCE: 0.75,
            PageType.VALUE: 0.75,
        },
        UserMemoryTaskType.GENERAL: {
            PageType.PREFERENCE: 0.5,
            PageType.VALUE: 0.5,
            PageType.CORRECTION: 0.5,
        },
    }
    return boosts.get(task_type, {}).get(page.page_type, 0.0)


def _page_is_deleted_or_unusable(page: UserMemoryPage) -> bool:
    return (
        page.status in {"deleted", "archived"}
        or page.review_status == "deletion_pending"
        or page.prompt_visibility == "never"
    )


def _privacy_gate(page: UserMemoryPage, options: UserMemoryRetrievalOptions) -> Optional[str]:
    if page.sensitivity == "secret":
        return "sensitive"
    if page.sensitivity == "restricted" and not options.allow_restricted:
        return "sensitive"
    if page.sensitivity == "private" and not options.allow_private:
        return "private"
    return None


def _bounded_selection(
    scored: Sequence[Tuple[float, UserMemoryPage]],
    max_pages: int,
) -> Tuple[UserMemoryPage, ...]:
    bounded = max(0, max_pages)
    if bounded == 0:
        return ()
    ranked = sorted(
        scored,
        key=lambda item: (
            -item[0],
            _memory_state_rank(item[1]),
            item[1].relative_path,
        ),
    )
    return tuple(page for _, page in ranked[:bounded])


def _memory_state_rank(page: UserMemoryPage) -> int:
    order = {
        MemoryState.CORRECTION.value: 0,
        MemoryState.CONFIRMED.value: 1,
        MemoryState.OBSERVED_PATTERN.value: 2,
        MemoryState.INFERRED.value: 3,
        MemoryState.OPEN_QUESTION.value: 4,
    }
    return order.get(page.memory_state, 5)


def _include_related_guardrails(
    selected: Sequence[UserMemoryPage],
    pages: Sequence[UserMemoryPage],
    options: UserMemoryRetrievalOptions,
    max_pages: int,
) -> Tuple[UserMemoryPage, ...]:
    selected_pages = list(selected)
    if len(selected_pages) >= max_pages:
        return tuple(selected_pages[:max_pages])
    selected_paths = {page.relative_path for page in selected_pages}
    guardrails = []
    for page in pages:
        if page.relative_path in selected_paths:
            continue
        if page.page_type not in {PageType.CORRECTION, PageType.OPEN_QUESTION}:
            continue
        if _page_is_deleted_or_unusable(page) or _privacy_gate(page, options) is not None:
            continue
        related_paths = set(page.related + page.corrections + page.contradictions)
        if related_paths & selected_paths:
            guardrails.append(page)
    for page in sorted(guardrails, key=lambda item: (_memory_state_rank(item), item.relative_path)):
        if len(selected_pages) >= max_pages:
            break
        selected_pages.append(page)
    return tuple(selected_pages)


def _page_is_caveat(page: UserMemoryPage) -> bool:
    return (
        page.page_type == PageType.OPEN_QUESTION
        or page.page_type == PageType.CORRECTION
        or page.memory_state == MemoryState.OPEN_QUESTION.value
        or page.memory_state == MemoryState.CORRECTION.value
        or page.prompt_visibility == "confirm_first"
        or page.status == "contested"
        or bool(page.contradictions)
    )


def _format_memory_fact(page: UserMemoryPage) -> str:
    state_label = page.memory_state.replace("_", " ").capitalize()
    return "{}: {} - {} [{}]".format(
        state_label,
        page.title,
        page.summary,
        page.provenance_label,
    )


def _format_memory_caveat(page: UserMemoryPage) -> str:
    if page.page_type == PageType.OPEN_QUESTION or page.memory_state == MemoryState.OPEN_QUESTION.value:
        prefix = "Open question"
    elif page.page_type == PageType.CORRECTION or page.memory_state == MemoryState.CORRECTION.value:
        prefix = "Correction"
    elif page.status == "contested" or page.contradictions:
        prefix = "Contradiction"
    elif page.prompt_visibility == "confirm_first":
        prefix = "Needs confirmation"
    else:
        prefix = "Caveat"
    return "{}: {} - {} [{}]".format(
        prefix,
        page.title,
        page.summary,
        page.provenance_label,
    )


def _task_high_stakes_signal(text: str) -> bool:
    return bool(HIGH_STAKES_TASK_RE.search(text))


def _dedupe_strings(values: Sequence[str]) -> Tuple[str, ...]:
    seen = set()
    deduped = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return tuple(deduped)


def _extract_from_sentence(
    sentence: str,
    message: ConversationMessage,
    source_record: SourceRecord,
) -> Tuple[MemoryCandidate, ...]:
    candidates: List[MemoryCandidate] = []
    clean = _clean_sentence(sentence)

    concept = re.search(
        r"\bconcept\s*[:\-]\s*(?P<title>[^:.\-]+?)\s+(?:is|means)\s+(?P<body>[^.?!]+)",
        clean,
        re.IGNORECASE,
    )
    if concept:
        title = _title_from_phrase(concept.group("title"))
        candidates.append(
            _build_candidate(
                page_type=PageType.CONCEPT,
                title=title,
                claim="Concept {} means {}.".format(
                    title,
                    _trim_terminal_punctuation(concept.group("body")),
                ),
                state=_state_for_sentence(clean, MemoryState.CONFIRMED),
                message=message,
                source_record=source_record,
                tags=("concept",),
            )
        )

    for pattern, page_type, claim_prefix, tag in (
        (
            r"\b(?:i value|i care about)\s+(?P<claim>[^.?!]+)",
            PageType.VALUE,
            "User values",
            "value",
        ),
        (
            r"\bit is important to me that\s+(?P<claim>[^.?!]+)",
            PageType.VALUE,
            "User says it is important that",
            "value",
        ),
        (
            r"\bi prefer\s+(?P<claim>[^.?!]+)",
            PageType.PREFERENCE,
            "User prefers",
            "preference",
        ),
        (
            r"\bi like\s+(?P<claim>[^.?!]+)",
            PageType.PREFERENCE,
            "User likes",
            "preference",
        ),
        (
            r"\bi want\s+(?P<claim>[^.?!]+)",
            PageType.PREFERENCE,
            "User wants",
            "preference",
        ),
        (
            r"\bplease\s+(?P<claim>(?:use|keep|make|avoid|do not|don't)\s+[^.?!]+)",
            PageType.PREFERENCE,
            "User requested",
            "preference",
        ),
        (
            r"\bi(?: am|'m) working on\s+(?P<claim>[^.?!]+)",
            PageType.PROJECT,
            "User is working on",
            "project",
        ),
        (
            r"\bwe(?: are|'re) building\s+(?P<claim>[^.?!]+)",
            PageType.PROJECT,
            "User's project is building",
            "project",
        ),
        (
            r"\bproject\s*[:\-]\s*(?P<claim>[^.?!]+)",
            PageType.PROJECT,
            "Project context",
            "project",
        ),
        (
            r"\b(?:we|i) decided to\s+(?P<claim>[^.?!]+)",
            PageType.DECISION,
            "Decision",
            "decision",
        ),
        (
            r"\bdecision\s*[:\-]\s*(?P<claim>[^.?!]+)",
            PageType.DECISION,
            "Decision",
            "decision",
        ),
    ):
        for match in re.finditer(pattern, clean, flags=re.IGNORECASE):
            phrase = _positive_phrase(match.group("claim"))
            state = _state_for_sentence(clean, MemoryState.CONFIRMED)
            support = "correction" if _is_correction_sentence(clean) else "explicit"
            candidates.append(
                _build_candidate(
                    page_type=page_type,
                    title=_title_from_phrase(phrase),
                    claim="{} {}.".format(claim_prefix, _trim_terminal_punctuation(phrase)),
                    state=state,
                    message=message,
                    source_record=source_record,
                    support=support,
                    tags=(tag,),
                    from_correction=_is_correction_sentence(clean),
                )
            )

    for pattern, page_type, tag in (
        (
            r"\bperson\s*[:\-]\s*(?P<title>[^:.\-]+?)\s*[:\-]\s*(?P<claim>[^.?!]+)",
            PageType.PERSON,
            "person",
        ),
        (
            r"\borg(?:anization)?\s*[:\-]\s*(?P<title>[^:.\-]+?)\s*[:\-]\s*(?P<claim>[^.?!]+)",
            PageType.ORG,
            "org",
        ),
    ):
        match = re.search(pattern, clean, flags=re.IGNORECASE)
        if match:
            title = _title_from_phrase(match.group("title"))
            candidates.append(
                _build_candidate(
                    page_type=page_type,
                    title=title,
                    claim="{}: {}.".format(title, _trim_terminal_punctuation(match.group("claim"))),
                    state=_state_for_sentence(clean, MemoryState.CONFIRMED),
                    message=message,
                    source_record=source_record,
                    tags=(tag,),
                )
            )

    for match in re.finditer(
        r"\bi\s+(?:might|may|probably)\s+(?:prefer|want|need|care about)\s+(?P<claim>[^.?!]+)",
        clean,
        flags=re.IGNORECASE,
    ):
        phrase = _positive_phrase(match.group("claim"))
        candidates.append(
            _build_candidate(
                page_type=PageType.PREFERENCE,
                title=_title_from_phrase(phrase),
                claim="User may prefer {}.".format(_trim_terminal_punctuation(phrase)),
                state=MemoryState.INFERRED,
                message=message,
                source_record=source_record,
                support="indirect",
                tags=("preference", "inferred"),
            )
        )

    for pattern in (
        r"\bi (?:usually|often|tend to)\s+(?P<claim>[^.?!]+)",
        r"\bi keep\s+(?P<claim>[^.?!]+)",
    ):
        for match in re.finditer(pattern, clean, flags=re.IGNORECASE):
            phrase = _positive_phrase(match.group("claim"))
            candidates.append(
                _build_candidate(
                    page_type=PageType.OBSERVATION,
                    title=_title_from_phrase(phrase),
                    claim="Observed pattern: user {}.".format(
                        _trim_terminal_punctuation(phrase)
                    ),
                    state=MemoryState.OBSERVED_PATTERN,
                    message=message,
                    source_record=source_record,
                    support="indirect",
                    tags=("observed-pattern",),
                )
            )

    open_question = _open_question_claim(clean)
    if open_question is not None:
        candidates.append(
            _build_candidate(
                page_type=PageType.OPEN_QUESTION,
                title=_title_from_phrase(open_question, prefix="Question"),
                claim="Open question: {}?".format(
                    _trim_terminal_punctuation(open_question).rstrip("?")
                ),
                state=MemoryState.OPEN_QUESTION,
                message=message,
                source_record=source_record,
                support="explicit",
                tags=("open-question",),
            )
        )

    return tuple(candidates)


def _build_candidate(
    page_type: PageType,
    title: str,
    claim: str,
    state: MemoryState,
    message: ConversationMessage,
    source_record: SourceRecord,
    support: str = "explicit",
    tags: Tuple[str, ...] = (),
    related: Tuple[str, ...] = (),
    correction_target: Optional[Tuple[PageType, str]] = None,
    from_correction: bool = False,
) -> MemoryCandidate:
    confidence_level, confidence_score, review_status = _confidence_for_state(state)
    sensitivity = _sensitivity_for_page_type(page_type)
    prompt_visibility = _prompt_visibility_for(page_type, sensitivity, state)
    source_ref = CandidateSourceRef(
        source_id=source_record.source_id,
        path=source_record.path,
        locator=message.locator,
        claim=_short_claim(claim),
        support=support,
        excerpt_hash="sha256:{}".format(_sha256(_clean_sentence(message.text))[:16]),
    )
    return MemoryCandidate(
        page_type=page_type,
        title=title,
        claim=_trim_terminal_punctuation(claim) + ".",
        memory_state=state,
        confidence_level=confidence_level,
        confidence_score=confidence_score,
        sensitivity=sensitivity,
        prompt_visibility=prompt_visibility,
        review_status=review_status,
        source_refs=(source_ref,),
        tags=tags,
        related=related,
        correction_target=correction_target,
        from_correction=from_correction,
    )


def _correction_candidates(
    sentence: str,
    extracted: Sequence[MemoryCandidate],
    message: ConversationMessage,
    source_record: SourceRecord,
) -> Tuple[MemoryCandidate, ...]:
    candidates: List[MemoryCandidate] = []
    for target in extracted:
        if target.page_type in {PageType.CORRECTION, PageType.OPEN_QUESTION}:
            continue
        related = ("wiki/{}/{}.md".format(PAGE_DIRECTORIES[target.page_type], target.slug),)
        candidates.append(
            _build_candidate(
                page_type=PageType.CORRECTION,
                title="Correction {}".format(target.title),
                claim="User corrected memory about {}: {}.".format(
                    target.title,
                    _clean_sentence(sentence),
                ),
                state=MemoryState.CORRECTION,
                message=message,
                source_record=source_record,
                support="correction",
                tags=("correction", target.page_type.value),
                related=related,
                correction_target=(target.page_type, target.slug),
                from_correction=True,
            )
        )
    return tuple(candidates)


def _dedupe_candidates(candidates: Sequence[MemoryCandidate]) -> Tuple[MemoryCandidate, ...]:
    by_key: Dict[Tuple[PageType, str], MemoryCandidate] = {}
    for candidate in candidates:
        key = (candidate.page_type, candidate.slug)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = candidate
            continue
        refs = _unique_source_refs(existing.source_refs + candidate.source_refs)
        state = _merge_state(existing.memory_state, candidate.memory_state, len(refs))
        confidence_level, confidence_score, review_status = _confidence_for_state(state)
        by_key[key] = replace(
            existing,
            claim=existing.claim if _normalize_claim(existing.claim) == _normalize_claim(candidate.claim) else candidate.claim,
            memory_state=state,
            confidence_level=confidence_level,
            confidence_score=confidence_score,
            review_status=review_status,
            source_refs=refs,
            tags=tuple(sorted(set(existing.tags + candidate.tags))),
            related=tuple(sorted(set(existing.related + candidate.related))),
            from_correction=existing.from_correction or candidate.from_correction,
        )
    return tuple(by_key[key] for key in sorted(by_key, key=lambda item: (item[0].value, item[1])))


def _merge_state(
    first: MemoryState,
    second: MemoryState,
    source_ref_count: int,
) -> MemoryState:
    if MemoryState.CORRECTION in {first, second}:
        return MemoryState.CORRECTION
    if MemoryState.OPEN_QUESTION in {first, second}:
        return MemoryState.OPEN_QUESTION
    if MemoryState.OBSERVED_PATTERN in {first, second}:
        return MemoryState.OBSERVED_PATTERN
    if source_ref_count >= 2 and first == second == MemoryState.INFERRED:
        return MemoryState.OBSERVED_PATTERN
    if MemoryState.CONFIRMED in {first, second}:
        return MemoryState.CONFIRMED
    return first


def _unique_source_refs(refs: Sequence[CandidateSourceRef]) -> Tuple[CandidateSourceRef, ...]:
    seen = set()
    unique: List[CandidateSourceRef] = []
    for ref in refs:
        key = (ref.source_id, ref.locator, ref.claim)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ref)
    return tuple(unique)


def _ensure_memory_root(plan: IngestPlan) -> None:
    for directory in PAGE_DIRECTORIES.values():
        (plan.root / "wiki" / directory).mkdir(parents=True, exist_ok=True)
    (plan.root / "raw" / "redactions").mkdir(parents=True, exist_ok=True)
    (plan.root / "review").mkdir(parents=True, exist_ok=True)
    readme_path = plan.root / "README.md"
    if not readme_path.exists():
        readme_path.write_text(
            "# User Memory\n\n"
            "This corpus stores synthesized user-memory wiki pages, source manifests, "
            "and review queues for one configured user.\n",
            encoding="utf-8",
        )
    schema_path = plan.root / "schema.md"
    if not schema_path.exists():
        schema_path.write_text(
            "# User Memory Schema\n\n"
            "This corpus follows the Herald user-memory wiki schema from "
            "`docs/herald-user-memory-wiki-schema.md` in the Vera repository.\n",
            encoding="utf-8",
        )


def _write_source_record(plan: IngestPlan) -> None:
    if plan.source_record.retention == SourceRetention.STORE:
        source_path = plan.root / plan.source_record.path
        source_path.parent.mkdir(parents=True, exist_ok=True)
        if not source_path.exists():
            source_path.write_text(plan.source_text, encoding="utf-8")
    else:
        redaction_path = plan.root / plan.source_record.path
        redaction_path.parent.mkdir(parents=True, exist_ok=True)
        if not redaction_path.exists():
            redaction_path.write_text(
                json.dumps(
                    {
                        "source_id": plan.source_record.source_id,
                        "sha256": plan.source_record.sha256,
                        "channel": plan.source_record.channel,
                        "message_count": plan.source_record.message_count,
                        "retention": plan.source_record.retention.value,
                        "raw_content": "not retained",
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
    manifest_path = plan.root / "raw" / "manifest.jsonl"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    existing = manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else ""
    if '"source_id": "{}"'.format(plan.source_record.source_id) in existing:
        return
    with manifest_path.open("a", encoding="utf-8") as manifest:
        manifest.write(json.dumps(_source_record_json(plan.source_record), sort_keys=True) + "\n")


def _source_record_json(record: SourceRecord) -> Mapping[str, Any]:
    return {
        "source_id": record.source_id,
        "path": record.path,
        "source_type": record.source_type,
        "channel": record.channel,
        "captured_at": _format_dt(record.captured_at),
        "source_event_at": _format_dt(record.source_event_at) if record.source_event_at else None,
        "sha256": record.sha256,
        "sensitivity": record.sensitivity,
        "consent_scope": record.consent_scope,
        "retention": record.retention.value,
        "redaction_state": record.redaction_state,
        "notes": "raw content not retained" if record.retention == SourceRetention.HASH_ONLY else "",
    }


def _new_page_markdown(plan: IngestPlan, candidate: MemoryCandidate) -> str:
    now = _format_dt(plan.source_record.captured_at)
    last_confirmed = now if candidate.memory_state in {MemoryState.CONFIRMED, MemoryState.CORRECTION} else "null"
    body_lines = [
        "---",
        "id: {}".format(candidate.stable_id),
        "title: {}".format(candidate.title),
        "page_type: {}".format(candidate.page_type.value),
        "owner_user: {}".format(plan.owner_user),
        "status: active",
        "memory_state: {}".format(candidate.memory_state.value),
        "confidence:",
        "  level: {}".format(candidate.confidence_level),
        "  score: {:.2f}".format(candidate.confidence_score),
        "sensitivity: {}".format(candidate.sensitivity),
        "prompt_visibility: {}".format(candidate.prompt_visibility),
        "review_status: {}".format(candidate.review_status),
        "created_at: {}".format(now),
        "updated_at: {}".format(now),
        "last_observed_at: {}".format(now),
        "last_confirmed_at: {}".format(last_confirmed),
        "stale_after: {}".format(_stale_after(candidate.page_type, candidate.memory_state)),
        "source_refs:",
    ]
    body_lines.extend(_source_ref_yaml(candidate.source_refs))
    body_lines.extend(_yaml_list("related", candidate.related))
    body_lines.extend(_yaml_list("supersedes", ()))
    body_lines.extend(_yaml_list("superseded_by", ()))
    body_lines.extend(_yaml_list("contradictions", ()))
    body_lines.extend(_yaml_list("corrections", ()))
    body_lines.extend(_yaml_inline_list("tags", candidate.tags))
    body_lines.extend(["---", "", "# {}".format(candidate.title), "", candidate.claim, ""])
    if candidate.memory_state == MemoryState.INFERRED:
        body_lines.extend(
            [
                "## Why This Is An Inference",
                "",
                "The source wording is tentative or indirect, so this page should be used with uncertainty language.",
                "",
            ]
        )
    if candidate.memory_state == MemoryState.OBSERVED_PATTERN:
        body_lines.extend(
            [
                "## Why This Is An Observed Pattern",
                "",
                "This records behavior-level evidence and must not be promoted into a global value without confirmation.",
                "",
            ]
        )
    if candidate.memory_state == MemoryState.OPEN_QUESTION:
        body_lines.extend(
            [
                "## What Would Answer This",
                "",
                "A future explicit user answer or correction should resolve this question.",
                "",
            ]
        )
    if candidate.memory_state == MemoryState.CORRECTION:
        body_lines.extend(
            [
                "## Corrective Rule",
                "",
                "Prefer this correction over older conflicting memory until review resolves the affected pages.",
                "",
            ]
        )
    body_lines.extend(["## Evidence", ""])
    for ref in candidate.source_refs:
        body_lines.append(
            "- {} [source: {}; locator: {}; support: {}; confidence: {}]".format(
                ref.claim,
                ref.source_id,
                ref.locator,
                ref.support,
                candidate.confidence_level,
            )
        )
    body_lines.extend(["", "## Prompt Rule", "", _prompt_rule(candidate), ""])
    return "\n".join(body_lines)


def _updated_page_markdown(
    plan: IngestPlan,
    existing: str,
    candidate: MemoryCandidate,
    contradiction: bool,
) -> str:
    now = _format_dt(plan.source_record.captured_at)
    updated = _replace_frontmatter_scalar(existing, "updated_at", now)
    updated = _replace_frontmatter_scalar(updated, "last_observed_at", now)
    if candidate.memory_state in {MemoryState.CONFIRMED, MemoryState.CORRECTION}:
        updated = _replace_frontmatter_scalar(updated, "last_confirmed_at", now)
    if contradiction:
        updated = _replace_frontmatter_scalar(updated, "status", "contested")
        updated = _replace_frontmatter_scalar(updated, "review_status", "disputed")
    updated = _append_frontmatter_source_refs(updated, candidate.source_refs)
    heading = "## Correction / Contradiction" if contradiction else "## Ingested Updates"
    section = [
        "",
        heading,
        "",
        "- {} [source: {}; confidence: {}; state: {}]".format(
            candidate.claim,
            candidate.source_refs[0].source_id,
            candidate.confidence_level,
            candidate.memory_state.value,
        ),
    ]
    if contradiction:
        section.append(
            "- Review note: this correction conflicts with older page content and must not be silently overwritten."
        )
    section.append("")
    return updated.rstrip() + "\n" + "\n".join(section)


def _append_frontmatter_source_refs(
    content: str,
    refs: Sequence[CandidateSourceRef],
) -> str:
    if not content.startswith("---\n"):
        return content
    end = content.find("\n---", 4)
    if end == -1:
        return content
    frontmatter = content[: end + 4]
    rest = content[end + 4 :]
    if all(ref.source_id in frontmatter and ref.locator in frontmatter for ref in refs):
        return content
    lines = frontmatter.splitlines()
    insert_at = None
    for index, line in enumerate(lines):
        if line == "source_refs:":
            insert_at = index + 1
            while insert_at < len(lines):
                current = lines[insert_at]
                if current and not current.startswith(" ") and current != "---":
                    break
                insert_at += 1
            break
    if insert_at is None:
        insert_at = len(lines) - 1
        lines.insert(insert_at, "source_refs:")
        insert_at += 1
    for yaml_line in reversed(_source_ref_yaml(refs)):
        lines.insert(insert_at, yaml_line)
    return "\n".join(lines) + rest


def _replace_frontmatter_scalar(content: str, key: str, value: str) -> str:
    if not content.startswith("---\n"):
        return content
    end = content.find("\n---", 4)
    if end == -1:
        return content
    frontmatter = content[:end]
    rest = content[end:]
    pattern = re.compile(r"^{}: .*$".format(re.escape(key)), flags=re.MULTILINE)
    replacement = "{}: {}".format(key, value)
    if pattern.search(frontmatter):
        frontmatter = pattern.sub(replacement, frontmatter)
    else:
        frontmatter = frontmatter + "\n" + replacement
    return frontmatter + rest


def _source_ref_yaml(refs: Sequence[CandidateSourceRef]) -> List[str]:
    lines: List[str] = []
    for ref in refs:
        lines.extend(
            [
                "  - source_id: {}".format(ref.source_id),
                "    path: {}".format(ref.path),
                "    locator: {}".format(ref.locator),
                "    claim: {}".format(_yaml_scalar(ref.claim)),
                "    support: {}".format(ref.support),
                "    excerpt_hash: {}".format(ref.excerpt_hash),
            ]
        )
    return lines


def _yaml_list(key: str, values: Sequence[str]) -> List[str]:
    if not values:
        return ["{}: []".format(key)]
    lines = ["{}:".format(key)]
    lines.extend("  - {}".format(value) for value in values)
    return lines


def _yaml_inline_list(key: str, values: Sequence[str]) -> List[str]:
    if not values:
        return ["{}: []".format(key)]
    return ["{}: [{}]".format(key, ", ".join(values))]


def _yaml_scalar(value: str) -> str:
    if ":" in value or "#" in value or value.startswith("{"):
        return json.dumps(value)
    return value


def _update_contradictions(plan: IngestPlan) -> None:
    if not plan.contradictions:
        return
    path = plan.root / "review" / "contradictions.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Contradictions\n"
    additions: List[str] = []
    for contradiction in plan.contradictions:
        marker = "{} {}".format(plan.source_record.source_id, contradiction.path)
        if marker in existing:
            continue
        additions.extend(
            [
                "",
                "## {} - {}".format(_format_dt(plan.source_record.captured_at), contradiction.title),
                "",
                "- marker: {}".format(marker),
                "- page: {}".format(contradiction.path),
                "- existing summary: {}".format(contradiction.existing_summary),
                "- new correction: {}".format(contradiction.new_summary),
                "- source: {}".format(contradiction.source_id),
                "- proposed resolution: {}".format(contradiction.proposed_resolution),
            ]
        )
    if additions:
        path.write_text(existing.rstrip() + "\n" + "\n".join(additions) + "\n", encoding="utf-8")


def _rebuild_index(root: Path, owner_user: str) -> None:
    lines = [
        "# User Memory Index",
        "",
        "Owner user: {}".format(owner_user),
        "",
        "This index is rebuilt by the user-memory ingest pipeline.",
        "",
    ]
    for page_type in PageType:
        directory = root / "wiki" / PAGE_DIRECTORIES[page_type]
        pages = sorted(directory.glob("*.md")) if directory.exists() else []
        lines.extend(["## {}".format(INDEX_HEADINGS[page_type]), ""])
        entries = []
        for page in pages:
            metadata = _page_metadata(page)
            if metadata.get("status") == "deleted":
                continue
            title = metadata.get("title") or _title_from_phrase(page.stem)
            state = metadata.get("memory_state", "unknown")
            confidence = metadata.get("confidence_level", "unknown")
            relative = page.relative_to(root).as_posix()
            entries.append("- [{}]({}) - {}; confidence: {}".format(title, relative, state, confidence))
        if entries:
            lines.extend(entries)
        else:
            lines.append("- none")
        lines.append("")
    (root / "index.md").write_text("\n".join(lines), encoding="utf-8")


def _page_metadata(path: Path) -> Mapping[str, str]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    metadata: Dict[str, str] = {}
    if content.startswith("---\n"):
        end = content.find("\n---", 4)
        if end != -1:
            frontmatter = content[4:end]
            for line in frontmatter.splitlines():
                if line.startswith("  "):
                    if line.strip().startswith("level:"):
                        metadata["confidence_level"] = line.split(":", 1)[1].strip()
                    continue
                if ":" in line:
                    key, value = line.split(":", 1)
                    metadata[key.strip()] = value.strip().strip('"')
    if "title" not in metadata:
        heading = re.search(r"^#\s+(.+)$", content, flags=re.MULTILINE)
        if heading:
            metadata["title"] = heading.group(1).strip()
    return metadata


def _append_log(plan: IngestPlan, changed_pages: Sequence[str]) -> None:
    path = plan.root / "log.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else "# User Memory Log\n"
    if plan.source_record.source_id in existing:
        return
    touched = ", ".join(changed_pages) if changed_pages else "none"
    contradictions = ", ".join(item.path for item in plan.contradictions) if plan.contradictions else "none"
    entry = (
        "- {}: ingest {} from {} touched {}; candidates: {}; contradictions: {}; "
        "retention: {}; withheld_secret_candidates: {}."
    ).format(
        _format_dt(plan.source_record.captured_at),
        plan.source_record.source_id,
        plan.source_record.channel,
        touched,
        len(plan.candidates),
        contradictions,
        plan.source_record.retention.value,
        plan.withheld_secret_count,
    )
    path.write_text(existing.rstrip() + "\n" + entry + "\n", encoding="utf-8")


def _candidate_already_present(content: str, candidate: MemoryCandidate) -> bool:
    normalized_content = _normalize_claim(content)
    return _normalize_claim(candidate.claim) in normalized_content


def _first_claim_summary(content: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("---") and not stripped.startswith("#"):
            if not stripped.endswith(":") and ":" not in stripped[:20]:
                return _short_claim(stripped)
    return "existing page content"


def _read_text_if_exists(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _prompt_rule(candidate: MemoryCandidate) -> str:
    if candidate.prompt_visibility == "never":
        return "Do not include this memory in prompts."
    if candidate.memory_state == MemoryState.OPEN_QUESTION:
        return "Surface this only as uncertainty or a clarification need."
    if candidate.memory_state == MemoryState.CORRECTION:
        return "Use this as a guardrail when older memory would conflict."
    if candidate.memory_state == MemoryState.INFERRED:
        return "Use only with explicit uncertainty language when task-relevant."
    return "Include only when directly task-relevant and no stricter correction applies."


def _state_for_sentence(sentence: str, default: MemoryState) -> MemoryState:
    lower = sentence.lower()
    if _open_question_claim(sentence) is not None:
        return MemoryState.OPEN_QUESTION
    if re.search(r"\b(?:i might|i may|probably|maybe|seems like|appears that)\b", lower):
        return MemoryState.INFERRED
    if re.search(r"\b(?:i usually|i often|i tend to|i keep)\b", lower):
        return MemoryState.OBSERVED_PATTERN
    return default


def _confidence_for_state(state: MemoryState) -> Tuple[str, float, str]:
    if state == MemoryState.CONFIRMED:
        return "high", 0.90, "user_confirmed"
    if state == MemoryState.CORRECTION:
        return "high", 0.92, "user_confirmed"
    if state == MemoryState.OBSERVED_PATTERN:
        return "medium", 0.70, "llm_reviewed"
    if state == MemoryState.INFERRED:
        return "low", 0.45, "needs_user_review"
    if state == MemoryState.OPEN_QUESTION:
        return "low", 0.20, "needs_user_review"
    return "low", 0.30, "needs_user_review"


def _sensitivity_for_page_type(page_type: PageType) -> str:
    if page_type in {PageType.CONCEPT}:
        return "internal"
    if page_type in {PageType.PROJECT, PageType.DECISION, PageType.OPEN_QUESTION}:
        return "internal"
    if page_type in {PageType.PERSON, PageType.ORG, PageType.VALUE, PageType.PREFERENCE}:
        return "private"
    if page_type == PageType.CORRECTION:
        return "private"
    return "private"


def _prompt_visibility_for(
    page_type: PageType,
    sensitivity: str,
    state: MemoryState,
) -> str:
    if state == MemoryState.OPEN_QUESTION:
        return "confirm_first"
    if state == MemoryState.INFERRED:
        return "confirm_first" if sensitivity in {"private", "restricted"} else "task_only"
    if page_type == PageType.CONCEPT and sensitivity == "public":
        return "safe"
    if page_type == PageType.CORRECTION:
        return "task_only"
    return "task_only"


def _stale_after(page_type: PageType, state: MemoryState) -> str:
    if page_type == PageType.CONCEPT:
        return "P180D"
    if page_type in {PageType.PROJECT, PageType.OPEN_QUESTION}:
        return "P30D"
    if state == MemoryState.CORRECTION:
        return "P180D"
    return "P90D"


def _source_sensitivity(messages: Sequence[ConversationMessage]) -> str:
    for message in messages:
        if SECRET_RE.search(message.text):
            return "secret"
    return "private"


def _source_path(source_id: str, channel: str, retention: SourceRetention) -> str:
    if retention == SourceRetention.STORE:
        return "raw/conversations/{}/{}.txt".format(slugify(channel), source_id)
    return "raw/redactions/{}.json".format(source_id)


def _default_source_id(captured_at: datetime, channel: str, digest: str) -> str:
    return "src-{}-{}-{}".format(
        captured_at.astimezone(timezone.utc).strftime("%Y-%m-%d"),
        slugify(channel),
        digest[:10],
    )


def _first_event_at(messages: Sequence[ConversationMessage]) -> Optional[datetime]:
    timestamps = [message.timestamp for message in messages if message.timestamp is not None]
    if not timestamps:
        return None
    return min(timestamps)


def _is_user_message(message: ConversationMessage) -> bool:
    speaker = _normalize_speaker(message.speaker)
    return speaker in USER_SPEAKERS or speaker not in ASSISTANT_SPEAKERS


def _looks_like_speaker(value: str) -> bool:
    return _normalize_speaker(value) in USER_SPEAKERS.union(ASSISTANT_SPEAKERS)


def _normalize_speaker(value: str) -> str:
    return re.sub(r"[^a-z]+", "_", value.strip().lower()).strip("_")


def _sentences(text: str) -> Tuple[str, ...]:
    parts = re.split(r"(?<=[.?!])\s+|\n+", text)
    return tuple(_clean_sentence(part) for part in parts if _clean_sentence(part))


def _clean_sentence(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _trim_terminal_punctuation(value: str) -> str:
    return value.strip().rstrip(" .?!")


def _positive_phrase(value: str) -> str:
    phrase = _trim_terminal_punctuation(value)
    phrase = re.split(r"\s*,?\s+\bnot\b\s+", phrase, maxsplit=1, flags=re.IGNORECASE)[0]
    phrase = re.split(r"\s*,\s*not\s+", phrase, maxsplit=1, flags=re.IGNORECASE)[0]
    return phrase.strip()


def _title_from_phrase(value: str, prefix: Optional[str] = None) -> str:
    phrase = _positive_phrase(value)
    phrase = re.sub(r"^(that|to|the|a|an|use|keep|make|avoid|do not|don't)\s+", "", phrase, flags=re.IGNORECASE)
    phrase = re.sub(r"[^A-Za-z0-9 &/_-]+", " ", phrase)
    words = [word for word in phrase.replace("/", " ").split() if word.lower() not in {"my", "our", "me"}]
    if not words:
        words = ["Memory"]
    title = " ".join(words[:8]).title()
    if prefix and not title.lower().startswith(prefix.lower()):
        return "{} {}".format(prefix, title)
    return title


def _open_question_claim(sentence: str) -> Optional[str]:
    match = re.search(r"\bopen question\s*[:\-]\s*(?P<claim>[^.?!]+)", sentence, flags=re.IGNORECASE)
    if match:
        return match.group("claim")
    if sentence.strip().endswith("?") and not re.search(r"\b(?:can you|could you|please|will you)\b", sentence, flags=re.IGNORECASE):
        return sentence.strip().rstrip("?")
    if re.search(r"\b(?:not sure whether|need to decide whether|unknown whether)\b", sentence, flags=re.IGNORECASE):
        return sentence
    return None


def _is_correction_sentence(sentence: str) -> bool:
    if re.search(
        r"\b(?:actually|correction|to correct|rather than|instead of)\b",
        sentence,
        flags=re.IGNORECASE,
    ):
        return True
    return bool(
        re.search(
            r"\bnot\b.+\b(?:but|prefer|instead)\b",
            sentence,
            flags=re.IGNORECASE,
        )
    )


def _short_claim(value: str, limit: int = 160) -> str:
    claim = _clean_sentence(value)
    if len(claim) <= limit:
        return claim
    return "{}...".format(claim[: max(0, limit - 3)].rstrip())


def _normalize_claim(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _format_dt(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _optional_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, int):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str) and value:
        return parse_datetime(value)
    return None


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UserMemoryIngestError("{} must be a non-empty string".format(field_name))
    return value.strip()


def _canonical_source_text(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
