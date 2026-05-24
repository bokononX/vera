import tempfile
import unittest
from pathlib import Path

from vera_harness.config import HarnessConfig
from vera_harness.models import TelegramTask
from vera_harness.telegram import (
    TelegramBotApi,
    TelegramLongPollingIntake,
    TelegramTaskStatus,
    TelegramUpdateStatus,
    TelegramUpdateStore,
    format_telegram_status,
)


class FakeTelegramApi:
    def __init__(self, updates):
        self._updates = tuple(updates)
        self.get_updates_calls = []
        self.sent_messages = []

    def get_updates(self, offset, timeout):
        self.get_updates_calls.append({"offset": offset, "timeout": timeout})
        return self._updates

    def send_message(self, chat_id, text, reply_to_message_id=None):
        self.sent_messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_to_message_id": reply_to_message_id,
            }
        )
        return {"message_id": len(self.sent_messages)}


def _config(temp_dir, extra=None):
    env = {
        "VERA_WORKSPACE_ROOT": temp_dir,
        "VERA_TELEGRAM_STATE_PATH": str(Path(temp_dir, "telegram-state.json")),
        "VERA_ALLOWED_CHAT_IDS": "100",
        "VERA_ALLOWED_USER_IDS": "200",
        "VERA_TELEGRAM_POLL_TIMEOUT_SECONDS": "9",
    }
    if extra:
        env.update(extra)
    return HarnessConfig.from_env(env, require_secrets=False)


def _multi_config(temp_dir):
    return HarnessConfig.from_env(
        {
            "VERA_TELEGRAM_BOT_TOKEN_ALICE": "alice-secret-token",
            "VERA_TELEGRAM_BOT_TOKEN_BOB": "bob-secret-token",
            "VERA_WORKSPACE_ROOT": temp_dir,
        },
        require_secrets=True,
        telegram_config={
            "shared_chat_ids": [-1000],
            "users": [
                {
                    "id": "alice",
                    "bot_username": "alice_bot",
                    "bot_token_env": "VERA_TELEGRAM_BOT_TOKEN_ALICE",
                    "allowed_chat_ids": [101],
                    "allowed_user_ids": [201],
                    "command_prefixes": ["/alice"],
                    "state_path": str(Path(temp_dir, "alice-telegram-state.json")),
                },
                {
                    "id": "bob",
                    "bot_username": "bob_bot",
                    "bot_token_env": "VERA_TELEGRAM_BOT_TOKEN_BOB",
                    "allowed_chat_ids": [102],
                    "allowed_user_ids": [202],
                    "command_prefixes": ["/bob"],
                    "state_path": str(Path(temp_dir, "bob-telegram-state.json")),
                },
            ],
        },
    )


def _message_update(
    update_id,
    chat_id=100,
    user_id=200,
    message_id=300,
    text="Do the work",
    chat_type="private",
    reply_to_username=None,
):
    message = {
        "message_id": message_id,
        "chat": {"id": chat_id, "type": chat_type},
        "from": {"id": user_id, "username": "vera_user"},
        "text": text,
    }
    if reply_to_username is not None:
        message["reply_to_message"] = {
            "message_id": message_id - 1,
            "from": {"id": 999, "username": reply_to_username, "is_bot": True},
        }
    return {
        "update_id": update_id,
        "message": message,
    }


class TelegramBotApiTests(unittest.TestCase):
    def test_bot_api_uses_mocked_json_http_calls(self):
        calls = []

        def requester(url, payload, timeout_seconds):
            calls.append(
                {
                    "url": url,
                    "payload": dict(payload),
                    "timeout_seconds": timeout_seconds,
                }
            )
            if url.endswith("/getUpdates"):
                return {"ok": True, "result": []}
            return {"ok": True, "result": {"message_id": 1}}

        api = TelegramBotApi(
            bot_token="token-placeholder",
            api_base_url="https://telegram.example.test",
            request_timeout_seconds=11,
            requester=requester,
        )

        self.assertEqual(api.get_updates(offset=42, timeout=7), ())
        api.send_message(chat_id=100, text="Accepted: queued.", reply_to_message_id=300)

        self.assertEqual(calls[0]["url"], "https://telegram.example.test/bottoken-placeholder/getUpdates")
        self.assertEqual(calls[0]["payload"]["offset"], 42)
        self.assertEqual(calls[0]["payload"]["timeout"], 7)
        self.assertEqual(calls[0]["payload"]["allowed_updates"], ["message"])
        self.assertEqual(calls[0]["timeout_seconds"], 11)
        self.assertEqual(calls[1]["url"], "https://telegram.example.test/bottoken-placeholder/sendMessage")
        self.assertEqual(calls[1]["payload"]["chat_id"], 100)
        self.assertEqual(calls[1]["payload"]["text"], "Accepted: queued.")
        self.assertEqual(calls[1]["payload"]["reply_to_message_id"], 300)


class TelegramLongPollingIntakeTests(unittest.TestCase):
    def test_unauthorized_update_can_receive_configured_rejection_response(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                {
                    "VERA_TELEGRAM_UNAUTHORIZED_RESPONSE": "This Telegram source is not authorized.",
                },
            )
            store = TelegramUpdateStore(config.telegram_state_path)
            api = FakeTelegramApi(
                [_message_update(update_id=1, chat_id=999, user_id=200, message_id=301)]
            )
            polling = TelegramLongPollingIntake(config, api=api, store=store)

            outcomes = polling.poll_once()

            self.assertEqual(outcomes[0].status, TelegramUpdateStatus.REJECTED)
            self.assertEqual(len(polling.queue), 0)
            self.assertTrue(store.has_processed(1))
            self.assertEqual(api.sent_messages[0]["chat_id"], 999)
            self.assertEqual(api.sent_messages[0]["text"], "This Telegram source is not authorized.")
            self.assertEqual(api.sent_messages[0]["reply_to_message_id"], 301)

    def test_authorized_message_is_normalized_and_queued(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir)
            store = TelegramUpdateStore(config.telegram_state_path)
            api = FakeTelegramApi([_message_update(update_id=2, text="  Ship Telegram intake  ")])
            polling = TelegramLongPollingIntake(config, api=api, store=store)

            outcomes = polling.poll_once()
            queued = polling.queue.queued_tasks()

            self.assertEqual(outcomes[0].status, TelegramUpdateStatus.ACCEPTED)
            self.assertEqual(len(queued), 1)
            self.assertEqual(queued[0].task_id, "telegram-100-300")
            self.assertEqual(queued[0].text, "Ship Telegram intake")
            self.assertEqual(queued[0].username, "vera_user")
            self.assertEqual(store.next_offset(), 3)
            self.assertEqual(store.task_status("telegram-100-300"), TelegramTaskStatus.ACCEPTED.value)
            self.assertEqual(api.sent_messages[0]["text"], "Accepted: queued.")

    def test_update_offset_and_task_state_persist_without_raw_message_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir, "state.json")
            task = TelegramTask.from_message(
                chat_id=100,
                user_id=200,
                message_id=300,
                text="Sensitive task text",
                username="vera_user",
            )
            store = TelegramUpdateStore(state_path)

            store.record_task_status(task, TelegramTaskStatus.STARTED)
            store.mark_update_processed(77)
            restored = TelegramUpdateStore(state_path)

            self.assertEqual(restored.next_offset(), 78)
            self.assertTrue(restored.has_processed(77))
            self.assertEqual(restored.task_status(task.task_id), TelegramTaskStatus.STARTED.value)
            persisted = state_path.read_text(encoding="utf-8")
            self.assertNotIn("Sensitive task text", persisted)
            self.assertNotIn("vera_user", persisted)

    def test_duplicate_updates_are_suppressed_after_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir)
            first_api = FakeTelegramApi(
                [
                    _message_update(update_id=10, message_id=300, text="First task"),
                    _message_update(update_id=11, message_id=301, text="Second task"),
                ]
            )
            first_poll = TelegramLongPollingIntake(
                config,
                api=first_api,
                store=TelegramUpdateStore(config.telegram_state_path),
            )

            first_outcomes = first_poll.poll_once()

            self.assertEqual(
                [outcome.status for outcome in first_outcomes],
                [TelegramUpdateStatus.ACCEPTED, TelegramUpdateStatus.ACCEPTED],
            )
            self.assertEqual(first_api.get_updates_calls[0]["offset"], None)
            self.assertEqual(len(first_poll.queue), 2)

            second_api = FakeTelegramApi(
                [
                    _message_update(update_id=10, message_id=300, text="First task"),
                    _message_update(update_id=11, message_id=301, text="Second task"),
                    _message_update(update_id=12, message_id=302, text="Third task"),
                ]
            )
            second_poll = TelegramLongPollingIntake(
                config,
                api=second_api,
                store=TelegramUpdateStore(config.telegram_state_path),
            )

            second_outcomes = second_poll.poll_once()

            self.assertEqual(second_api.get_updates_calls[0]["offset"], 12)
            self.assertEqual(
                [outcome.status for outcome in second_outcomes],
                [
                    TelegramUpdateStatus.DUPLICATE,
                    TelegramUpdateStatus.DUPLICATE,
                    TelegramUpdateStatus.ACCEPTED,
                ],
            )
            self.assertEqual(len(second_poll.queue), 1)
            self.assertEqual(second_poll.queue.queued_tasks()[0].message_id, 302)
            self.assertEqual(len(second_api.sent_messages), 1)

    def test_status_formatting_and_delivery(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir)
            api = FakeTelegramApi([])
            store = TelegramUpdateStore(config.telegram_state_path)
            polling = TelegramLongPollingIntake(config, api=api, store=store)
            task = TelegramTask.from_message(
                chat_id=100,
                user_id=200,
                message_id=300,
                text="Do the work",
            )

            self.assertEqual(format_telegram_status(TelegramTaskStatus.ACCEPTED), "Accepted: queued.")
            self.assertEqual(format_telegram_status(TelegramTaskStatus.STARTED), "Started: working on it.")
            self.assertEqual(format_telegram_status(TelegramTaskStatus.COMPLETED), "Completed.")
            self.assertEqual(
                format_telegram_status(TelegramTaskStatus.FAILED),
                "Failed: Vera could not complete the task.",
            )
            self.assertEqual(
                format_telegram_status(
                    TelegramTaskStatus.BLOCKED,
                    reason="Need a repo URL before continuing.",
                ),
                "Blocked: I need your judgment before continuing. Need a repo URL before continuing.",
            )
            self.assertEqual(
                format_telegram_status(
                    TelegramTaskStatus.FAILED,
                    reason="Codex failed with Authorization: Bearer secret-token-value",
                ),
                "Failed: Vera could not complete the task. Codex failed with Authorization: <redacted secret>",
            )

            polling.send_task_status(task, TelegramTaskStatus.STARTED)
            polling.send_task_status(task, TelegramTaskStatus.COMPLETED)
            polling.send_task_status(
                task,
                TelegramTaskStatus.BLOCKED,
                reason="Need a repo URL before continuing.",
            )
            polling.send_task_status(
                task,
                TelegramTaskStatus.FAILED,
                reason="Codex turn timed out.",
            )

            self.assertEqual(
                [message["text"] for message in api.sent_messages],
                [
                    "Started: working on it.",
                    "Completed.",
                    "Blocked: I need your judgment before continuing. Need a repo URL before continuing.",
                    "Failed: Vera could not complete the task. Codex turn timed out.",
                ],
            )
            self.assertEqual(store.task_status(task.task_id), TelegramTaskStatus.FAILED.value)

    def test_shared_chat_requires_explicit_bot_routing_without_fanout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _multi_config(temp_dir)
            alice_config = config.config_for_telegram_user("alice")
            bob_config = config.config_for_telegram_user("bob")
            shared_updates = [
                _message_update(
                    update_id=20,
                    chat_id=-1000,
                    user_id=201,
                    message_id=400,
                    text="@alice_bot please handle this",
                    chat_type="supergroup",
                ),
                _message_update(
                    update_id=21,
                    chat_id=-1000,
                    user_id=201,
                    message_id=401,
                    text="unaddressed shared chatter",
                    chat_type="supergroup",
                ),
                _message_update(
                    update_id=22,
                    chat_id=-1000,
                    user_id=201,
                    message_id=402,
                    text="@alice_bot @bob_bot ambiguous",
                    chat_type="supergroup",
                ),
                _message_update(
                    update_id=23,
                    chat_id=-1000,
                    user_id=202,
                    message_id=403,
                    text="/bob shared prefix route",
                    chat_type="group",
                ),
                _message_update(
                    update_id=24,
                    chat_id=-1000,
                    user_id=201,
                    message_id=404,
                    text="reply route",
                    chat_type="supergroup",
                    reply_to_username="alice_bot",
                ),
            ]

            alice_polling = TelegramLongPollingIntake(
                alice_config,
                api=FakeTelegramApi(shared_updates),
                store=TelegramUpdateStore(alice_config.telegram_state_path),
            )
            bob_polling = TelegramLongPollingIntake(
                bob_config,
                api=FakeTelegramApi(shared_updates),
                store=TelegramUpdateStore(bob_config.telegram_state_path),
            )

            alice_outcomes = alice_polling.poll_once()
            bob_outcomes = bob_polling.poll_once()
            alice_next_offset = alice_polling.store.next_offset()
            bob_next_offset = bob_polling.store.next_offset()

        self.assertEqual(
            [outcome.status for outcome in alice_outcomes],
            [
                TelegramUpdateStatus.ACCEPTED,
                TelegramUpdateStatus.IGNORED,
                TelegramUpdateStatus.IGNORED,
                TelegramUpdateStatus.IGNORED,
                TelegramUpdateStatus.ACCEPTED,
            ],
        )
        self.assertEqual(
            [outcome.status for outcome in bob_outcomes],
            [
                TelegramUpdateStatus.IGNORED,
                TelegramUpdateStatus.IGNORED,
                TelegramUpdateStatus.IGNORED,
                TelegramUpdateStatus.ACCEPTED,
                TelegramUpdateStatus.IGNORED,
            ],
        )
        alice_tasks = alice_polling.queue.queued_tasks()
        bob_tasks = bob_polling.queue.queued_tasks()
        self.assertEqual([task.task_id for task in alice_tasks], ["telegram-alice--1000-400", "telegram-alice--1000-404"])
        self.assertEqual([task.text for task in alice_tasks], ["please handle this", "reply route"])
        self.assertEqual([task.task_id for task in bob_tasks], ["telegram-bob--1000-403"])
        self.assertEqual(bob_tasks[0].text, "shared prefix route")
        self.assertNotEqual(alice_config.telegram_state_path, bob_config.telegram_state_path)
        self.assertEqual(alice_next_offset, 25)
        self.assertEqual(bob_next_offset, 25)


if __name__ == "__main__":
    unittest.main()
