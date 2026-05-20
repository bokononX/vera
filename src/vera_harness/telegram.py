"""Telegram intake boundary for the Vera harness.

This module owns Telegram transport concerns: Bot API calls, update
authorization, update idempotency, task queueing, and concise user-facing
status replies. Codex and workspace orchestration consume normalized
``TelegramTask`` objects and do not need Telegram-specific payloads.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Tuple
from urllib import error as urllib_error
from urllib import request as urllib_request

from .config import ConfigError, HarnessConfig
from .models import TelegramTask


TelegramJsonRequester = Callable[[str, Mapping[str, object], int], Mapping[str, object]]


class TelegramApiError(RuntimeError):
    """Raised when the Telegram Bot API request fails."""


class TelegramTaskStatus(str, Enum):
    """Task lifecycle status reported back to Telegram."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    STARTED = "started"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


class TelegramUpdateStatus(str, Enum):
    """Processing outcome for one Telegram update."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class TelegramIntakeOutcome:
    """Result of processing one Telegram update."""

    update_id: Optional[int]
    status: TelegramUpdateStatus
    task: Optional[TelegramTask] = None
    reason: Optional[str] = None


class TelegramBotApi:
    """Small Telegram Bot API client using JSON POST requests."""

    def __init__(
        self,
        bot_token: str,
        api_base_url: str = "https://api.telegram.org",
        request_timeout_seconds: int = 35,
        requester: Optional[TelegramJsonRequester] = None,
    ) -> None:
        token = bot_token.strip()
        if not token:
            raise ConfigError("VERA_TELEGRAM_BOT_TOKEN is required for Telegram polling")
        self._bot_token = token
        self._api_base_url = api_base_url.rstrip("/")
        self._request_timeout_seconds = request_timeout_seconds
        self._requester = requester or _urllib_json_request

    def get_updates(self, offset: Optional[int], timeout: int) -> Tuple[Mapping[str, Any], ...]:
        payload: dict[str, object] = {
            "timeout": timeout,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset
        result = self.request("getUpdates", payload)
        if not isinstance(result, list):
            raise TelegramApiError("Telegram getUpdates returned a non-list result")
        return tuple(update for update in result if isinstance(update, Mapping))

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: Optional[int] = None,
    ) -> Mapping[str, Any]:
        payload: dict[str, object] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id
        result = self.request("sendMessage", payload)
        if not isinstance(result, Mapping):
            raise TelegramApiError("Telegram sendMessage returned a non-object result")
        return result

    def request(self, method: str, payload: Mapping[str, object]) -> Any:
        url = "{}/bot{}/{}".format(self._api_base_url, self._bot_token, method)
        response = self._requester(url, payload, self._request_timeout_seconds)
        if response.get("ok") is not True:
            description = response.get("description", "unknown Telegram API error")
            raise TelegramApiError(str(description))
        return response.get("result")


class TelegramUpdateStore:
    """Persists Telegram update offsets and minimal task lifecycle state."""

    def __init__(self, path: Path, max_processed_update_ids: int = 1000) -> None:
        self._path = path
        self._max_processed_update_ids = max_processed_update_ids

    @property
    def path(self) -> Path:
        return self._path

    def next_offset(self) -> Optional[int]:
        state = self._load_state()
        last_update_id = state.get("last_update_id")
        if isinstance(last_update_id, int):
            return last_update_id + 1
        return None

    def has_processed(self, update_id: int) -> bool:
        state = self._load_state()
        last_update_id = state.get("last_update_id")
        if isinstance(last_update_id, int) and update_id <= last_update_id:
            return True
        return update_id in state.get("processed_update_ids", [])

    def mark_update_processed(self, update_id: int) -> None:
        state = self._load_state()
        processed = set(state.get("processed_update_ids", []))
        processed.add(update_id)
        state["processed_update_ids"] = sorted(processed)[-self._max_processed_update_ids :]
        last_update_id = state.get("last_update_id")
        if not isinstance(last_update_id, int) or update_id > last_update_id:
            state["last_update_id"] = update_id
        self._write_state(state)

    def record_task_status(self, task: TelegramTask, status: TelegramTaskStatus) -> None:
        state = self._load_state()
        tasks = state.setdefault("tasks", {})
        tasks[task.task_id] = {
            "status": TelegramTaskStatus(status).value,
            "chat_id": task.chat_id,
            "user_id": task.user_id,
            "message_id": task.message_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write_state(state)

    def task_status(self, task_id: str) -> Optional[str]:
        state = self._load_state()
        task_state = state.get("tasks", {}).get(task_id)
        if not isinstance(task_state, Mapping):
            return None
        status = task_state.get("status")
        return status if isinstance(status, str) else None

    def task_states(self) -> Mapping[str, Mapping[str, object]]:
        return dict(self._load_state().get("tasks", {}))

    def _load_state(self) -> dict[str, Any]:
        if not self._path.exists():
            return _empty_state()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Telegram state file is not valid JSON: {}".format(exc))
        if not isinstance(raw, dict):
            raise ValueError("Telegram state file must contain a JSON object")
        state = _empty_state()
        last_update_id = raw.get("last_update_id")
        if isinstance(last_update_id, int):
            state["last_update_id"] = last_update_id
        processed = raw.get("processed_update_ids")
        if isinstance(processed, list):
            state["processed_update_ids"] = [item for item in processed if isinstance(item, int)]
        tasks = raw.get("tasks")
        if isinstance(tasks, dict):
            state["tasks"] = {
                str(task_id): task_state
                for task_id, task_state in tasks.items()
                if isinstance(task_state, dict)
            }
        return state

    def _write_state(self, state: Mapping[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_name("{}.tmp".format(self._path.name))
        temp_path.write_text(
            json.dumps(state, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(self._path)


class TelegramTaskQueue:
    """In-memory queue boundary for tasks accepted from Telegram."""

    def __init__(self) -> None:
        self._tasks: list[TelegramTask] = []

    def enqueue(self, task: TelegramTask) -> None:
        self._tasks.append(task)

    def queued_tasks(self) -> Tuple[TelegramTask, ...]:
        return tuple(self._tasks)

    def drain(self) -> Tuple[TelegramTask, ...]:
        tasks = tuple(self._tasks)
        self._tasks.clear()
        return tasks

    def __len__(self) -> int:
        return len(self._tasks)


class TelegramIntake:
    """Converts Telegram-originated messages into harness tasks."""

    def __init__(self, config: HarnessConfig) -> None:
        self._config = config

    def is_allowed(self, chat_id: int, user_id: int) -> bool:
        chat_allowed = (
            not self._config.allowed_chat_ids or chat_id in self._config.allowed_chat_ids
        )
        user_allowed = (
            not self._config.allowed_user_ids or user_id in self._config.allowed_user_ids
        )
        return chat_allowed and user_allowed

    def task_from_message(
        self,
        chat_id: int,
        user_id: int,
        message_id: int,
        text: str,
        username: Optional[str] = None,
    ) -> TelegramTask:
        if not self.is_allowed(chat_id, user_id):
            raise PermissionError(
                "Telegram chat_id/user_id is not allowed by harness configuration"
            )
        return TelegramTask.from_message(
            chat_id=chat_id,
            user_id=user_id,
            message_id=message_id,
            text=text,
            username=username,
        )


class TelegramLongPollingIntake:
    """Polls Telegram updates and queues authorized text messages as tasks."""

    def __init__(
        self,
        config: HarnessConfig,
        api: Optional[Any] = None,
        store: Optional[TelegramUpdateStore] = None,
        queue: Optional[TelegramTaskQueue] = None,
        intake: Optional[TelegramIntake] = None,
    ) -> None:
        self._config = config
        self._api = api or TelegramBotApi(
            bot_token=config.telegram_bot_token or "",
            api_base_url=config.telegram_api_base_url,
            request_timeout_seconds=config.telegram_request_timeout_seconds,
        )
        self._store = store or TelegramUpdateStore(config.telegram_state_path)
        self._queue = queue or TelegramTaskQueue()
        self._intake = intake or TelegramIntake(config)

    @property
    def queue(self) -> TelegramTaskQueue:
        return self._queue

    @property
    def store(self) -> TelegramUpdateStore:
        return self._store

    def poll_once(self) -> Tuple[TelegramIntakeOutcome, ...]:
        updates = self._api.get_updates(
            offset=self._store.next_offset(),
            timeout=self._config.telegram_poll_timeout_seconds,
        )
        return tuple(self._handle_update(update) for update in updates)

    def send_task_status(
        self,
        task: TelegramTask,
        status: TelegramTaskStatus,
        reason: Optional[str] = None,
    ) -> None:
        normalized_status = TelegramTaskStatus(status)
        self._store.record_task_status(task, normalized_status)
        self._api.send_message(
            chat_id=task.chat_id,
            text=format_telegram_status(normalized_status, reason=reason),
            reply_to_message_id=task.message_id,
        )

    def _handle_update(self, update: Mapping[str, Any]) -> TelegramIntakeOutcome:
        update_id = update.get("update_id")
        if not isinstance(update_id, int):
            return TelegramIntakeOutcome(
                update_id=None,
                status=TelegramUpdateStatus.IGNORED,
                reason="missing integer update_id",
            )
        if self._store.has_processed(update_id):
            return TelegramIntakeOutcome(update_id=update_id, status=TelegramUpdateStatus.DUPLICATE)

        message = _extract_message(update)
        if message is None:
            self._store.mark_update_processed(update_id)
            return TelegramIntakeOutcome(
                update_id=update_id,
                status=TelegramUpdateStatus.IGNORED,
                reason="update did not contain a supported message",
            )

        chat_id, user_id, message_id, text, username = message
        if not self._intake.is_allowed(chat_id=chat_id, user_id=user_id):
            self._send_unauthorized_response(chat_id, message_id)
            self._store.mark_update_processed(update_id)
            return TelegramIntakeOutcome(
                update_id=update_id,
                status=TelegramUpdateStatus.REJECTED,
                reason="unauthorized Telegram chat or user",
            )

        try:
            task = self._intake.task_from_message(
                chat_id=chat_id,
                user_id=user_id,
                message_id=message_id,
                text=text,
                username=username,
            )
        except ValueError as exc:
            self._store.mark_update_processed(update_id)
            self._api.send_message(
                chat_id=chat_id,
                text=format_telegram_status(
                    TelegramTaskStatus.BLOCKED,
                    reason="Send a text task for Vera to run.",
                ),
                reply_to_message_id=message_id,
            )
            return TelegramIntakeOutcome(
                update_id=update_id,
                status=TelegramUpdateStatus.BLOCKED,
                reason=str(exc),
            )

        self._store.record_task_status(task, TelegramTaskStatus.ACCEPTED)
        self._store.mark_update_processed(update_id)
        self._queue.enqueue(task)
        self._api.send_message(
            chat_id=chat_id,
            text=format_telegram_status(TelegramTaskStatus.ACCEPTED),
            reply_to_message_id=message_id,
        )
        return TelegramIntakeOutcome(
            update_id=update_id,
            status=TelegramUpdateStatus.ACCEPTED,
            task=task,
        )

    def _send_unauthorized_response(self, chat_id: int, message_id: int) -> None:
        if self._config.telegram_unauthorized_response is None:
            return
        self._api.send_message(
            chat_id=chat_id,
            text=self._config.telegram_unauthorized_response,
            reply_to_message_id=message_id,
        )


def format_telegram_status(
    status: TelegramTaskStatus,
    reason: Optional[str] = None,
) -> str:
    """Formats concise, actionable Telegram lifecycle replies."""

    normalized_status = TelegramTaskStatus(status)
    if normalized_status is TelegramTaskStatus.ACCEPTED:
        return "Accepted: queued."
    if normalized_status is TelegramTaskStatus.REJECTED:
        return "Rejected: this chat or user is not authorized."
    if normalized_status is TelegramTaskStatus.STARTED:
        return "Started: working on it."
    if normalized_status is TelegramTaskStatus.COMPLETED:
        return "Completed."
    if normalized_status is TelegramTaskStatus.FAILED:
        message = "Failed: Vera could not complete the task."
        detail = _status_detail(reason)
        if detail:
            return "{} {}".format(message, detail)
        return message

    message = "Blocked: I need your judgment before continuing."
    detail = _status_detail(reason)
    if detail:
        return "{} {}".format(message, detail)
    return message


def _urllib_json_request(
    url: str,
    payload: Mapping[str, object],
    timeout_seconds: int,
) -> Mapping[str, object]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib_request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except urllib_error.URLError as exc:
        raise TelegramApiError("Telegram API request failed: {}".format(exc))
    decoded = json.loads(raw)
    if not isinstance(decoded, Mapping):
        raise TelegramApiError("Telegram API response must be a JSON object")
    return decoded


def _extract_message(update: Mapping[str, Any]) -> Optional[Tuple[int, int, int, str, Optional[str]]]:
    message = update.get("message")
    if not isinstance(message, Mapping):
        return None
    chat = message.get("chat")
    sender = message.get("from")
    if not isinstance(chat, Mapping) or not isinstance(sender, Mapping):
        return None

    chat_id = chat.get("id")
    user_id = sender.get("id")
    message_id = message.get("message_id")
    if not isinstance(chat_id, int) or not isinstance(user_id, int) or not isinstance(message_id, int):
        return None

    text = message.get("text")
    if not isinstance(text, str):
        text = ""
    username = sender.get("username")
    if not isinstance(username, str):
        username = None
    return chat_id, user_id, message_id, text, username


def _status_detail(reason: Optional[str]) -> str:
    if reason is None:
        return ""
    return " ".join(reason.split())[:280]


def _empty_state() -> dict[str, Any]:
    return {
        "last_update_id": None,
        "processed_update_ids": [],
        "tasks": {},
    }
