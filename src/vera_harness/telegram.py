"""Telegram intake boundary for the Vera harness.

Live polling and webhook handling are intentionally out of scope for this
scaffold. The module owns authorization checks and conversion from a Telegram
message shape into the internal task model.
"""

from __future__ import annotations

from typing import Optional

from .config import HarnessConfig
from .models import TelegramTask


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
