"""Assistant identity profile, direct self-introduction, and interview support."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from .chat import session_id_for_telegram
from .models import AssistantIdentity, TelegramTask


ASSISTANT_IDENTITY_SCHEMA_VERSION = 1
ASSISTANT_IDENTITY_INTERVIEW_SCHEMA_VERSION = 1

_STRING_FIELDS = {
    "name",
    "short_description",
    "mission",
    "relationship_to_owner",
}
_LIST_FIELDS = {
    "core_values",
    "communication_principles",
    "boundaries",
    "transparency_rules",
    "proactivity",
    "owner_special_treatment",
}
_META_FIELDS = {"schema_version", "identity_path"}
_ALLOWED_FIELDS = _STRING_FIELDS | _LIST_FIELDS | _META_FIELDS
_FORBIDDEN_FIELDS = {
    "api_key",
    "bot_token",
    "password",
    "secret",
    "telegram_bot_token",
    "token",
    "VERA_TELEGRAM_BOT_TOKEN",
}
_OVERCLAIM_PATTERNS = (
    re.compile(r"\b(?:i am|i'm|assistant is|vera is)\s+(?:a\s+)?human\b", re.IGNORECASE),
    re.compile(r"\b(?:i am|i'm|assistant is|vera is)\s+(?:a\s+)?(?:sentient|conscious)\b", re.IGNORECASE),
    re.compile(r"\bnot\s+(?:powered by|using|running through)\s+(?:codex|openai)\b", re.IGNORECASE),
)


class AssistantIdentityConfigError(ValueError):
    """Raised when assistant identity configuration is invalid."""


class AssistantIdentityStateError(RuntimeError):
    """Raised when assistant identity interview/profile state cannot be loaded."""


@dataclass(frozen=True)
class AssistantIdentityQuestion:
    key: str
    label: str
    prompt: str


ASSISTANT_IDENTITY_QUESTIONS: Tuple[AssistantIdentityQuestion, ...] = (
    AssistantIdentityQuestion(
        key="name",
        label="Assistant name",
        prompt="Assistant identity 1/10: What should this assistant be called?",
    ),
    AssistantIdentityQuestion(
        key="short_description",
        label="Short self-description",
        prompt="2/10: In one short sentence, what kind of assistant is this?",
    ),
    AssistantIdentityQuestion(
        key="mission",
        label="Mission",
        prompt="3/10: What is this assistant's mission?",
    ),
    AssistantIdentityQuestion(
        key="core_values",
        label="Core values",
        prompt="4/10: What core values should guide the assistant? Use semicolons for multiple values.",
    ),
    AssistantIdentityQuestion(
        key="communication_principles",
        label="Communication principles",
        prompt="5/10: How should the assistant communicate by default?",
    ),
    AssistantIdentityQuestion(
        key="boundaries",
        label="Boundaries",
        prompt="6/10: What boundaries should the assistant never cross?",
    ),
    AssistantIdentityQuestion(
        key="relationship_to_owner",
        label="Relationship to owner",
        prompt="7/10: What is the assistant's relationship to the owner/human user?",
    ),
    AssistantIdentityQuestion(
        key="proactivity",
        label="Proactivity",
        prompt="8/10: When should the assistant be proactive, and when should it stay quiet?",
    ),
    AssistantIdentityQuestion(
        key="owner_special_treatment",
        label="Owner-specific treatment",
        prompt="9/10: How should the assistant treat the owner as special compared with other Telegram users?",
    ),
    AssistantIdentityQuestion(
        key="transparency_rules",
        label="Transparency rules",
        prompt=(
            "10/10: What should the assistant say about being Vera/minime "
            "and powered by Codex/OpenAI?"
        ),
    ),
)


@dataclass(frozen=True)
class AssistantIdentityInterviewSession:
    session_id: str
    status: str = "collecting"
    step_index: int = 0
    answers: Mapping[str, str] = field(default_factory=dict)
    message_ids: Tuple[int, ...] = ()
    transcript: Tuple[Mapping[str, object], ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class JsonAssistantIdentityStore:
    """JSON store for the active assistant identity profile."""

    def __init__(self, path: Path, default_identity: AssistantIdentity) -> None:
        self._path = path
        self._default_identity = default_identity

    @property
    def path(self) -> Path:
        return self._path

    def current(self) -> AssistantIdentity:
        if not self._path.exists():
            return self._default_identity
        try:
            return load_assistant_identity_file(self._path, base=self._default_identity)
        except AssistantIdentityConfigError as exc:
            raise AssistantIdentityStateError(str(exc))

    def save(self, identity: AssistantIdentity) -> AssistantIdentity:
        _write_json_atomic(self._path, assistant_identity_to_json(identity))
        return identity

    def format_for_chat(self) -> str:
        identity = self.current()
        lines = [
            "Assistant identity profile:",
            "- Name: {}".format(identity.safe_display_name),
            "- Short self-description: {}".format(identity.short_description),
            "- Mission: {}".format(identity.mission),
            "- Relationship to owner: {}".format(identity.relationship_to_owner),
        ]
        lines.extend("- Core value: {}".format(item) for item in identity.core_values)
        lines.extend(
            "- Communication principle: {}".format(item)
            for item in identity.communication_principles
        )
        lines.extend("- Boundary: {}".format(item) for item in identity.boundaries)
        lines.extend(
            "- Transparency rule: {}".format(item)
            for item in identity.transparency_rules
        )
        lines.extend("- Proactivity: {}".format(item) for item in identity.proactivity)
        lines.extend(
            "- Owner-specific treatment: {}".format(item)
            for item in identity.owner_special_treatment
        )
        return "\n".join(lines)


class JsonAssistantIdentityInterviewStore:
    """JSON store for active assistant identity interview state."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def session_by_id(self, session_id: str) -> Optional[AssistantIdentityInterviewSession]:
        raw = self._load().get("sessions", {}).get(session_id)
        if not isinstance(raw, Mapping):
            return None
        return _interview_session_from_json(raw)

    def save(
        self,
        session: AssistantIdentityInterviewSession,
    ) -> AssistantIdentityInterviewSession:
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
            return {
                "schema_version": ASSISTANT_IDENTITY_INTERVIEW_SCHEMA_VERSION,
                "sessions": {},
            }
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise AssistantIdentityStateError(
                "assistant identity interview file is not valid JSON: {}".format(exc)
            )
        if not isinstance(raw, dict):
            raise AssistantIdentityStateError(
                "assistant identity interview file must contain a JSON object"
            )
        if "sessions" not in raw:
            raw["sessions"] = {}
        return raw


class AssistantIdentityController:
    """Routes Telegram messages into assistant identity and interview flows."""

    def __init__(
        self,
        identity_store: JsonAssistantIdentityStore,
        interview_store: JsonAssistantIdentityInterviewStore,
    ) -> None:
        self._identity_store = identity_store
        self._interview_store = interview_store

    def active_identity(self) -> AssistantIdentity:
        return self._identity_store.current()

    def handle(self, task: TelegramTask, allow_profile_update: bool) -> Optional[str]:
        session_id = session_id_for_telegram(task.chat_id, task.user_id)
        text = task.text.strip()
        normalized = _normalize(text)
        identity = self.active_identity()

        if _is_self_identity_question(normalized):
            return identity.introduction(include_runtime=_asks_about_runtime(normalized))

        if not allow_profile_update:
            return None

        session = self._interview_store.session_by_id(session_id)
        if session is not None and session.status in {"collecting", "awaiting_confirmation"}:
            return self._handle_active_interview(session, task)

        if _is_profile_inspect(normalized):
            return self._identity_store.format_for_chat()
        if _is_start_trigger(normalized):
            return self._start_interview(session_id, task)
        return None

    def _start_interview(self, session_id: str, task: TelegramTask) -> str:
        question = ASSISTANT_IDENTITY_QUESTIONS[0]
        session = AssistantIdentityInterviewSession(
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
        session: AssistantIdentityInterviewSession,
        task: TelegramTask,
    ) -> str:
        normalized = _normalize(task.text)
        if normalized in {"cancel", "/cancel", "stop", "cancel assistant identity"}:
            response = "Assistant identity interview cancelled. I did not write profile changes."
            self._interview_store.save(
                replace(
                    _append_transcript(session, task, response),
                    status="cancelled",
                )
            )
            return response

        if session.status == "awaiting_confirmation":
            if normalized in {"confirm", "save", "yes", "yes save", "looks good", "confirmed"}:
                identity = _identity_from_answers(session.answers, base=self.active_identity())
                self._identity_store.save(identity)
                response = (
                    "Saved assistant identity for {}. Inspect it with /assistant identity profile."
                ).format(identity.safe_display_name)
                self._interview_store.save(
                    replace(
                        _append_transcript(session, task, response),
                        status="completed",
                    )
                )
                return response
            response = "Reply `confirm` to save this assistant identity, or `cancel` to discard it."
            self._interview_store.save(_append_transcript(session, task, response))
            return response

        answer = task.text.strip()
        if not answer:
            response = "Please answer in a short message, or say cancel."
            self._interview_store.save(_append_transcript(session, task, response))
            return response

        question = ASSISTANT_IDENTITY_QUESTIONS[session.step_index]
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
        if next_step < len(ASSISTANT_IDENTITY_QUESTIONS):
            response = ASSISTANT_IDENTITY_QUESTIONS[next_step].prompt
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


def assistant_identity_from_mapping(
    raw: Mapping[str, Any],
    base: Optional[AssistantIdentity] = None,
    source_name: str = "assistant identity",
) -> AssistantIdentity:
    if not isinstance(raw, Mapping):
        raise AssistantIdentityConfigError("{} must be a JSON object".format(source_name))
    present_forbidden = sorted(_FORBIDDEN_FIELDS.intersection(raw.keys()))
    if present_forbidden:
        raise AssistantIdentityConfigError(
            "{} must not contain secret fields: {}".format(
                source_name,
                ", ".join(present_forbidden),
            )
        )
    unknown = sorted(set(raw.keys()) - _ALLOWED_FIELDS)
    if unknown:
        raise AssistantIdentityConfigError(
            "{} contains unknown fields: {}".format(source_name, ", ".join(unknown))
        )

    identity = base or AssistantIdentity.default()
    values: Dict[str, Any] = {
        "name": identity.name,
        "short_description": identity.short_description,
        "mission": identity.mission,
        "core_values": identity.core_values,
        "communication_principles": identity.communication_principles,
        "boundaries": identity.boundaries,
        "transparency_rules": identity.transparency_rules,
        "relationship_to_owner": identity.relationship_to_owner,
        "proactivity": identity.proactivity,
        "owner_special_treatment": identity.owner_special_treatment,
    }
    for key in _STRING_FIELDS:
        if key in raw:
            parsed = _parse_optional_string(raw.get(key), "{}.{}".format(source_name, key))
            if parsed is not None:
                values[key] = parsed
    for key in _LIST_FIELDS:
        if key in raw:
            values[key] = _parse_string_tuple(raw.get(key), "{}.{}".format(source_name, key))
    updated = AssistantIdentity(**values)
    _validate_product_truth(updated, source_name)
    return updated


def load_assistant_identity_file(
    path: Path,
    base: Optional[AssistantIdentity] = None,
) -> AssistantIdentity:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise AssistantIdentityConfigError(
            "assistant identity file cannot be read: {}".format(exc)
        )
    except json.JSONDecodeError as exc:
        raise AssistantIdentityConfigError(
            "assistant identity file is not valid JSON: {}".format(exc)
        )
    return assistant_identity_from_mapping(raw, base=base, source_name=str(path))


def assistant_identity_to_json(identity: AssistantIdentity) -> Dict[str, object]:
    return {
        "schema_version": ASSISTANT_IDENTITY_SCHEMA_VERSION,
        "name": identity.safe_display_name,
        "short_description": identity.short_description,
        "mission": identity.mission,
        "core_values": list(identity.core_values),
        "communication_principles": list(identity.communication_principles),
        "boundaries": list(identity.boundaries),
        "transparency_rules": list(identity.transparency_rules),
        "relationship_to_owner": identity.relationship_to_owner,
        "proactivity": list(identity.proactivity),
        "owner_special_treatment": list(identity.owner_special_treatment),
    }


def _identity_from_answers(
    answers: Mapping[str, str],
    base: AssistantIdentity,
) -> AssistantIdentity:
    raw: Dict[str, object] = {}
    for question in ASSISTANT_IDENTITY_QUESTIONS:
        value = str(answers.get(question.key, "")).strip()
        if not value:
            continue
        if question.key in _LIST_FIELDS:
            raw[question.key] = _split_guidance(value)
        else:
            raw[question.key] = value
    return assistant_identity_from_mapping(raw, base=base, source_name="assistant identity interview")


def _summary_for_answers(answers: Mapping[str, str]) -> str:
    lines = ["Here is the assistant identity profile I would save:"]
    for question in ASSISTANT_IDENTITY_QUESTIONS:
        value = str(answers.get(question.key, "")).strip()
        if value:
            lines.append("- {}: {}".format(question.label, value))
    lines.extend(
        [
            "",
            "I will treat this as configurable product identity, not a human personality claim.",
            "Reply `confirm` to save it, or `cancel` to discard it.",
        ]
    )
    return "\n".join(lines)


def _append_transcript(
    session: AssistantIdentityInterviewSession,
    task: TelegramTask,
    assistant_text: str,
) -> AssistantIdentityInterviewSession:
    return replace(
        session,
        transcript=tuple(session.transcript)
        + (
            _transcript("user", task.text, task.message_id),
            _transcript("assistant", assistant_text, None),
        ),
    )


def _transcript(role: str, text: str, message_id: Optional[int]) -> Mapping[str, object]:
    return {
        "role": role,
        "text": text,
        "message_id": message_id,
        "created_at": _utcnow().isoformat(),
    }


def _is_self_identity_question(normalized: str) -> bool:
    normalized = normalized.strip()
    if normalized in {
        "who are you",
        "what are you",
        "introduce yourself",
        "tell me who you are",
        "tell me about yourself",
        "are you codex",
        "are you vera",
        "what is your runtime",
        "what powers you",
    }:
        return True
    if normalized.startswith("who are you ") or normalized.startswith("what are you "):
        return True
    return False


def _asks_about_runtime(normalized: str) -> bool:
    return any(
        word in normalized
        for word in ("codex", "openai", "runtime", "powered", "model", "tooling")
    )


def _is_start_trigger(normalized: str) -> bool:
    return normalized in {
        "/assistant identity",
        "/assistant interview",
        "/assistant profile edit",
        "assistant identity interview",
        "configure assistant identity",
    }


def _is_profile_inspect(normalized: str) -> bool:
    return normalized in {
        "/assistant",
        "/assistant profile",
        "/assistant identity profile",
        "/assistant identity show",
        "show assistant identity",
        "show vera identity",
    }


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9/@._ -]+", "", text.casefold()).strip()


def _split_guidance(value: str) -> Tuple[str, ...]:
    parts: Iterable[str]
    if "\n" in value:
        parts = value.splitlines()
    else:
        parts = re.split(r";+", value)
    parsed = tuple(part.strip(" -\t\r\n") for part in parts if part.strip(" -\t\r\n"))
    return parsed or (value.strip(),)


def _parse_optional_string(value: Any, field_name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AssistantIdentityConfigError("{} must be a string or null".format(field_name))
    stripped = value.strip()
    return stripped or None


def _parse_string_tuple(value: Any, field_name: str) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if not isinstance(value, (list, tuple)):
        raise AssistantIdentityConfigError(
            "{} must be a string or an array of strings".format(field_name)
        )
    parsed = []
    for item in value:
        if not isinstance(item, str):
            raise AssistantIdentityConfigError("{} must contain only strings".format(field_name))
        text = item.strip()
        if text:
            parsed.append(text)
    return tuple(parsed)


def _validate_product_truth(identity: AssistantIdentity, source_name: str) -> None:
    text = "\n".join(
        (
            identity.name,
            identity.short_description,
            identity.mission,
            identity.relationship_to_owner,
            "\n".join(identity.core_values),
            "\n".join(identity.communication_principles),
            "\n".join(identity.boundaries),
            "\n".join(identity.transparency_rules),
            "\n".join(identity.proactivity),
            "\n".join(identity.owner_special_treatment),
        )
    )
    for pattern in _OVERCLAIM_PATTERNS:
        if pattern.search(text):
            raise AssistantIdentityConfigError(
                "{} must not configure the assistant to claim human, sentient, or runtime-independent status".format(
                    source_name
                )
            )


def _interview_session_to_json(session: AssistantIdentityInterviewSession) -> Dict[str, Any]:
    return {
        "session_id": session.session_id,
        "status": session.status,
        "step_index": session.step_index,
        "answers": dict(session.answers),
        "message_ids": list(session.message_ids),
        "transcript": list(session.transcript),
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
    }


def _interview_session_from_json(raw: Mapping[str, Any]) -> AssistantIdentityInterviewSession:
    answers = raw.get("answers")
    if not isinstance(answers, Mapping):
        answers = {}
    transcript = raw.get("transcript")
    if not isinstance(transcript, list):
        transcript = []
    return AssistantIdentityInterviewSession(
        session_id=_required_string(raw, "session_id"),
        status=_optional_string(raw.get("status")) or "collecting",
        step_index=_optional_int(raw.get("step_index")),
        answers={str(key): str(value) for key, value in answers.items()},
        message_ids=_int_tuple(raw.get("message_ids")),
        transcript=tuple(item for item in transcript if isinstance(item, Mapping)),
        created_at=_optional_datetime(raw.get("created_at")),
        updated_at=_optional_datetime(raw.get("updated_at")),
    )


def _required_string(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise AssistantIdentityStateError(
            "assistant identity interview state is missing required string field: {}".format(key)
        )
    return value


def _optional_string(value: Any) -> Optional[str]:
    if isinstance(value, str) and value:
        return value
    return None


def _optional_int(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _int_tuple(value: Any) -> Tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, int) and item >= 0)


def _optional_datetime(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return _utcnow()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name("{}.tmp".format(path.name))
    temp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)
