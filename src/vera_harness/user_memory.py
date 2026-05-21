"""Deterministic conversation-to-user-memory wiki ingest helpers."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

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


class SourceRetention(str, Enum):
    HASH_ONLY = "hash_only"
    STORE = "store"


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
