"""Persistent Telegram chat session state for Vera."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from .models import TelegramTask


class ChatSessionStateError(RuntimeError):
    """Raised when persisted chat session state cannot be loaded or written."""


@dataclass(frozen=True)
class TelegramChatSession:
    """A durable mapping from a Telegram chat/user pair to one Codex thread."""

    session_id: str
    chat_id: int
    user_id: int
    username: Optional[str] = None
    workspace_path: Optional[str] = None
    thread_id: Optional[str] = None
    last_turn_id: Optional[str] = None
    turns_completed: int = 0
    last_status: str = "planned"
    last_assistant_response: Optional[str] = None
    pending_prompt: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class JsonTelegramChatSessionStore:
    """Small JSON store for restart-safe Telegram chat sessions."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def session_for_task(self, task: TelegramTask) -> Optional[TelegramChatSession]:
        return self.session_for_ids(
            chat_id=task.chat_id,
            user_id=task.user_id,
            bot_id=task.bot_id,
        )

    def session_for_ids(
        self,
        chat_id: int,
        user_id: int,
        bot_id: Optional[str] = None,
    ) -> Optional[TelegramChatSession]:
        return self.session_by_id(
            session_id_for_telegram(chat_id=chat_id, user_id=user_id, bot_id=bot_id)
        )

    def session_by_id(self, session_id: str) -> Optional[TelegramChatSession]:
        raw = self._load().get("sessions", {}).get(session_id)
        if not isinstance(raw, Mapping):
            return None
        return _session_from_json(raw)

    def all_sessions(self) -> Tuple[TelegramChatSession, ...]:
        sessions = self._load().get("sessions", {})
        if not isinstance(sessions, Mapping):
            return ()
        return tuple(
            _session_from_json(raw)
            for raw in sessions.values()
            if isinstance(raw, Mapping)
        )

    def get_or_create(self, task: TelegramTask) -> TelegramChatSession:
        existing = self.session_for_task(task)
        if existing is not None:
            if existing.username == task.username:
                return existing
            return self.save(replace(existing, username=task.username))
        session = TelegramChatSession(
            session_id=session_id_for_telegram(
                chat_id=task.chat_id,
                user_id=task.user_id,
                bot_id=task.bot_id,
            ),
            chat_id=task.chat_id,
            user_id=task.user_id,
            username=task.username,
        )
        return self.save(session)

    def save(self, session: TelegramChatSession) -> TelegramChatSession:
        updated = replace(session, updated_at=datetime.now(timezone.utc))
        payload = self._load()
        sessions = payload.setdefault("sessions", {})
        if not isinstance(sessions, dict):
            sessions = {}
            payload["sessions"] = sessions
        sessions[updated.session_id] = _session_to_json(updated)
        self._write(payload)
        return updated

    def _load(self) -> Dict[str, Any]:
        if not self._path.exists():
            return {"sessions": {}}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ChatSessionStateError("chat session state file is not valid JSON: {}".format(exc))
        if not isinstance(raw, dict):
            raise ChatSessionStateError("chat session state file must contain a JSON object")
        sessions = raw.get("sessions")
        if not isinstance(sessions, dict):
            raw["sessions"] = {}
        return raw

    def _write(self, payload: Mapping[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_name("{}.tmp".format(self._path.name))
        temp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self._path)


def session_id_for_telegram(
    chat_id: int,
    user_id: int,
    bot_id: Optional[str] = None,
) -> str:
    if bot_id:
        return _safe_session_id("telegram-bot-{}-chat-{}-user-{}".format(bot_id, chat_id, user_id))
    return _safe_session_id("telegram-chat-{}-user-{}".format(chat_id, user_id))


def _session_to_json(session: TelegramChatSession) -> Dict[str, Any]:
    return {
        "session_id": session.session_id,
        "chat_id": session.chat_id,
        "user_id": session.user_id,
        "username": session.username,
        "workspace_path": session.workspace_path,
        "thread_id": session.thread_id,
        "last_turn_id": session.last_turn_id,
        "turns_completed": session.turns_completed,
        "last_status": session.last_status,
        "last_assistant_response": session.last_assistant_response,
        "pending_prompt": session.pending_prompt,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
    }


def _session_from_json(raw: Mapping[str, Any]) -> TelegramChatSession:
    return TelegramChatSession(
        session_id=_required_string(raw, "session_id"),
        chat_id=_required_int(raw, "chat_id"),
        user_id=_required_int(raw, "user_id"),
        username=_optional_string(raw.get("username")),
        workspace_path=_optional_string(raw.get("workspace_path")),
        thread_id=_optional_string(raw.get("thread_id")),
        last_turn_id=_optional_string(raw.get("last_turn_id")),
        turns_completed=_optional_int(raw.get("turns_completed")),
        last_status=_optional_string(raw.get("last_status")) or "planned",
        last_assistant_response=_optional_string(raw.get("last_assistant_response")),
        pending_prompt=_optional_string(raw.get("pending_prompt")),
        created_at=_optional_datetime(raw.get("created_at")),
        updated_at=_optional_datetime(raw.get("updated_at")),
    )


def _safe_session_id(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")
    if not slug or slug in {".", ".."}:
        raise ValueError("chat session id does not contain usable characters")
    return slug[:120]


def _required_string(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ChatSessionStateError("chat session state is missing required string field: {}".format(key))
    return value


def _required_int(raw: Mapping[str, Any], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ChatSessionStateError("chat session state is missing required integer field: {}".format(key))
    return value


def _optional_string(value: Any) -> Optional[str]:
    if isinstance(value, str) and value:
        return value
    return None


def _optional_int(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _optional_datetime(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(timezone.utc)
