import unittest
from datetime import datetime, timezone

from vera_harness.models import TelegramTask


class TelegramTaskTests(unittest.TestCase):
    def test_task_creation_keeps_minimal_telegram_context(self):
        received_at = datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc)

        task = TelegramTask.from_message(
            chat_id=123,
            user_id=456,
            message_id=789,
            text="  Build the harness scaffold  ",
            username=" vera_user ",
            received_at=received_at,
        )

        self.assertEqual(task.task_id, "telegram-123-789")
        self.assertEqual(task.chat_id, 123)
        self.assertEqual(task.user_id, 456)
        self.assertEqual(task.message_id, 789)
        self.assertEqual(task.text, "Build the harness scaffold")
        self.assertEqual(task.username, "vera_user")
        self.assertEqual(task.received_at, received_at)

    def test_task_creation_rejects_empty_text(self):
        with self.assertRaises(ValueError):
            TelegramTask.from_message(chat_id=1, user_id=2, message_id=3, text=" ")

    def test_summary_truncates_long_text(self):
        task = TelegramTask.from_message(chat_id=1, user_id=2, message_id=3, text="abcdef")

        self.assertEqual(task.summary(limit=4), "a...")


if __name__ == "__main__":
    unittest.main()
