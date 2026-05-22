"""Durable owner-directed question queue for Vera context building."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple

from .user_memory import (
    CandidateSourceRef,
    IngestPlan,
    MemoryCandidate,
    MemoryState,
    PageType,
    ProposedWikiEdit,
    SourceRecord,
    SourceRetention,
    apply_ingest_plan,
    slugify,
)


QUEUE_SCHEMA_VERSION = 1
DEFAULT_PRIORITY = 0

SECRET_LIKE_RE = re.compile(
    r"\b(password|passcode|secret|api[_ -]?key|private key|token|credential)\b",
    re.IGNORECASE,
)
RESTRICTED_LIKE_RE = re.compile(
    r"\b("
    r"medical|health|diagnosis|therapy|therapist|doctor|medication|hospital|"
    r"finance|financial|bank|payment|salary|debt|tax|legal|lawyer|lawsuit|"
    r"identity|passport|ssn|social security|address|location|safety"
    r")\b",
    re.IGNORECASE,
)


class OwnerQuestionQueueError(RuntimeError):
    """Raised when owner-question queue state cannot be loaded or written."""


class OwnerQuestionStatus(str, Enum):
    """Lifecycle status for an owner-directed question."""

    PENDING = "pending"
    ASKED = "asked"
    ANSWERED = "answered"
    DISMISSED = "dismissed"
    EXPIRED = "expired"


@dataclass(frozen=True)
class OwnerQuestionSubjectRef:
    """Optional subject/entity reference for a queued owner question."""

    kind: str
    subject_id: str
    label: Optional[str] = None

    @property
    def display(self) -> str:
        return self.label or self.subject_id


@dataclass(frozen=True)
class OwnerQuestionAnswerMemoryRef:
    """Memory provenance written after the owner answers a queued question."""

    source_id: str
    path: str
    locator: str
    created_at: datetime


@dataclass(frozen=True)
class OwnerQuestion:
    """One persisted owner-directed question."""

    question_id: str
    question_text: str
    source: str
    priority: int
    status: OwnerQuestionStatus
    created_at: datetime
    updated_at: datetime
    subject_ref: Optional[OwnerQuestionSubjectRef] = None
    do_not_ask_before: Optional[datetime] = None
    last_asked_at: Optional[datetime] = None
    answered_at: Optional[datetime] = None
    dismissed_at: Optional[datetime] = None
    expired_at: Optional[datetime] = None
    ask_count: int = 0
    dedupe_key: str = ""
    answer_hash: Optional[str] = None
    answer_memory_refs: Tuple[OwnerQuestionAnswerMemoryRef, ...] = ()
    dismissal_reason: Optional[str] = None
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class OwnerQuestionCandidate:
    """Candidate question submitted by another Vera subsystem."""

    question_text: str
    source: str
    subject_ref: Optional[OwnerQuestionSubjectRef] = None
    priority: int = DEFAULT_PRIORITY
    do_not_ask_before: Optional[datetime] = None
    metadata: Mapping[str, str] = field(default_factory=dict)


class JsonOwnerQuestionQueueStore:
    """JSON-backed store for owner question queue state."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> Tuple[OwnerQuestion, ...]:
        if not self._path.exists():
            return ()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise OwnerQuestionQueueError(
                "owner question queue file is not valid JSON: {}".format(exc)
            )
        if not isinstance(raw, Mapping):
            raise OwnerQuestionQueueError("owner question queue file must contain a JSON object")
        if raw.get("schema_version") not in {None, QUEUE_SCHEMA_VERSION}:
            raise OwnerQuestionQueueError(
                "unsupported owner question queue schema_version: {}".format(
                    raw.get("schema_version")
                )
            )
        raw_questions = raw.get("questions", [])
        if not isinstance(raw_questions, list):
            raise OwnerQuestionQueueError("owner question queue `questions` must be a list")
        return tuple(
            _question_from_json(item)
            for item in raw_questions
            if isinstance(item, Mapping)
        )

    def save(self, questions: Sequence[OwnerQuestion]) -> None:
        payload = {
            "schema_version": QUEUE_SCHEMA_VERSION,
            "questions": [_question_to_json(question) for question in questions],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


class OwnerQuestionQueue:
    """Internal service API for enqueueing, selecting, and resolving questions."""

    def __init__(self, store: JsonOwnerQuestionQueueStore) -> None:
        self._store = store

    @property
    def store(self) -> JsonOwnerQuestionQueueStore:
        return self._store

    def list_questions(self) -> Tuple[OwnerQuestion, ...]:
        return self._store.load()

    def get_question(self, question_id: str) -> OwnerQuestion:
        for question in self._store.load():
            if question.question_id == question_id:
                return question
        raise OwnerQuestionQueueError("owner question not found: {}".format(question_id))

    def enqueue_candidate(
        self,
        candidate: OwnerQuestionCandidate,
        now: Optional[datetime] = None,
    ) -> OwnerQuestion:
        """Add or merge a candidate question without asking it immediately."""

        timestamp = _coerce_datetime(now)
        question_text = _required_text(candidate.question_text, "question_text")
        source = _required_text(candidate.source, "source")
        subject_ref = _normalize_subject_ref(candidate.subject_ref)
        dedupe_key = _dedupe_key(
            question_text=question_text,
            source=source,
            subject_ref=subject_ref,
        )
        questions = list(self._store.load())
        duplicate_index = _duplicate_question_index(
            questions,
            question_text=question_text,
            source=source,
            subject_ref=subject_ref,
            dedupe_key=dedupe_key,
        )
        if duplicate_index is not None:
            existing = questions[duplicate_index]
            merged = _merge_duplicate_question(
                existing,
                candidate,
                dedupe_key=dedupe_key,
                now=timestamp,
            )
            questions[duplicate_index] = merged
            self._store.save(questions)
            return merged

        question = OwnerQuestion(
            question_id="oq-{}".format(_sha256(dedupe_key)[:16]),
            question_text=question_text,
            source=source,
            subject_ref=subject_ref,
            priority=int(candidate.priority),
            status=OwnerQuestionStatus.PENDING,
            created_at=timestamp,
            updated_at=timestamp,
            do_not_ask_before=_coerce_optional_datetime(candidate.do_not_ask_before),
            dedupe_key=dedupe_key,
            metadata=_clean_metadata(candidate.metadata),
        )
        questions.append(question)
        self._store.save(questions)
        return question

    def enqueue_question(
        self,
        question_text: str,
        source: str,
        subject_ref: Optional[OwnerQuestionSubjectRef] = None,
        priority: int = DEFAULT_PRIORITY,
        do_not_ask_before: Optional[datetime] = None,
        metadata: Optional[Mapping[str, str]] = None,
        now: Optional[datetime] = None,
    ) -> OwnerQuestion:
        """Convenience wrapper for adding a single candidate question."""

        return self.enqueue_candidate(
            OwnerQuestionCandidate(
                question_text=question_text,
                source=source,
                subject_ref=subject_ref,
                priority=priority,
                do_not_ask_before=do_not_ask_before,
                metadata=metadata or {},
            ),
            now=now,
        )

    def select_next_pending_question(
        self,
        now: Optional[datetime] = None,
        sources: Optional[Iterable[str]] = None,
    ) -> Optional[OwnerQuestion]:
        """Return the highest priority pending question eligible to ask now."""

        timestamp = _coerce_datetime(now)
        source_filter = set(sources or ())
        eligible = []
        for question in self._store.load():
            if question.status != OwnerQuestionStatus.PENDING:
                continue
            if source_filter and question.source not in source_filter:
                continue
            if question.do_not_ask_before is not None and question.do_not_ask_before > timestamp:
                continue
            eligible.append(question)
        if not eligible:
            return None
        return sorted(
            eligible,
            key=lambda item: (
                -item.priority,
                item.ask_count,
                item.created_at,
                item.question_id,
            ),
        )[0]

    def mark_asked(
        self,
        question_id: str,
        do_not_ask_before: Optional[datetime] = None,
        now: Optional[datetime] = None,
    ) -> OwnerQuestion:
        timestamp = _coerce_datetime(now)

        def mutate(question: OwnerQuestion) -> OwnerQuestion:
            return replace(
                question,
                status=OwnerQuestionStatus.ASKED,
                last_asked_at=timestamp,
                updated_at=timestamp,
                ask_count=question.ask_count + 1,
                do_not_ask_before=_coerce_optional_datetime(do_not_ask_before),
            )

        return self._update_question(question_id, mutate)

    def defer_question(
        self,
        question_id: str,
        do_not_ask_before: datetime,
        now: Optional[datetime] = None,
    ) -> OwnerQuestion:
        timestamp = _coerce_datetime(now)
        cooldown = _coerce_datetime(do_not_ask_before)

        def mutate(question: OwnerQuestion) -> OwnerQuestion:
            return replace(
                question,
                status=OwnerQuestionStatus.PENDING,
                do_not_ask_before=cooldown,
                updated_at=timestamp,
            )

        return self._update_question(question_id, mutate)

    def mark_answered(
        self,
        question_id: str,
        answer_text: str,
        memory_root: Optional[Path] = None,
        owner_user: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> OwnerQuestion:
        """Resolve a question and optionally persist the explicit answer to user memory."""

        timestamp = _coerce_datetime(now)
        answer = _required_text(answer_text, "answer_text")
        if memory_root is not None and not owner_user:
            raise OwnerQuestionQueueError("owner_user is required when memory_root is provided")
        questions = list(self._store.load())
        index, question = _find_question(questions, question_id)
        answer_hash = "sha256:{}".format(_sha256(answer))
        refs: Tuple[OwnerQuestionAnswerMemoryRef, ...] = ()
        if memory_root is not None and owner_user is not None:
            refs = _persist_answer_to_user_memory(
                question=question,
                answer_text=answer,
                memory_root=memory_root,
                owner_user=owner_user,
                now=timestamp,
            )
        updated = replace(
            question,
            status=OwnerQuestionStatus.ANSWERED,
            answered_at=timestamp,
            updated_at=timestamp,
            answer_hash=answer_hash,
            answer_memory_refs=_unique_memory_refs(question.answer_memory_refs + refs),
        )
        questions[index] = updated
        self._store.save(questions)
        return updated

    def dismiss_question(
        self,
        question_id: str,
        reason: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> OwnerQuestion:
        timestamp = _coerce_datetime(now)

        def mutate(question: OwnerQuestion) -> OwnerQuestion:
            return replace(
                question,
                status=OwnerQuestionStatus.DISMISSED,
                dismissed_at=timestamp,
                updated_at=timestamp,
                dismissal_reason=_clean_optional_reason(reason),
            )

        return self._update_question(question_id, mutate)

    def expire_question(
        self,
        question_id: str,
        now: Optional[datetime] = None,
    ) -> OwnerQuestion:
        timestamp = _coerce_datetime(now)

        def mutate(question: OwnerQuestion) -> OwnerQuestion:
            return replace(
                question,
                status=OwnerQuestionStatus.EXPIRED,
                expired_at=timestamp,
                updated_at=timestamp,
            )

        return self._update_question(question_id, mutate)

    def _update_question(self, question_id: str, mutate: Any) -> OwnerQuestion:
        questions = list(self._store.load())
        index, question = _find_question(questions, question_id)
        updated = mutate(question)
        questions[index] = updated
        self._store.save(questions)
        return updated


def _find_question(
    questions: Sequence[OwnerQuestion],
    question_id: str,
) -> Tuple[int, OwnerQuestion]:
    for index, question in enumerate(questions):
        if question.question_id == question_id:
            return index, question
    raise OwnerQuestionQueueError("owner question not found: {}".format(question_id))


def _merge_duplicate_question(
    existing: OwnerQuestion,
    candidate: OwnerQuestionCandidate,
    dedupe_key: str,
    now: datetime,
) -> OwnerQuestion:
    if existing.status in {
        OwnerQuestionStatus.ANSWERED,
        OwnerQuestionStatus.DISMISSED,
        OwnerQuestionStatus.EXPIRED,
    }:
        return existing
    merged_metadata = dict(existing.metadata)
    merged_metadata.update(_clean_metadata(candidate.metadata))
    cooldown = _merge_cooldown(
        existing.do_not_ask_before,
        _coerce_optional_datetime(candidate.do_not_ask_before),
    )
    return replace(
        existing,
        priority=max(existing.priority, int(candidate.priority)),
        updated_at=now,
        do_not_ask_before=cooldown,
        dedupe_key=dedupe_key,
        metadata=merged_metadata,
    )


def _merge_cooldown(
    existing: Optional[datetime],
    candidate: Optional[datetime],
) -> Optional[datetime]:
    if existing is None:
        return candidate
    if candidate is None:
        return existing
    return min(existing, candidate)


def _duplicate_question_index(
    questions: Sequence[OwnerQuestion],
    question_text: str,
    source: str,
    subject_ref: Optional[OwnerQuestionSubjectRef],
    dedupe_key: str,
) -> Optional[int]:
    normalized = _normalize_question_text(question_text)
    tokens = _question_tokens(question_text)
    subject_key = _subject_key(subject_ref)
    for index, question in enumerate(questions):
        if question.dedupe_key == dedupe_key:
            return index
        if question.source != source:
            continue
        if _subject_key(question.subject_ref) != subject_key:
            continue
        existing_normalized = _normalize_question_text(question.question_text)
        if normalized == existing_normalized:
            return index
        if (
            subject_key != "none"
            and _token_similarity(tokens, _question_tokens(question.question_text)) >= 0.60
        ):
            return index
    return None


def _dedupe_key(
    question_text: str,
    source: str,
    subject_ref: Optional[OwnerQuestionSubjectRef],
) -> str:
    return "|".join(
        [
            source.strip().lower(),
            _subject_key(subject_ref),
            _normalize_question_text(question_text),
        ]
    )


def _subject_key(subject_ref: Optional[OwnerQuestionSubjectRef]) -> str:
    if subject_ref is None:
        return "none"
    identity = subject_ref.subject_id or subject_ref.label or ""
    return "{}:{}".format(subject_ref.kind.strip().lower(), identity.strip().lower())


def _normalize_subject_ref(
    subject_ref: Optional[OwnerQuestionSubjectRef],
) -> Optional[OwnerQuestionSubjectRef]:
    if subject_ref is None:
        return None
    kind = _required_text(subject_ref.kind, "subject_ref.kind")
    subject_id = _required_text(subject_ref.subject_id, "subject_ref.subject_id")
    label = subject_ref.label.strip() if subject_ref.label and subject_ref.label.strip() else None
    return OwnerQuestionSubjectRef(kind=kind, subject_id=subject_id, label=label)


def _normalize_question_text(value: str) -> str:
    lowered = value.lower()
    lowered = re.sub(r"<[^>]+>", " placeholder ", lowered)
    return " ".join(re.findall(r"[a-z0-9]+", lowered))


def _question_tokens(value: str) -> Tuple[str, ...]:
    stopwords = {
        "a",
        "about",
        "and",
        "are",
        "as",
        "how",
        "i",
        "is",
        "it",
        "of",
        "or",
        "should",
        "the",
        "them",
        "to",
        "what",
        "who",
        "with",
        "your",
    }
    return tuple(
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if token not in stopwords
    )


def _token_similarity(left: Sequence[str], right: Sequence[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / float(len(left_set | right_set))


def _persist_answer_to_user_memory(
    question: OwnerQuestion,
    answer_text: str,
    memory_root: Path,
    owner_user: str,
    now: datetime,
) -> Tuple[OwnerQuestionAnswerMemoryRef, ...]:
    if SECRET_LIKE_RE.search(answer_text):
        raise OwnerQuestionQueueError(
            "owner answer looks secret-like; not writing it to user memory"
        )
    answer_hash = _sha256(answer_text)
    source_id = "src-owner-question-{}-{}".format(
        question.question_id.replace("oq-", "")[:12],
        answer_hash[:8],
    )
    source_path = "raw/redactions/{}.json".format(source_id)
    source_record = SourceRecord(
        source_id=source_id,
        path=source_path,
        source_type="owner_question_answer",
        channel="owner_question_queue",
        captured_at=now,
        source_event_at=now,
        sha256=answer_hash,
        sensitivity=_answer_sensitivity(answer_text),
        consent_scope="owner_answered_question",
        retention=SourceRetention.HASH_ONLY,
        redaction_state="redacted",
        message_count=1,
    )
    page_type = _memory_page_type(question)
    title = _memory_title(question)
    prompt_visibility = "confirm_first" if source_record.sensitivity == "restricted" else "task_only"
    claim = "Owner-provided context about {}: {}.".format(
        title,
        _trim_terminal_punctuation(_clean_sentence(answer_text)),
    )
    source_ref = CandidateSourceRef(
        source_id=source_id,
        path=source_path,
        locator="owner_question:{}".format(question.question_id),
        claim="Owner answered queued question {}.".format(question.question_id),
        support="owner_answer",
        excerpt_hash="sha256:{}".format(answer_hash[:16]),
    )
    candidate = MemoryCandidate(
        page_type=page_type,
        title=title,
        claim=claim,
        memory_state=MemoryState.CONFIRMED,
        confidence_level="high",
        confidence_score=0.92,
        sensitivity=source_record.sensitivity,
        prompt_visibility=prompt_visibility,
        review_status="user_confirmed",
        source_refs=(source_ref,),
        tags=_memory_tags(question),
        related=(),
    )
    root = memory_root.expanduser().resolve()
    page_path = root / candidate.relative_path
    action = "create"
    if page_path.exists():
        existing = page_path.read_text(encoding="utf-8")
        action = "unchanged" if _normalize_answer(answer_text) in _normalize_answer(existing) else "update"
    plan = IngestPlan(
        root=root,
        owner_user=owner_user,
        source_record=source_record,
        candidates=(candidate,),
        confirmation_required_candidates=(),
        edits=(
            ProposedWikiEdit(
                action=action,
                path=page_path,
                relative_path=candidate.relative_path,
                candidate=candidate,
                contradiction=False,
            ),
        ),
        contradictions=(),
        withheld_secret_count=0,
        source_text=answer_text,
        apply=True,
    )
    apply_ingest_plan(plan)
    return (
        OwnerQuestionAnswerMemoryRef(
            source_id=source_id,
            path=candidate.relative_path,
            locator=source_ref.locator,
            created_at=now,
        ),
    )


def _memory_page_type(question: OwnerQuestion) -> PageType:
    subject_kind = question.subject_ref.kind.lower() if question.subject_ref else ""
    source = question.source.lower()
    if subject_kind in {"person", "contact", "handle", "imessage_contact"}:
        return PageType.PERSON
    if subject_kind in {"org", "organization"}:
        return PageType.ORG
    if subject_kind == "project" or "project" in source:
        return PageType.PROJECT
    if "relationship" in source or "contact" in source:
        return PageType.PERSON
    if "preference" in source or "boundary" in source:
        return PageType.PREFERENCE
    return PageType.CONCEPT


def _memory_title(question: OwnerQuestion) -> str:
    if question.subject_ref is not None:
        return _title_from_text(question.subject_ref.display)
    return _title_from_text(question.question_text)


def _memory_tags(question: OwnerQuestion) -> Tuple[str, ...]:
    tags = {"owner-question", slugify(question.source)}
    if question.subject_ref is not None:
        tags.add(slugify(question.subject_ref.kind))
    return tuple(sorted(tag for tag in tags if tag))


def _answer_sensitivity(answer_text: str) -> str:
    if RESTRICTED_LIKE_RE.search(answer_text):
        return "restricted"
    return "private"


def _title_from_text(value: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", value)
    if not words:
        return "Owner Question"
    trimmed = words[:8]
    return " ".join(word[:1].upper() + word[1:] for word in trimmed)


def _clean_sentence(value: str) -> str:
    return " ".join(value.strip().split())


def _trim_terminal_punctuation(value: str) -> str:
    return value.strip().rstrip(".?!")


def _normalize_answer(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _unique_memory_refs(
    refs: Sequence[OwnerQuestionAnswerMemoryRef],
) -> Tuple[OwnerQuestionAnswerMemoryRef, ...]:
    seen = set()
    unique: List[OwnerQuestionAnswerMemoryRef] = []
    for ref in refs:
        key = (ref.source_id, ref.path, ref.locator)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ref)
    return tuple(unique)


def _question_to_json(question: OwnerQuestion) -> Mapping[str, Any]:
    return {
        "question_id": question.question_id,
        "question_text": question.question_text,
        "source": question.source,
        "subject_ref": _subject_ref_to_json(question.subject_ref),
        "priority": question.priority,
        "status": question.status.value,
        "created_at": _format_dt(question.created_at),
        "updated_at": _format_dt(question.updated_at),
        "do_not_ask_before": _format_optional_dt(question.do_not_ask_before),
        "last_asked_at": _format_optional_dt(question.last_asked_at),
        "answered_at": _format_optional_dt(question.answered_at),
        "dismissed_at": _format_optional_dt(question.dismissed_at),
        "expired_at": _format_optional_dt(question.expired_at),
        "ask_count": question.ask_count,
        "dedupe_key": question.dedupe_key,
        "answer_hash": question.answer_hash,
        "answer_memory_refs": [
            _answer_ref_to_json(ref) for ref in question.answer_memory_refs
        ],
        "dismissal_reason": question.dismissal_reason,
        "metadata": dict(question.metadata),
    }


def _question_from_json(raw: Mapping[str, Any]) -> OwnerQuestion:
    return OwnerQuestion(
        question_id=_required_text(raw.get("question_id"), "question_id"),
        question_text=_required_text(raw.get("question_text"), "question_text"),
        source=_required_text(raw.get("source"), "source"),
        subject_ref=_subject_ref_from_json(raw.get("subject_ref")),
        priority=int(raw.get("priority", DEFAULT_PRIORITY)),
        status=OwnerQuestionStatus(raw.get("status", OwnerQuestionStatus.PENDING.value)),
        created_at=_parse_dt(_required_text(raw.get("created_at"), "created_at")),
        updated_at=_parse_dt(_required_text(raw.get("updated_at"), "updated_at")),
        do_not_ask_before=_parse_optional_dt(raw.get("do_not_ask_before")),
        last_asked_at=_parse_optional_dt(raw.get("last_asked_at")),
        answered_at=_parse_optional_dt(raw.get("answered_at")),
        dismissed_at=_parse_optional_dt(raw.get("dismissed_at")),
        expired_at=_parse_optional_dt(raw.get("expired_at")),
        ask_count=int(raw.get("ask_count", 0)),
        dedupe_key=str(raw.get("dedupe_key", "")),
        answer_hash=raw.get("answer_hash") if isinstance(raw.get("answer_hash"), str) else None,
        answer_memory_refs=tuple(
            _answer_ref_from_json(item)
            for item in raw.get("answer_memory_refs", [])
            if isinstance(item, Mapping)
        ),
        dismissal_reason=(
            raw.get("dismissal_reason")
            if isinstance(raw.get("dismissal_reason"), str)
            else None
        ),
        metadata=_clean_metadata(
            raw.get("metadata") if isinstance(raw.get("metadata"), Mapping) else {}
        ),
    )


def _subject_ref_to_json(
    subject_ref: Optional[OwnerQuestionSubjectRef],
) -> Optional[Mapping[str, str]]:
    if subject_ref is None:
        return None
    payload = {
        "kind": subject_ref.kind,
        "subject_id": subject_ref.subject_id,
    }
    if subject_ref.label:
        payload["label"] = subject_ref.label
    return payload


def _subject_ref_from_json(raw: object) -> Optional[OwnerQuestionSubjectRef]:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise OwnerQuestionQueueError("subject_ref must be an object")
    label = raw.get("label") if isinstance(raw.get("label"), str) else None
    return OwnerQuestionSubjectRef(
        kind=_required_text(raw.get("kind"), "subject_ref.kind"),
        subject_id=_required_text(raw.get("subject_id"), "subject_ref.subject_id"),
        label=label,
    )


def _answer_ref_to_json(ref: OwnerQuestionAnswerMemoryRef) -> Mapping[str, str]:
    return {
        "source_id": ref.source_id,
        "path": ref.path,
        "locator": ref.locator,
        "created_at": _format_dt(ref.created_at),
    }


def _answer_ref_from_json(raw: Mapping[str, Any]) -> OwnerQuestionAnswerMemoryRef:
    return OwnerQuestionAnswerMemoryRef(
        source_id=_required_text(raw.get("source_id"), "answer_memory_refs.source_id"),
        path=_required_text(raw.get("path"), "answer_memory_refs.path"),
        locator=_required_text(raw.get("locator"), "answer_memory_refs.locator"),
        created_at=_parse_dt(
            _required_text(raw.get("created_at"), "answer_memory_refs.created_at")
        ),
    )


def _clean_metadata(raw: Mapping[str, Any]) -> Mapping[str, str]:
    return {
        str(key): str(value)
        for key, value in raw.items()
        if str(key).strip() and str(value).strip()
    }


def _clean_optional_reason(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = re.sub(r"[^A-Za-z0-9_.:-]+", "-", value.strip()).strip("-")
    return cleaned or None


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise OwnerQuestionQueueError("{} must be a string".format(field_name))
    cleaned = value.strip()
    if not cleaned:
        raise OwnerQuestionQueueError("{} must not be empty".format(field_name))
    return cleaned


def _format_dt(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _format_optional_dt(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return _format_dt(value)


def _parse_dt(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = "{}+00:00".format(normalized[:-1])
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_optional_dt(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    return _parse_dt(value)


def _coerce_datetime(value: Optional[datetime]) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _coerce_optional_datetime(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return _coerce_datetime(value)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
