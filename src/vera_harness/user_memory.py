"""Deterministic conversation-to-user-memory wiki ingest helpers."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .chat import session_id_for_telegram
from .models import TelegramTask


class UserMemoryIngestError(RuntimeError):
    """Raised when a user-memory ingest cannot be planned or applied."""


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
    RETRACTED = "retracted"


class SourceRetention(str, Enum):
    HASH_ONLY = "hash_only"
    STORE = "store"


class MemorySensitivity(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    PRIVATE = "private"
    RESTRICTED = "restricted"
    SECRET = "secret"


class UserMemoryTaskType(str, Enum):
    """Broad task scopes used to bias user-memory retrieval."""

    GENERAL = "general"
    PROJECT_EXECUTION = "project_execution"
    USER_REPRESENTATION = "user_representation"
    SOCIAL_COORDINATION = "social_coordination"
    CORRECTION_HANDLING = "correction_handling"
    MEMORY_MAINTENANCE = "memory_maintenance"


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

RESTRICTED_RE = re.compile(
    r"\b("
    r"medical|health|diagnosis|therapy|therapist|doctor|medication|hospital|"
    r"finance|financial|bank|payment|salary|debt|tax|legal|lawyer|lawsuit|"
    r"identity|passport|ssn|social security|address|location|safety"
    r")\b",
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
    confirmation_required_candidates: Tuple[MemoryCandidate, ...]
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
            "confirmation_required_candidates: {}".format(
                len(self.confirmation_required_candidates)
            ),
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
        if not self.contradictions and not self.confirmation_required_candidates:
            lines.append("- none")
        for contradiction in self.contradictions:
            lines.append(
                "- review/contradictions.md: {} conflicts with existing {}".format(
                    contradiction.new_summary,
                    contradiction.path,
                )
            )
        for candidate in self.confirmation_required_candidates:
            lines.append(
                "- review/pending.md: high-sensitivity inferred memory requires explicit confirmation before wiki storage [{}; source: {}]".format(
                    candidate.sensitivity,
                    candidate.source_refs[0].source_id if candidate.source_refs else "unknown-source",
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
    supersedes: Tuple[str, ...]
    superseded_by: Tuple[str, ...]
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


@dataclass(frozen=True)
class _MemoryControlCommand:
    action: str
    query: str = ""
    replacement: str = ""
    sensitivity: str = ""


class UserMemoryControlController:
    """Owner-facing Telegram controls for inspecting and changing user memory."""

    def __init__(self) -> None:
        self._last_matches: Dict[str, Tuple[str, ...]] = {}

    def handle(self, task: TelegramTask, root: Optional[Path]) -> Optional[str]:
        command = _parse_memory_control_command(task.text)
        if command is None:
            return None
        if root is None:
            return (
                "User memory is not configured. Set `VERA_USER_MEMORY_ROOT` or "
                "`owner.user_memory_root` before using memory controls."
            )
        memory_root = root.expanduser().resolve()
        session_id = session_id_for_telegram(task.chat_id, task.user_id)
        if command.action == "help":
            return _format_memory_control_help()
        if command.action == "recent":
            return _format_recent_memory_updates(memory_root)
        if command.action == "list":
            pages = _find_memory_control_matches(
                memory_root,
                command.query,
                self._last_matches.get(session_id, ()),
            )
            self._remember_matches(session_id, pages)
            return _format_memory_control_list(command.query, pages)
        if command.action == "correct":
            pages = _find_memory_control_matches(
                memory_root,
                command.query,
                self._last_matches.get(session_id, ()),
                limit=1,
            )
            if not pages:
                return _no_memory_match_response(command.query)
            response = _apply_memory_correction(
                memory_root,
                pages[0],
                command.replacement,
                task,
            )
            self._remember_matches(session_id, (load_user_memory_page(memory_root, pages[0].relative_path),))
            return response
        if command.action == "forget":
            pages = _find_memory_control_matches(
                memory_root,
                command.query,
                self._last_matches.get(session_id, ()),
                limit=1,
            )
            if not pages:
                return _no_memory_match_response(command.query)
            response = _apply_memory_forget(memory_root, pages, task)
            self._last_matches[session_id] = ()
            return response
        if command.action == "mark":
            pages = _find_memory_control_matches(
                memory_root,
                command.query,
                self._last_matches.get(session_id, ()),
                limit=1,
            )
            if not pages:
                return _no_memory_match_response(command.query)
            response = _apply_memory_sensitivity_mark(
                memory_root,
                pages[0],
                command.sensitivity,
                task,
            )
            self._remember_matches(session_id, (load_user_memory_page(memory_root, pages[0].relative_path),))
            return response
        return None

    def _remember_matches(self, session_id: str, pages: Sequence[Optional["UserMemoryPage"]]) -> None:
        self._last_matches[session_id] = tuple(
            page.relative_path for page in pages if page is not None
        )


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


def load_user_memory_page(root: Path, relative_path: str) -> Optional[UserMemoryPage]:
    """Load one synthesized wiki page by corpus-relative path."""

    root = root.expanduser().resolve()
    path = (root / relative_path).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    if not path.exists():
        return None
    return _load_user_memory_page(path, root)


def _parse_memory_control_command(text: str) -> Optional[_MemoryControlCommand]:
    stripped = _clean_sentence(text)
    lower = stripped.lower()
    if lower in {"/memory", "/memory help", "memory help", "help memory"}:
        return _MemoryControlCommand(action="help")
    if lower in {"/memory recent", "show recent memory updates", "recent memory updates"}:
        return _MemoryControlCommand(action="recent")
    match = re.match(r"^/memory\s+recent(?:\s+\d+)?$", lower)
    if match:
        return _MemoryControlCommand(action="recent")
    for prefix in ("/memory correct ", "correct "):
        if lower.startswith(prefix):
            body = stripped[len(prefix) :].strip()
            correction = re.match(r"(?P<query>.+?)\s+to\s+(?P<replacement>.+)$", body, flags=re.IGNORECASE)
            if correction:
                return _MemoryControlCommand(
                    action="correct",
                    query=correction.group("query").strip(),
                    replacement=correction.group("replacement").strip(),
                )
    for prefix in ("/memory forget", "forget"):
        if lower == prefix or lower.startswith("{} ".format(prefix)):
            query = stripped[len(prefix) :].strip()
            return _MemoryControlCommand(action="forget", query=query or "this")
    mark = re.match(
        r"^(?:/memory\s+)?mark\s+(?P<query>.+?)\s+as\s+(?P<sensitivity>public|internal|private|sensitive|restricted|secret)$",
        stripped,
        flags=re.IGNORECASE,
    )
    if mark:
        return _MemoryControlCommand(
            action="mark",
            query=mark.group("query").strip(),
            sensitivity=_normalize_control_sensitivity(mark.group("sensitivity")),
        )
    remember = re.match(
        r"^(?:/memory\s+show\s+|/memory\s+search\s+)?what do you remember(?: about)?\s*(?P<query>.*?)\??$",
        stripped,
        flags=re.IGNORECASE,
    )
    if remember and (remember.group("query") or lower.startswith("/memory")):
        return _MemoryControlCommand(
            action="list",
            query=remember.group("query").strip() or "memory",
        )
    for prefix in ("/memory show ", "/memory search "):
        if lower.startswith(prefix):
            return _MemoryControlCommand(action="list", query=stripped[len(prefix) :].strip())
    return None


def _normalize_control_sensitivity(value: str) -> str:
    lower = value.strip().lower()
    if lower == "sensitive":
        return MemorySensitivity.RESTRICTED.value
    try:
        return MemorySensitivity(lower).value
    except ValueError:
        return MemorySensitivity.PRIVATE.value


def _format_memory_control_help() -> str:
    return "\n".join(
        [
            "User memory controls:",
            "- `what do you remember about X?` lists matching memory with source and confidence metadata.",
            "- `correct X to Y` records a correction and updates the active claim used for retrieval.",
            "- `forget X` deletes matching synthesized memory and tombstones source references when policy requires it.",
            "- `mark X as private` or `mark this as sensitive` changes sensitivity and prompt visibility.",
            "- `show recent memory updates` shows recent memory audit log entries.",
        ]
    )


def _find_memory_control_matches(
    root: Path,
    query: str,
    last_paths: Sequence[str],
    limit: int = 5,
) -> Tuple[UserMemoryPage, ...]:
    normalized_query = _clean_sentence(query).strip()
    if normalized_query.lower() in {"this", "that"} and last_paths:
        pages = tuple(
            page
            for page in (load_user_memory_page(root, path) for path in last_paths)
            if page is not None and not _page_is_deleted_or_unusable(page)
        )
        return pages[:limit]
    pages = tuple(page for page in load_user_memory_pages(root) if not _page_is_deleted_or_unusable(page))
    if not normalized_query:
        return pages[:limit]
    if normalized_query.isdigit() and last_paths:
        index = int(normalized_query) - 1
        if 0 <= index < len(last_paths):
            page = load_user_memory_page(root, last_paths[index])
            if page is not None and not _page_is_deleted_or_unusable(page):
                return (page,)
    query_tokens = _tokenize_for_retrieval(normalized_query)
    scored: List[Tuple[float, UserMemoryPage]] = []
    query_lower = normalized_query.lower()
    for page in pages:
        score = _memory_relevance_score(page, query_tokens, UserMemoryTaskType.MEMORY_MAINTENANCE)
        haystack = " ".join(
            [
                page.title,
                page.relative_path,
                page.summary,
                page.body_text,
                " ".join(page.tags),
            ]
        ).lower()
        if query_lower and query_lower in haystack:
            score += 4.0
        if score > 0:
            scored.append((score, page))
    ranked = sorted(
        scored,
        key=lambda item: (
            -item[0],
            _memory_control_page_rank(item[1]),
            _memory_state_rank(item[1]),
            item[1].relative_path,
        ),
    )
    return tuple(page for _, page in ranked[:limit])


def _memory_control_page_rank(page: UserMemoryPage) -> int:
    if page.page_type == PageType.CORRECTION or page.memory_state == MemoryState.CORRECTION.value:
        return 1
    return 0


def _format_memory_control_list(query: str, pages: Sequence[UserMemoryPage]) -> str:
    if not pages:
        return _no_memory_match_response(query)
    lines = ["I found {} remembered claim(s) for `{}`:".format(len(pages), query or "memory")]
    for index, page in enumerate(pages, start=1):
        summary = page.summary
        if page.sensitivity == MemorySensitivity.SECRET.value:
            summary = "Details withheld because this memory is classified as `secret`."
        lines.extend(
            [
                "",
                "{}. {} - {}".format(index, page.title, summary),
                "   path: {}".format(page.relative_path),
                "   state: {}; confidence: {}; sensitivity: {}; visibility: {}; review: {}".format(
                    page.memory_state,
                    page.confidence_level,
                    page.sensitivity,
                    page.prompt_visibility,
                    page.review_status,
                ),
            ]
        )
        if page.source_refs:
            ref = page.source_refs[0]
            lines.append(
                "   source: {} ({}; support: {})".format(
                    ref.source_id,
                    ref.locator or "locator:unknown",
                    ref.support or "unknown",
                )
            )
        if page.corrections:
            lines.append("   corrections: {}".format(", ".join(page.corrections)))
        if page.superseded_by:
            lines.append("   superseded_by: {}".format(", ".join(page.superseded_by)))
    return "\n".join(lines)


def _no_memory_match_response(query: str) -> str:
    return "I do not have matching user-memory pages for `{}`.".format(query or "memory")


def _apply_memory_correction(
    root: Path,
    page: UserMemoryPage,
    replacement: str,
    task: TelegramTask,
) -> str:
    replacement_claim = _normalize_replacement_claim(replacement)
    sensitivity = _max_sensitivity(page.sensitivity, _content_sensitivity(replacement_claim))
    source = _memory_control_source_record(task, "correction", sensitivity)
    _write_memory_control_source_record(root, source, "memory correction command")
    correction_path = _write_memory_correction_page(root, page, replacement_claim, source, sensitivity)
    _write_corrected_memory_page(root, page, replacement_claim, correction_path, source, sensitivity)
    _rebuild_index(root, _owner_user_for_root(root))
    _append_memory_control_log(
        root,
        "correction",
        source.source_id,
        (page.relative_path, correction_path),
        "updated active claim and linked correction record",
    )
    return (
        "Updated {}. The active claim now reads: {} Correction record: {}.".format(
            page.title,
            replacement_claim,
            correction_path,
        )
    )


def _apply_memory_forget(
    root: Path,
    pages: Sequence[UserMemoryPage],
    task: TelegramTask,
) -> str:
    sensitivity = MemorySensitivity.PRIVATE.value
    for page in pages:
        sensitivity = _max_sensitivity(sensitivity, page.sensitivity)
    source = _memory_control_source_record(task, "deletion", sensitivity)
    _write_memory_control_source_record(root, source, "memory deletion command")
    changed = []
    for page in pages:
        _write_deleted_memory_page(root, page, source)
        changed.append(page.relative_path)
    _redact_deleted_source_refs(root, pages, source)
    _rebuild_index(root, _owner_user_for_root(root))
    _append_memory_control_log(
        root,
        "forget",
        source.source_id,
        tuple(changed),
        "deleted synthesized memory and redacted source refs according to retention policy",
    )
    titles = ", ".join(page.title for page in pages)
    return (
        "Forgot {} memory page(s): {}. Deleted pages are tombstoned and excluded from future retrieval.".format(
            len(pages),
            titles,
        )
    )


def _apply_memory_sensitivity_mark(
    root: Path,
    page: UserMemoryPage,
    sensitivity: str,
    task: TelegramTask,
) -> str:
    source = _memory_control_source_record(task, "sensitivity", sensitivity)
    _write_memory_control_source_record(root, source, "memory sensitivity command")
    page_path = root / page.relative_path
    existing = page_path.read_text(encoding="utf-8")
    state = _enum_or_none(MemoryState, page.memory_state) or MemoryState.CONFIRMED
    updated = _replace_frontmatter_scalar(existing, "sensitivity", sensitivity)
    updated = _replace_frontmatter_scalar(
        updated,
        "prompt_visibility",
        _prompt_visibility_for(page.page_type, sensitivity, state),
    )
    updated = _replace_frontmatter_scalar(updated, "updated_at", _format_dt(source.captured_at))
    updated = _append_frontmatter_source_refs(
        updated,
        (
            CandidateSourceRef(
                source_id=source.source_id,
                path=source.path,
                locator="message:{}".format(task.message_id),
                claim="User marked memory sensitivity.",
                support="correction",
                excerpt_hash="sha256:{}".format(source.sha256[:16]),
            ),
        ),
    )
    updated = updated.rstrip() + "\n\n## Sensitivity Update\n\n- Marked as `{}` by explicit user command [source: {}].\n".format(
        sensitivity,
        source.source_id,
    )
    page_path.write_text(updated, encoding="utf-8")
    _rebuild_index(root, _owner_user_for_root(root))
    _append_memory_control_log(
        root,
        "sensitivity",
        source.source_id,
        (page.relative_path,),
        "marked sensitivity as {}".format(sensitivity),
    )
    return "Marked {} as `{}`. Prompt visibility is now `{}`.".format(
        page.title,
        sensitivity,
        _prompt_visibility_for(page.page_type, sensitivity, state),
    )


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
    confirmation_required_candidates = tuple(
        candidate for candidate in candidates if _requires_confirmation_before_storage(candidate)
    )
    edits: List[ProposedWikiEdit] = []
    contradictions: List[ContradictionRecord] = []
    for candidate in candidates:
        if candidate in confirmation_required_candidates:
            continue
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
        confirmation_required_candidates=confirmation_required_candidates,
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
    _update_pending_confirmations(plan)
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
        supersedes=tuple(metadata.get("supersedes", ())),
        superseded_by=tuple(metadata.get("superseded_by", ())),
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
        or page.memory_state == MemoryState.RETRACTED.value
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
        MemoryState.RETRACTED.value: 99,
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
    sensitivity = _sensitivity_for_candidate(page_type, claim, message.text)
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


def _normalize_replacement_claim(value: str) -> str:
    claim = _trim_terminal_punctuation(_clean_sentence(value))
    if not claim:
        return "User corrected this memory."
    if re.match(r"^(user|the user)\b", claim, flags=re.IGNORECASE):
        return claim[0].upper() + claim[1:] + "."
    return "User corrected this memory to: {}.".format(claim)


def _memory_control_source_record(
    task: TelegramTask,
    source_type: str,
    sensitivity: str,
) -> SourceRecord:
    captured_at = task.received_at or datetime.now(timezone.utc)
    digest = _sha256("{}:{}:{}:{}".format(task.chat_id, task.user_id, task.message_id, task.text))
    source_id = "src-{}-telegram-memory-{}-{}".format(
        captured_at.astimezone(timezone.utc).strftime("%Y-%m-%d"),
        slugify(source_type),
        digest[:10],
    )
    return SourceRecord(
        source_id=source_id,
        path="raw/redactions/{}.json".format(source_id),
        source_type=source_type,
        channel="telegram",
        captured_at=captured_at,
        source_event_at=task.received_at,
        sha256=digest,
        sensitivity=sensitivity,
        consent_scope="store",
        retention=SourceRetention.HASH_ONLY,
        redaction_state="redacted",
        message_count=1,
    )


def _write_memory_control_source_record(root: Path, source: SourceRecord, reason: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    redaction_path = root / source.path
    redaction_path.parent.mkdir(parents=True, exist_ok=True)
    if not redaction_path.exists():
        redaction_path.write_text(
            json.dumps(
                {
                    "source_id": source.source_id,
                    "sha256": source.sha256,
                    "channel": source.channel,
                    "message_count": source.message_count,
                    "retention": source.retention.value,
                    "raw_content": "not retained",
                    "reason": reason,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    manifest_path = root / "raw" / "manifest.jsonl"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    existing = manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else ""
    if '"source_id": "{}"'.format(source.source_id) not in existing:
        with manifest_path.open("a", encoding="utf-8") as manifest:
            manifest.write(json.dumps(_source_record_json(source), sort_keys=True) + "\n")


def _write_memory_correction_page(
    root: Path,
    page: UserMemoryPage,
    replacement_claim: str,
    source: SourceRecord,
    sensitivity: str,
) -> str:
    slug = "correction-{}-{}".format(slugify(page.title), source.sha256[:8])
    relative_path = "wiki/corrections/{}.md".format(slug)
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    now = _format_dt(source.captured_at)
    prompt_visibility = _prompt_visibility_for(PageType.CORRECTION, sensitivity, MemoryState.CORRECTION)
    lines = [
        "---",
        "id: mem-correction-{}".format(slug),
        "title: Correction {}".format(page.title),
        "page_type: correction",
        "owner_user: {}".format(_owner_user_for_root(root)),
        "status: active",
        "memory_state: correction",
        "confidence:",
        "  level: high",
        "  score: 0.92",
        "sensitivity: {}".format(sensitivity),
        "prompt_visibility: {}".format(prompt_visibility),
        "review_status: user_confirmed",
        "created_at: {}".format(now),
        "updated_at: {}".format(now),
        "last_observed_at: {}".format(now),
        "last_confirmed_at: {}".format(now),
        "stale_after: P180D",
        "source_refs:",
        "  - source_id: {}".format(source.source_id),
        "    path: {}".format(source.path),
        "    locator: message:control",
        "    claim: User corrected {}.".format(_yaml_scalar(page.title)),
        "    support: correction",
        "    excerpt_hash: sha256:{}".format(source.sha256[:16]),
        "related:",
        "  - {}".format(page.relative_path),
        "supersedes:",
        "  - {}".format(page.relative_path),
        "superseded_by: []",
        "contradictions: []",
        "corrections: []",
        "tags: [correction, memory-control]",
        "---",
        "",
        "# Correction {}".format(page.title),
        "",
        replacement_claim,
        "",
        "## Corrective Rule",
        "",
        "Use this correction instead of older wording from `{}`.".format(page.relative_path),
        "",
        "## Evidence",
        "",
        "- Explicit Telegram memory-control command [source: {}; confidence: high].".format(
            source.source_id
        ),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return relative_path


def _write_corrected_memory_page(
    root: Path,
    page: UserMemoryPage,
    replacement_claim: str,
    correction_path: str,
    source: SourceRecord,
    sensitivity: str,
) -> None:
    path = root / page.relative_path
    existing = path.read_text(encoding="utf-8")
    now = _format_dt(source.captured_at)
    state = MemoryState.CONFIRMED
    updated = _replace_frontmatter_scalar(existing, "status", "active")
    updated = _replace_frontmatter_scalar(updated, "memory_state", state.value)
    updated = _replace_frontmatter_scalar(updated, "review_status", "user_confirmed")
    updated = _replace_frontmatter_scalar(updated, "sensitivity", sensitivity)
    updated = _replace_frontmatter_scalar(
        updated,
        "prompt_visibility",
        _prompt_visibility_for(page.page_type, sensitivity, state),
    )
    updated = _replace_frontmatter_scalar(updated, "updated_at", now)
    updated = _replace_frontmatter_scalar(updated, "last_confirmed_at", now)
    updated = _append_frontmatter_list_values(updated, "corrections", (correction_path,))
    updated = _append_frontmatter_list_values(updated, "superseded_by", (correction_path,))
    updated = _append_frontmatter_source_refs(
        updated,
        (
            CandidateSourceRef(
                source_id=source.source_id,
                path=source.path,
                locator="message:control",
                claim="User corrected {}.".format(page.title),
                support="correction",
                excerpt_hash="sha256:{}".format(source.sha256[:16]),
            ),
        ),
    )
    frontmatter, body = _split_frontmatter(updated)
    remaining_sections = _body_sections_after_summary(body)
    old_summary = page.summary or "Previous claim text was present before correction."
    corrected_body = [
        "# {}".format(page.title),
        "",
        replacement_claim,
        "",
        "## Superseded Claim",
        "",
        old_summary,
        "",
        "## User Correction",
        "",
        "- Correction record: {}".format(correction_path),
        "- Source: {}".format(source.source_id),
        "",
    ]
    if remaining_sections:
        corrected_body.extend([remaining_sections.strip(), ""])
    if frontmatter is None:
        path.write_text("\n".join(corrected_body), encoding="utf-8")
    else:
        path.write_text("---\n{}\n---\n\n{}".format(frontmatter, "\n".join(corrected_body)), encoding="utf-8")


def _write_deleted_memory_page(root: Path, page: UserMemoryPage, source: SourceRecord) -> None:
    path = root / page.relative_path
    existing = path.read_text(encoding="utf-8")
    now = _format_dt(source.captured_at)
    updated = _replace_frontmatter_scalar(existing, "status", "deleted")
    updated = _replace_frontmatter_scalar(updated, "memory_state", MemoryState.RETRACTED.value)
    updated = _replace_frontmatter_scalar(updated, "prompt_visibility", "never")
    updated = _replace_frontmatter_scalar(updated, "review_status", "deletion_pending")
    updated = _replace_frontmatter_scalar(updated, "updated_at", now)
    updated = _redact_frontmatter_source_ref_claims(updated)
    updated = _append_frontmatter_source_refs(
        updated,
        (
            CandidateSourceRef(
                source_id=source.source_id,
                path=source.path,
                locator="message:control",
                claim="User requested deletion.",
                support="correction",
                excerpt_hash="sha256:{}".format(source.sha256[:16]),
            ),
        ),
    )
    frontmatter, _body = _split_frontmatter(updated)
    body = "\n".join(
        [
            "# Deleted Memory",
            "",
            "This memory was deleted by explicit user request. Original claim text was removed.",
            "",
            "## Tombstone",
            "",
            "- deletion_source: {}".format(source.source_id),
            "- deleted_at: {}".format(now),
            "",
        ]
    )
    if frontmatter is None:
        path.write_text(body, encoding="utf-8")
    else:
        path.write_text("---\n{}\n---\n\n{}".format(frontmatter, body), encoding="utf-8")


def _redact_deleted_source_refs(
    root: Path,
    pages: Sequence[UserMemoryPage],
    deletion_source: SourceRecord,
) -> None:
    source_ids = {
        ref.source_id
        for page in pages
        for ref in page.source_refs
        if ref.source_id
    }
    source_paths = {
        ref.path
        for page in pages
        for ref in page.source_refs
        if ref.path
    }
    for relative in source_paths:
        source_path = (root / relative).resolve()
        try:
            source_path.relative_to(root.resolve())
        except ValueError:
            continue
        if not source_path.exists() or "raw/redactions/" in source_path.as_posix():
            continue
        source_path.write_text(
            json.dumps(
                {
                    "deleted_at": _format_dt(deletion_source.captured_at),
                    "deletion_source": deletion_source.source_id,
                    "raw_content": "deleted by user request",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    manifest_path = root / "raw" / "manifest.jsonl"
    if not manifest_path.exists() or not source_ids:
        return
    updated_lines = []
    changed = False
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            updated_lines.append(line)
            continue
        if isinstance(record, dict) and record.get("source_id") in source_ids:
            record["consent_scope"] = "delete_requested"
            record["redaction_state"] = "pending_delete"
            record["notes"] = "source referenced deleted memory; deletion source {}".format(
                deletion_source.source_id
            )
            changed = True
            updated_lines.append(json.dumps(record, sort_keys=True))
        else:
            updated_lines.append(line)
    if changed:
        manifest_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


def _append_memory_control_log(
    root: Path,
    action: str,
    source_id: str,
    paths: Sequence[str],
    note: str,
) -> None:
    path = root / "log.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else "# User Memory Log\n"
    entry = "- {}: memory-control {} {} touched {}; {}.".format(
        _format_dt(datetime.now(timezone.utc)),
        action,
        source_id,
        ", ".join(paths) if paths else "none",
        note,
    )
    path.write_text(existing.rstrip() + "\n" + entry + "\n", encoding="utf-8")


def _format_recent_memory_updates(root: Path, limit: int = 5) -> str:
    path = root / "log.md"
    if not path.exists():
        return "No memory update log exists yet."
    entries = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("- ")
    ]
    if not entries:
        return "No memory update entries exist yet."
    lines = ["Recent memory updates:"]
    lines.extend(entries[-limit:])
    return "\n".join(lines)


def _owner_user_for_root(root: Path) -> str:
    index_path = root / "index.md"
    if index_path.exists():
        match = re.search(r"^Owner user:\s*(.+)$", index_path.read_text(encoding="utf-8"), flags=re.MULTILINE)
        if match:
            return match.group(1).strip()
    for page_path in sorted((root / "wiki").glob("*/*.md")):
        metadata = _page_metadata(page_path)
        owner = metadata.get("owner_user")
        if owner:
            return owner
    return "unknown"


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
                if current == "---" or (current and not current.startswith(" ")):
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


def _append_frontmatter_list_values(
    content: str,
    key: str,
    values: Sequence[str],
) -> str:
    additions = tuple(value for value in values if value)
    if not additions or not content.startswith("---\n"):
        return content
    end = content.find("\n---", 4)
    if end == -1:
        return content
    frontmatter = content[: end + 4]
    rest = content[end + 4 :]
    parsed = _parse_memory_frontmatter(frontmatter[4:-4])
    existing_values = tuple(parsed.get(key, ()))
    missing = tuple(value for value in additions if value not in existing_values)
    if not missing:
        return content
    lines = frontmatter.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.startswith("{}:".format(key)):
            start = index
            break
    if start is None:
        insert_at = len(lines) - 1
        lines.insert(insert_at, "{}:".format(key))
        for value in reversed(missing):
            lines.insert(insert_at + 1, "  - {}".format(value))
        return "\n".join(lines) + rest
    if lines[start].strip() == "{}: []".format(key):
        lines[start] = "{}:".format(key)
        insert_at = start + 1
    else:
        insert_at = start + 1
        while insert_at < len(lines):
            current = lines[insert_at]
            if current == "---" or (current and not current.startswith(" ")):
                break
            insert_at += 1
    for value in reversed(missing):
        lines.insert(insert_at, "  - {}".format(value))
    return "\n".join(lines) + rest


def _redact_frontmatter_source_ref_claims(content: str) -> str:
    if not content.startswith("---\n"):
        return content
    end = content.find("\n---", 4)
    if end == -1:
        return content
    frontmatter = content[:end]
    rest = content[end:]
    return re.sub(
        r"^    claim: .*$",
        "    claim: deleted by user request",
        frontmatter,
        flags=re.MULTILINE,
    ) + rest


def _body_sections_after_summary(body: str) -> str:
    lines = body.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.startswith("## "):
            start = index
            break
    if start is None:
        return ""
    return "\n".join(lines[start:])


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


def _update_pending_confirmations(plan: IngestPlan) -> None:
    if not plan.confirmation_required_candidates:
        return
    path = plan.root / "review" / "pending.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Pending Memory Confirmation\n"
    additions: List[str] = []
    for candidate in plan.confirmation_required_candidates:
        marker = "{} {}".format(plan.source_record.source_id, candidate.stable_id)
        if marker in existing:
            continue
        additions.extend(
            [
                "",
                "## {} - Confirmation Required".format(_format_dt(plan.source_record.captured_at)),
                "",
                "- marker: {}".format(marker),
                "- candidate_id: {}".format(candidate.stable_id),
                "- page_type: {}".format(candidate.page_type.value),
                "- sensitivity: {}".format(candidate.sensitivity),
                "- memory_state: {}".format(candidate.memory_state.value),
                "- source: {}".format(plan.source_record.source_id),
                "- action: high-sensitivity inferred claim withheld pending explicit user confirmation.",
            ]
        )
    if additions:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(existing.rstrip() + "\n" + "\n".join(additions) + "\n", encoding="utf-8")


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
        "confirmation_required: {}; retention: {}; withheld_secret_candidates: {}."
    ).format(
        _format_dt(plan.source_record.captured_at),
        plan.source_record.source_id,
        plan.source_record.channel,
        touched,
        len(plan.candidates),
        contradictions,
        len(plan.confirmation_required_candidates),
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
    if state == MemoryState.RETRACTED:
        return "low", 0.0, "deletion_pending"
    return "low", 0.30, "needs_user_review"


def _sensitivity_for_page_type(page_type: PageType) -> str:
    if page_type in {PageType.CONCEPT}:
        return MemorySensitivity.INTERNAL.value
    if page_type in {PageType.PROJECT, PageType.DECISION, PageType.OPEN_QUESTION}:
        return MemorySensitivity.INTERNAL.value
    if page_type in {PageType.PERSON, PageType.ORG, PageType.VALUE, PageType.PREFERENCE}:
        return MemorySensitivity.PRIVATE.value
    if page_type == PageType.CORRECTION:
        return MemorySensitivity.PRIVATE.value
    return MemorySensitivity.PRIVATE.value


def _sensitivity_for_candidate(page_type: PageType, claim: str, source_text: str) -> str:
    base = _sensitivity_for_page_type(page_type)
    content = _content_sensitivity("{} {}".format(claim, source_text))
    return _max_sensitivity(base, content)


def _content_sensitivity(text: str) -> str:
    if SECRET_RE.search(text):
        return MemorySensitivity.SECRET.value
    if RESTRICTED_RE.search(text):
        return MemorySensitivity.RESTRICTED.value
    return MemorySensitivity.PRIVATE.value


def _max_sensitivity(first: str, second: str) -> str:
    order = {
        MemorySensitivity.PUBLIC.value: 0,
        MemorySensitivity.INTERNAL.value: 1,
        MemorySensitivity.PRIVATE.value: 2,
        MemorySensitivity.RESTRICTED.value: 3,
        MemorySensitivity.SECRET.value: 4,
    }
    return first if order.get(first, 0) >= order.get(second, 0) else second


def _requires_confirmation_before_storage(candidate: MemoryCandidate) -> bool:
    return (
        candidate.memory_state == MemoryState.INFERRED
        and candidate.sensitivity in {MemorySensitivity.RESTRICTED.value, MemorySensitivity.SECRET.value}
    )


def _prompt_visibility_for(
    page_type: PageType,
    sensitivity: str,
    state: MemoryState,
) -> str:
    if sensitivity == MemorySensitivity.SECRET.value:
        return "never"
    if sensitivity == MemorySensitivity.RESTRICTED.value:
        return "confirm_first"
    if state == MemoryState.OPEN_QUESTION:
        return "confirm_first"
    if state == MemoryState.INFERRED:
        return "confirm_first" if sensitivity in {MemorySensitivity.PRIVATE.value, MemorySensitivity.RESTRICTED.value} else "task_only"
    if page_type == PageType.CONCEPT and sensitivity == MemorySensitivity.PUBLIC.value:
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
            return MemorySensitivity.SECRET.value
    for message in messages:
        if RESTRICTED_RE.search(message.text):
            return MemorySensitivity.RESTRICTED.value
    return MemorySensitivity.PRIVATE.value


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
