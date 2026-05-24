"""Telegram intake boundary for the Vera harness.

This module owns Telegram transport concerns: Bot API calls, update
authorization, update idempotency, task queueing, and concise user-facing
status replies. Codex and workspace orchestration consume normalized
``TelegramTask`` objects and do not need Telegram-specific payloads.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Tuple
from urllib import error as urllib_error
from urllib import request as urllib_request

from .config import ConfigError, HarnessConfig
from .models import TelegramTask
from .observability import redact_text


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


@dataclass(frozen=True)
class TelegramMessage:
    """Normalized Telegram message fields needed by intake routing."""

    chat_id: int
    user_id: int
    message_id: int
    text: str
    username: Optional[str] = None
    chat_type: Optional[str] = None
    reply_to_username: Optional[str] = None


@dataclass(frozen=True)
class TelegramSharedRoute:
    """Routing decision for one shared Telegram group/supergroup message."""

    accepted: bool
    text: str
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
            not self._config.allowed_chat_ids
            or chat_id in self._config.allowed_chat_ids
            or chat_id in self._config.telegram_shared_chat_ids
        )
        user_allowed = (
            not self._config.allowed_user_ids or user_id in self._config.allowed_user_ids
        )
        return chat_allowed and user_allowed

    def route_shared_message(
        self,
        chat_id: int,
        text: str,
        reply_to_username: Optional[str] = None,
    ) -> TelegramSharedRoute:
        if chat_id not in self._config.telegram_shared_chat_ids:
            return TelegramSharedRoute(accepted=True, text=text)

        target = _shared_route_target(
            text=text,
            reply_to_username=reply_to_username,
            bot_username=self._config.telegram_bot_username,
            known_bot_usernames=self._config.telegram_known_bot_usernames,
            command_prefixes=self._config.telegram_command_prefixes,
            known_command_prefixes=self._config.telegram_known_command_prefixes,
        )
        if target != "current":
            return TelegramSharedRoute(
                accepted=False,
                text=text,
                reason="shared chat message was not explicitly addressed to this bot",
            )
        return TelegramSharedRoute(
            accepted=True,
            text=_strip_shared_route_tokens(
                text,
                bot_username=self._config.telegram_bot_username,
                command_prefixes=self._config.telegram_command_prefixes,
            ),
        )

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
            bot_id=self._config.telegram_runtime_id,
            bot_username=self._config.telegram_bot_username,
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
        send_accepted_reply: bool = True,
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
        self._send_accepted_reply = send_accepted_reply

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

    def send_chat_response(
        self,
        task: TelegramTask,
        text: str,
        status: TelegramTaskStatus = TelegramTaskStatus.COMPLETED,
    ) -> None:
        self._store.record_task_status(task, status)
        self._api.send_message(
            chat_id=task.chat_id,
            text=text,
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

        route = self._intake.route_shared_message(
            chat_id=message.chat_id,
            text=message.text,
            reply_to_username=message.reply_to_username,
        )
        if not route.accepted:
            self._store.mark_update_processed(update_id)
            return TelegramIntakeOutcome(
                update_id=update_id,
                status=TelegramUpdateStatus.IGNORED,
                reason=route.reason,
            )

        if not self._intake.is_allowed(chat_id=message.chat_id, user_id=message.user_id):
            self._send_unauthorized_response(message.chat_id, message.message_id)
            self._store.mark_update_processed(update_id)
            return TelegramIntakeOutcome(
                update_id=update_id,
                status=TelegramUpdateStatus.REJECTED,
                reason="unauthorized Telegram chat or user",
            )

        try:
            task = self._intake.task_from_message(
                chat_id=message.chat_id,
                user_id=message.user_id,
                message_id=message.message_id,
                text=route.text,
                username=message.username,
            )
        except ValueError as exc:
            self._store.mark_update_processed(update_id)
            self._api.send_message(
                chat_id=message.chat_id,
                text=format_telegram_status(
                    TelegramTaskStatus.BLOCKED,
                    reason="Send a text task for Vera to run.",
                ),
                reply_to_message_id=message.message_id,
            )
            return TelegramIntakeOutcome(
                update_id=update_id,
                status=TelegramUpdateStatus.BLOCKED,
                reason=str(exc),
            )

        self._store.record_task_status(task, TelegramTaskStatus.ACCEPTED)
        self._store.mark_update_processed(update_id)
        self._queue.enqueue(task)
        if self._send_accepted_reply:
            self._api.send_message(
                chat_id=message.chat_id,
                text=format_telegram_status(TelegramTaskStatus.ACCEPTED),
                reply_to_message_id=message.message_id,
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


def _extract_message(update: Mapping[str, Any]) -> Optional[TelegramMessage]:
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
    chat_type = chat.get("type")
    if not isinstance(chat_type, str):
        chat_type = None
    reply_to_username = _reply_to_username(message)
    return TelegramMessage(
        chat_id=chat_id,
        user_id=user_id,
        message_id=message_id,
        text=text,
        username=username,
        chat_type=chat_type,
        reply_to_username=reply_to_username,
    )


def _reply_to_username(message: Mapping[str, Any]) -> Optional[str]:
    reply = message.get("reply_to_message")
    if not isinstance(reply, Mapping):
        return None
    sender = reply.get("from")
    if not isinstance(sender, Mapping):
        return None
    username = sender.get("username")
    if not isinstance(username, str):
        return None
    username = username.strip().lstrip("@")
    return username or None


def _shared_route_target(
    text: str,
    reply_to_username: Optional[str],
    bot_username: Optional[str],
    known_bot_usernames: Tuple[str, ...],
    command_prefixes: Tuple[str, ...],
    known_command_prefixes: Tuple[str, ...],
) -> str:
    targets = set()
    current_username = bot_username.lower() if bot_username else None
    known_usernames = {username.lower() for username in known_bot_usernames}
    for mention in _mentioned_usernames(text):
        if mention in known_usernames:
            targets.add("current" if mention == current_username else "other")

    if reply_to_username is not None:
        reply_username = reply_to_username.lower()
        if reply_username in known_usernames:
            targets.add("current" if reply_username == current_username else "other")

    matched_prefixes = _matched_command_prefixes(text, known_command_prefixes)
    if matched_prefixes:
        current_prefixes = set(command_prefixes)
        for prefix in matched_prefixes:
            targets.add("current" if prefix in current_prefixes else "other")

    if len(targets) != 1:
        return "ambiguous" if targets else "none"
    return next(iter(targets))


def _mentioned_usernames(text: str) -> Tuple[str, ...]:
    return tuple(
        match.group(1).lower()
        for match in re.finditer(r"@([A-Za-z0-9_]{5,32})", text)
    )


def _matched_command_prefixes(
    text: str,
    known_command_prefixes: Tuple[str, ...],
) -> Tuple[str, ...]:
    stripped = text.lstrip()
    matches = []
    for prefix in known_command_prefixes:
        if _text_starts_with_prefix(stripped, prefix):
            matches.append(prefix)
    return tuple(sorted(matches, key=len, reverse=True))


def _text_starts_with_prefix(text: str, prefix: str) -> bool:
    if not text.startswith(prefix):
        return False
    if len(text) == len(prefix):
        return True
    return text[len(prefix)].isspace()


def _strip_shared_route_tokens(
    text: str,
    bot_username: Optional[str],
    command_prefixes: Tuple[str, ...],
) -> str:
    stripped = text.strip()
    for prefix in sorted(command_prefixes, key=len, reverse=True):
        if _text_starts_with_prefix(stripped, prefix):
            stripped = stripped[len(prefix) :].strip()
            break
    if bot_username:
        stripped = re.sub(
            r"@{}\b".format(re.escape(bot_username)),
            "",
            stripped,
            flags=re.IGNORECASE,
        ).strip()
    return stripped


def _status_detail(reason: Optional[str]) -> str:
    if reason is None:
        return ""
    return " ".join(redact_text(reason).split())[:280]


def _empty_state() -> dict[str, Any]:
    return {
        "last_update_id": None,
        "processed_update_ids": [],
        "tasks": {},
    }
