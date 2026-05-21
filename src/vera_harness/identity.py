"""Owner identity and communication-style interview support."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple
from uuid import uuid4

from .chat import session_id_for_telegram
from .models import AssistantIdentity, TelegramTask


PROFILE_SCHEMA_VERSION = 1
INTERVIEW_SCHEMA_VERSION = 1
CONFIDENCE_CONFIRMED_INTERVIEW = 0.86
CONFIDENCE_CORRECTION = 0.92
CORRECTION_PATH = (
    "Tell Vera: `that's wrong`, `forget that`, or `change my <preference>`."
)


class IdentityStateError(RuntimeError):
    """Raised when identity interview/profile state cannot be loaded or written."""


@dataclass(frozen=True)
class IdentityQuestion:
    """One mobile-sized interview question."""

    key: str
    label: str
    prompt: str


QUESTIONS: Tuple[IdentityQuestion, ...] = (
    IdentityQuestion(
        key="address_name",
        label="Name/address preference",
        prompt=(
            "Identity interview 1/7: What should I call you? "
            "Include any name or form of address I should avoid."
        ),
    ),
    IdentityQuestion(
        key="helpfulness",
        label="What helpful means",
        prompt="2/7: When I am helping well, what am I optimizing for?",
    ),
    IdentityQuestion(
        key="tone_detail",
        label="Tone and detail",
        prompt="3/7: What tone and level of detail do you prefer by default?",
    ),
    IdentityQuestion(
        key="challenge_style",
        label="Challenge and disagreement",
        prompt=(
            "4/7: How should I challenge you, disagree, or slow you down "
            "when I see risk or unclear reasoning?"
        ),
    ),
    IdentityQuestion(
        key="values_priorities",
        label="Values and priorities",
        prompt=(
            "5/7: What values or priorities should guide decisions when "
            "tradeoffs are unclear?"
        ),
    ),
    IdentityQuestion(
        key="sensitive_topics",
        label="Topics needing extra care",
        prompt=(
            "6/7: What topics, situations, or behaviors require extra care "
            "from me?"
        ),
    ),
    IdentityQuestion(
        key="persistence_boundaries",
        label="Memory boundaries",
        prompt=(
            "7/7: What should I remember long-term, and what should I avoid "
            "persisting?"
        ),
    ),
)

QUESTION_BY_KEY = {question.key: question for question in QUESTIONS}


@dataclass(frozen=True)
class IdentityProfileEntry:
    """A confirmed durable owner-profile/user-wiki fact."""

    entry_id: str
    category: str
    label: str
    value: str
    source: str
    source_session_id: str
    source_message_ids: Tuple[int, ...]
    created_at: datetime
    confidence: float
    correction_path: str = CORRECTION_PATH
    status: str = "active"
    correction_of: Tuple[str, ...] = ()
    archived_at: Optional[datetime] = None
    corrected_by: Optional[str] = None


@dataclass(frozen=True)
class TranscriptItem:
    """A raw interview turn kept outside the durable profile store."""

    role: str
    text: str
    message_id: Optional[int]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class IdentityInterviewSession:
    """A persisted identity interview state machine for one Telegram session."""

    session_id: str
    status: str = "collecting"
    step_index: int = 0
    answers: Mapping[str, str] = field(default_factory=dict)
    message_ids: Tuple[int, ...] = ()
    transcript: Tuple[TranscriptItem, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class JsonIdentityProfileStore:
    """JSON store for confirmed owner identity/style profile entries."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def active_entries(self) -> Tuple[IdentityProfileEntry, ...]:
        return tuple(entry for entry in self.entries() if entry.status == "active")

    def entries(self) -> Tuple[IdentityProfileEntry, ...]:
        raw_entries = self._load().get("entries", [])
        if not isinstance(raw_entries, list):
            raise IdentityStateError("identity profile entries must be a list")
        return tuple(
            _profile_entry_from_json(item)
            for item in raw_entries
            if isinstance(item, Mapping)
        )

    def append_entries(
        self,
        entries: Iterable[IdentityProfileEntry],
        archive_prior_categories: bool = False,
    ) -> Tuple[IdentityProfileEntry, ...]:
        new_entries = tuple(entries)
        all_entries = list(self.entries())
        if archive_prior_categories:
            replacement_by_category = {entry.category: entry for entry in new_entries}
            all_entries = [
                replace(
                    entry,
                    status="archived",
                    archived_at=replacement_by_category[entry.category].created_at,
                    corrected_by=replacement_by_category[entry.category].entry_id,
                )
                if entry.status == "active" and entry.category in replacement_by_category
                else entry
                for entry in all_entries
            ]
        all_entries.extend(new_entries)
        self._write_entries(tuple(all_entries))
        return tuple(all_entries)

    def archive_entries(
        self,
        entry_ids: Iterable[str],
        corrected_by: Optional[str] = None,
    ) -> Tuple[IdentityProfileEntry, ...]:
        targets = set(entry_ids)
        archived_at = _utcnow()
        updated = []
        for entry in self.entries():
            if entry.entry_id in targets and entry.status == "active":
                updated.append(
                    replace(
                        entry,
                        status="archived",
                        archived_at=archived_at,
                        corrected_by=corrected_by,
                    )
                )
            else:
                updated.append(entry)
        self._write_entries(tuple(updated))
        return tuple(updated)

    def replace_category(
        self,
        category: str,
        value: str,
        source_session_id: str,
        source_message_ids: Tuple[int, ...],
        source: str = "telegram_identity_correction",
    ) -> IdentityProfileEntry:
        prior = tuple(
            entry
            for entry in self.active_entries()
            if entry.category == category
        )
        question = QUESTION_BY_KEY.get(category)
        label = question.label if question is not None else _display_category(category)
        new_entry = _new_profile_entry(
            category=category,
            label=label,
            value=value,
            source=source,
            source_session_id=source_session_id,
            source_message_ids=source_message_ids,
            confidence=CONFIDENCE_CORRECTION,
            correction_of=tuple(entry.entry_id for entry in prior),
        )
        entries = list(self.entries())
        if prior:
            prior_ids = {entry.entry_id for entry in prior}
            entries = [
                replace(
                    entry,
                    status="archived",
                    archived_at=new_entry.created_at,
                    corrected_by=new_entry.entry_id,
                )
                if entry.entry_id in prior_ids
                else entry
                for entry in entries
            ]
        entries.append(new_entry)
        self._write_entries(tuple(entries))
        return new_entry

    def prompt_lines(self) -> Tuple[str, ...]:
        entries = self.active_entries()
        if not entries:
            return ()
        lines = [
            (
                "Confirmed owner identity/style profile: use these as practical "
                "guidance, not flattery or fixed personality claims."
            )
        ]
        lines.extend(
            "{}: {} (source: {}; confidence: {:.2f})".format(
                entry.label,
                entry.value,
                entry.source,
                entry.confidence,
            )
            for entry in entries
        )
        lines.append(
            "Prefer explicit owner corrections over this profile when they conflict."
        )
        return tuple(lines)

    def format_for_chat(self) -> str:
        entries = self.active_entries()
        if not entries:
            return (
                "I do not have confirmed identity/style facts yet. "
                "Start with /identity or /interview."
            )
        lines = ["Confirmed identity/style facts:"]
        for index, entry in enumerate(entries, start=1):
            lines.append(
                "{}. {}: {} [source: {}; confidence: {:.2f}]".format(
                    index,
                    entry.label,
                    entry.value,
                    entry.source,
                    entry.confidence,
                )
            )
        lines.append(CORRECTION_PATH)
        return "\n".join(lines)

    def _load(self) -> Dict[str, Any]:
        if not self._path.exists():
            return {"schema_version": PROFILE_SCHEMA_VERSION, "entries": []}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise IdentityStateError("identity profile file is not valid JSON: {}".format(exc))
        if not isinstance(raw, dict):
            raise IdentityStateError("identity profile file must contain a JSON object")
        if "entries" not in raw:
            raw["entries"] = []
        return raw

    def _write_entries(self, entries: Tuple[IdentityProfileEntry, ...]) -> None:
        payload = {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "entries": [_profile_entry_to_json(entry) for entry in entries],
        }
        _write_json_atomic(self._path, payload)


class JsonIdentityInterviewStore:
    """JSON store for active interview state and raw interview transcript."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def session_by_id(self, session_id: str) -> Optional[IdentityInterviewSession]:
        raw = self._load().get("sessions", {}).get(session_id)
        if not isinstance(raw, Mapping):
            return None
        return _interview_session_from_json(raw)

    def save(self, session: IdentityInterviewSession) -> IdentityInterviewSession:
        updated = replace(session, updated_at=_utcnow())
        payload = self._load()
        sessions = payload.setdefault("sessions", {})
        if not isinstance(sessions, dict):
            sessions = {}
            payload["sessions"] = sessions
        sessions[updated.session_id] = _interview_session_to_json(updated)
        _write_json_atomic(self._path, payload)
        return updated

    def _load(self) -> Dict[str, Any]:
        if not self._path.exists():
            return {"schema_version": INTERVIEW_SCHEMA_VERSION, "sessions": {}}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise IdentityStateError("identity interview file is not valid JSON: {}".format(exc))
        if not isinstance(raw, dict):
            raise IdentityStateError("identity interview file must contain a JSON object")
        if "sessions" not in raw:
            raw["sessions"] = {}
        return raw


class IdentityInterviewController:
    """Routes Telegram messages into identity interview/profile flows."""

    def __init__(
        self,
        profile_store: JsonIdentityProfileStore,
        interview_store: JsonIdentityInterviewStore,
    ) -> None:
        self._profile_store = profile_store
        self._interview_store = interview_store

    def profile_prompt_lines(self) -> Tuple[str, ...]:
        return self._profile_store.prompt_lines()

    def handle(self, task: TelegramTask) -> Optional[str]:
        session_id = session_id_for_telegram(task.chat_id, task.user_id)
        text = task.text.strip()
        normalized = _normalize(text)
        session = self._interview_store.session_by_id(session_id)
        if session is not None and session.status in {"collecting", "awaiting_confirmation"}:
            return self._handle_active_interview(session, task)

        if _is_profile_inspect(normalized):
            return self._profile_store.format_for_chat()
        correction = self._handle_profile_correction(normalized, text, session_id, task.message_id)
        if correction is not None:
            return correction
        if _is_start_trigger(normalized):
            return self._start_interview(session_id, task)
        return None

    def _start_interview(self, session_id: str, task: TelegramTask) -> str:
        question = QUESTIONS[0]
        session = IdentityInterviewSession(
            session_id=session_id,
            status="collecting",
            step_index=0,
            transcript=(
                _transcript("user", task.text, task.message_id),
                _transcript("assistant", question.prompt, None),
            ),
        )
        self._interview_store.save(session)
        return question.prompt

    def _handle_active_interview(
        self,
        session: IdentityInterviewSession,
        task: TelegramTask,
    ) -> str:
        normalized = _normalize(task.text)
        if _is_cancel(normalized):
            response = "Identity interview cancelled. I did not write profile changes."
            self._interview_store.save(
                replace(
                    _append_transcript(session, task, response),
                    status="cancelled",
                )
            )
            return response

        if session.status == "awaiting_confirmation":
            if _is_confirm(normalized):
                entries = _entries_from_answers(session, task.message_id)
                self._profile_store.append_entries(entries, archive_prior_categories=True)
                response = (
                    "Saved {} confirmed identity/style facts. "
                    "Inspect them with /identity profile. {}".format(
                        len(entries),
                        CORRECTION_PATH,
                    )
                )
                self._interview_store.save(
                    replace(
                        _append_transcript(session, task, response),
                        status="completed",
                    )
                )
                return response
            if _is_change_request(normalized):
                response = (
                    "Tell me the corrected preference as `change my <preference> to ...`, "
                    "or reply cancel to discard this interview."
                )
                self._interview_store.save(_append_transcript(session, task, response))
                return response
            response = "Reply `confirm` to save these profile facts, or `cancel` to discard them."
            self._interview_store.save(_append_transcript(session, task, response))
            return response

        if session.step_index >= len(QUESTIONS):
            response = _summary_for_answers(session.answers)
            self._interview_store.save(
                replace(
                    _append_transcript(session, task, response),
                    status="awaiting_confirmation",
                )
            )
            return response

        answer = task.text.strip()
        if not answer:
            response = "Please answer in a short message, or say cancel."
            self._interview_store.save(_append_transcript(session, task, response))
            return response

        question = QUESTIONS[session.step_index]
        answers = dict(session.answers)
        answers[question.key] = answer
        message_ids = tuple(session.message_ids) + (task.message_id,)
        next_step = session.step_index + 1
        updated = replace(
            session,
            answers=answers,
            message_ids=message_ids,
            step_index=next_step,
        )
        if next_step < len(QUESTIONS):
            response = QUESTIONS[next_step].prompt
            self._interview_store.save(_append_transcript(updated, task, response))
            return response

        response = _summary_for_answers(answers)
        self._interview_store.save(
            replace(
                _append_transcript(updated, task, response),
                status="awaiting_confirmation",
            )
        )
        return response

    def _handle_profile_correction(
        self,
        normalized: str,
        text: str,
        session_id: str,
        message_id: int,
    ) -> Optional[str]:
        active = self._profile_store.active_entries()
        if normalized in {"thats wrong", "that is wrong", "that's wrong"}:
            if not active:
                return "I do not have confirmed identity/style facts to correct yet."
            return (
                "Which fact should I correct or forget? Use `/identity profile`, "
                "`/identity change <number> to ...`, or `/identity forget <number>`."
            )

        forget_target = _forget_target(normalized)
        if forget_target is not None:
            return self._forget_entries(forget_target, active)

        change = _change_request(normalized, text)
        if change is None:
            return None
        category, value = change
        if category.startswith("__number__:"):
            matches = _matching_entries(category, active)
            if not matches:
                return "I could not find that identity/style fact number. Use `/identity profile` to inspect them."
            category = matches[0].category
        if not value:
            return "Tell me the new value after `to`, or say cancel."
        entry = self._profile_store.replace_category(
            category=category,
            value=value,
            source_session_id=session_id,
            source_message_ids=(message_id,),
        )
        return "Updated {}: {}. {}".format(entry.label, entry.value, CORRECTION_PATH)

    def _forget_entries(
        self,
        target: str,
        active: Tuple[IdentityProfileEntry, ...],
    ) -> str:
        if not active:
            return "I do not have confirmed identity/style facts to forget yet."
        matches = _matching_entries(target, active)
        if not matches:
            return "I could not find a matching identity/style fact. Use `/identity profile` to inspect them."
        self._profile_store.archive_entries(entry.entry_id for entry in matches)
        if len(matches) == 1:
            return "Forgot {}: {}.".format(matches[0].label, matches[0].value)
        return "Forgot {} matching identity/style facts.".format(len(matches))


def render_chat_prompt_with_profile(
    user_message: str,
    owner_profile: Tuple[str, ...],
    assistant_identity: Optional[AssistantIdentity] = None,
) -> str:
    """Wrap a follow-up chat message with assistant identity and owner guidance."""

    if assistant_identity is None and not owner_profile:
        return user_message
    lines = []
    if assistant_identity is not None:
        lines.extend(assistant_identity.prompt_lines())
    if owner_profile:
        if lines:
            lines.append("")
        lines.append("Owner profile guidance for this turn:")
        lines.extend(owner_profile)
    lines.extend(["", "Telegram message:", user_message])
    return "\n".join(lines)


def _entries_from_answers(
    session: IdentityInterviewSession,
    confirmation_message_id: int,
) -> Tuple[IdentityProfileEntry, ...]:
    entries = []
    message_ids = tuple(session.message_ids) + (confirmation_message_id,)
    for question in QUESTIONS:
        value = str(session.answers.get(question.key, "")).strip()
        if not value:
            continue
        entries.append(
            _new_profile_entry(
                category=question.key,
                label=question.label,
                value=value,
                source="telegram_identity_interview",
                source_session_id=session.session_id,
                source_message_ids=message_ids,
                confidence=CONFIDENCE_CONFIRMED_INTERVIEW,
            )
        )
    return tuple(entries)


def _new_profile_entry(
    category: str,
    label: str,
    value: str,
    source: str,
    source_session_id: str,
    source_message_ids: Tuple[int, ...],
    confidence: float,
    correction_of: Tuple[str, ...] = (),
) -> IdentityProfileEntry:
    return IdentityProfileEntry(
        entry_id="identity-{}-{}".format(category, uuid4().hex[:12]),
        category=category,
        label=label,
        value=value.strip(),
        source=source,
        source_session_id=source_session_id,
        source_message_ids=source_message_ids,
        created_at=_utcnow(),
        confidence=confidence,
        correction_of=correction_of,
    )


def _summary_for_answers(answers: Mapping[str, str]) -> str:
    lines = [
        "Here is what I would save as practical identity/style guidance:",
    ]
    for question in QUESTIONS:
        value = str(answers.get(question.key, "")).strip()
        if value:
            lines.append("- {}: {}".format(question.label, value))
    lines.extend(
        [
            "",
            "I will treat this as revisable guidance, not a personality label.",
            "Reply `confirm` to save it, or `cancel` to discard it.",
        ]
    )
    return "\n".join(lines)


def _append_transcript(
    session: IdentityInterviewSession,
    task: TelegramTask,
    assistant_text: str,
) -> IdentityInterviewSession:
    return replace(
        session,
        transcript=tuple(session.transcript)
        + (
            _transcript("user", task.text, task.message_id),
            _transcript("assistant", assistant_text, None),
        ),
    )


def _transcript(role: str, text: str, message_id: Optional[int]) -> TranscriptItem:
    return TranscriptItem(role=role, text=text, message_id=message_id)


def _is_start_trigger(normalized: str) -> bool:
    if normalized in {"/identity", "/interview", "identity", "interview"}:
        return True
    if "identity" in normalized and "interview" in normalized:
        return True
    if "style" in normalized and "interview" in normalized:
        return True
    return "interview" in normalized and "values" in normalized


def _is_profile_inspect(normalized: str) -> bool:
    return normalized in {
        "/identity profile",
        "/identity show",
        "/identity inspect",
        "show my identity profile",
        "show my style profile",
        "what do you remember about my style",
        "what do you remember about my identity",
    }


def _is_cancel(normalized: str) -> bool:
    return normalized in {"cancel", "/cancel", "stop", "stop interview", "cancel interview"}


def _is_confirm(normalized: str) -> bool:
    return normalized in {"confirm", "save", "yes", "yes save", "looks good", "confirmed"}


def _is_change_request(normalized: str) -> bool:
    return normalized in {"change", "edit", "that's wrong", "thats wrong", "that is wrong"}


def _forget_target(normalized: str) -> Optional[str]:
    if normalized == "forget that":
        return "latest"
    match = re.match(r"^/identity forget(?:\s+(.+))?$", normalized)
    if match:
        return (match.group(1) or "latest").strip()
    if normalized.startswith("forget my "):
        return normalized[len("forget my ") :].strip()
    return None


def _change_request(normalized: str, original_text: str) -> Optional[Tuple[str, str]]:
    numbered = re.match(r"^/identity change\s+(\d+)\s+to\s+(.+)$", original_text.strip(), re.IGNORECASE)
    if numbered:
        category = "__number__:{}".format(numbered.group(1))
        return category, numbered.group(2).strip()

    match = re.match(r"^(?:/identity\s+)?change my (.+?) to (.+)$", original_text.strip(), re.IGNORECASE)
    if not match:
        return None
    subject = _normalize(match.group(1))
    category = _category_from_subject(subject)
    if category is None:
        return None
    return category, match.group(2).strip()


def _category_from_subject(subject: str) -> Optional[str]:
    if "name" in subject or "call" in subject or "address" in subject:
        return "address_name"
    if "help" in subject:
        return "helpfulness"
    if "style" in subject or "tone" in subject or "detail" in subject:
        return "tone_detail"
    if "challenge" in subject or "disagree" in subject or "slow" in subject:
        return "challenge_style"
    if "value" in subject or "priorit" in subject:
        return "values_priorities"
    if "care" in subject or "sensitive" in subject or "topic" in subject:
        return "sensitive_topics"
    if "remember" in subject or "persist" in subject or "memory" in subject:
        return "persistence_boundaries"
    return None


def _matching_entries(
    target: str,
    active: Tuple[IdentityProfileEntry, ...],
) -> Tuple[IdentityProfileEntry, ...]:
    if target == "latest":
        return active[-1:]
    if target.isdigit():
        index = int(target)
        if 1 <= index <= len(active):
            return (active[index - 1],)
        return ()
    numbered_category = re.match(r"^__number__:(\d+)$", target)
    if numbered_category:
        index = int(numbered_category.group(1))
        if 1 <= index <= len(active):
            return (active[index - 1],)
        return ()
    target_category = _category_from_subject(target)
    if target_category is not None:
        return tuple(entry for entry in active if entry.category == target_category)
    words = set(target.split())
    if not words:
        return ()
    return tuple(
        entry
        for entry in active
        if words & set(_normalize(" ".join([entry.label, entry.value, entry.category])).split())
    )


def _profile_entry_to_json(entry: IdentityProfileEntry) -> Dict[str, Any]:
    return {
        "entry_id": entry.entry_id,
        "category": entry.category,
        "label": entry.label,
        "value": entry.value,
        "source": entry.source,
        "source_session_id": entry.source_session_id,
        "source_message_ids": list(entry.source_message_ids),
        "created_at": entry.created_at.isoformat(),
        "confidence": entry.confidence,
        "correction_path": entry.correction_path,
        "status": entry.status,
        "correction_of": list(entry.correction_of),
        "archived_at": entry.archived_at.isoformat() if entry.archived_at else None,
        "corrected_by": entry.corrected_by,
    }


def _profile_entry_from_json(raw: Mapping[str, Any]) -> IdentityProfileEntry:
    return IdentityProfileEntry(
        entry_id=_required_string(raw, "entry_id"),
        category=_required_string(raw, "category"),
        label=_required_string(raw, "label"),
        value=_required_string(raw, "value"),
        source=_required_string(raw, "source"),
        source_session_id=_required_string(raw, "source_session_id"),
        source_message_ids=tuple(
            item for item in raw.get("source_message_ids", []) if isinstance(item, int)
        ),
        created_at=_parse_datetime(raw.get("created_at")),
        confidence=_optional_float(raw.get("confidence"), CONFIDENCE_CONFIRMED_INTERVIEW),
        correction_path=_optional_string(raw.get("correction_path")) or CORRECTION_PATH,
        status=_optional_string(raw.get("status")) or "active",
        correction_of=tuple(
            item for item in raw.get("correction_of", []) if isinstance(item, str)
        ),
        archived_at=_parse_optional_datetime(raw.get("archived_at")),
        corrected_by=_optional_string(raw.get("corrected_by")),
    )


def _interview_session_to_json(session: IdentityInterviewSession) -> Dict[str, Any]:
    return {
        "session_id": session.session_id,
        "status": session.status,
        "step_index": session.step_index,
        "answers": dict(session.answers),
        "message_ids": list(session.message_ids),
        "transcript": [_transcript_to_json(item) for item in session.transcript],
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
    }


def _interview_session_from_json(raw: Mapping[str, Any]) -> IdentityInterviewSession:
    answers = raw.get("answers")
    transcript = raw.get("transcript")
    return IdentityInterviewSession(
        session_id=_required_string(raw, "session_id"),
        status=_optional_string(raw.get("status")) or "collecting",
        step_index=_optional_int(raw.get("step_index")),
        answers={str(key): str(value) for key, value in answers.items()} if isinstance(answers, Mapping) else {},
        message_ids=tuple(item for item in raw.get("message_ids", []) if isinstance(item, int)),
        transcript=tuple(
            _transcript_from_json(item)
            for item in transcript
            if isinstance(item, Mapping)
        )
        if isinstance(transcript, list)
        else (),
        created_at=_parse_datetime(raw.get("created_at")),
        updated_at=_parse_datetime(raw.get("updated_at")),
    )


def _transcript_to_json(item: TranscriptItem) -> Dict[str, Any]:
    return {
        "role": item.role,
        "text": item.text,
        "message_id": item.message_id,
        "created_at": item.created_at.isoformat(),
    }


def _transcript_from_json(raw: Mapping[str, Any]) -> TranscriptItem:
    message_id = raw.get("message_id")
    return TranscriptItem(
        role=_required_string(raw, "role"),
        text=_required_string(raw, "text"),
        message_id=message_id if isinstance(message_id, int) else None,
        created_at=_parse_datetime(raw.get("created_at")),
    )


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name("{}.tmp".format(path.name))
    temp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def _normalize(value: str) -> str:
    normalized = value.strip().lower()
    normalized = normalized.replace("`", "")
    normalized = normalized.replace("'", "")
    normalized = normalized.replace("’", "")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _display_category(category: str) -> str:
    return category.replace("_", " ").title()


def _required_string(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise IdentityStateError("identity state is missing required string field: {}".format(key))
    return value


def _optional_string(value: Any) -> Optional[str]:
    if isinstance(value, str) and value:
        return value
    return None


def _optional_int(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _optional_float(value: Any, default: float) -> float:
    if isinstance(value, (float, int)):
        return float(value)
    return default


def _parse_datetime(value: Any) -> datetime:
    parsed = _parse_optional_datetime(value)
    return parsed or _utcnow()


def _parse_optional_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
