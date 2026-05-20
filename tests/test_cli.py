import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vera_harness import cli


class CliConfigTests(unittest.TestCase):
    def test_check_config_prints_non_secret_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir, "telegram.json")
            state_path = Path(temp_dir, "state.json")
            config_path.write_text(
                """
{
  "telegram": {
    "allowed_chat_ids": [100],
    "allowed_user_ids": [200],
    "api_base_url": "https://telegram.example.test",
    "poll_timeout_seconds": 9,
    "request_timeout_seconds": 10,
    "state_path": "%s",
    "unauthorized_response": "Not authorized."
  }
}
""".strip()
                % state_path,
                encoding="utf-8",
            )
            output = io.StringIO()

            with patch.dict(os.environ, {"VERA_TELEGRAM_BOT_TOKEN": "redacted-test-value"}, clear=True):
                with contextlib.redirect_stdout(output):
                    status = cli.main(["--check-config", "--telegram-config", str(config_path)])

        self.assertEqual(status, 0)
        rendered = output.getvalue()
        self.assertIn("Vera configuration OK", rendered)
        self.assertIn("telegram_bot_token: <secret-present>", rendered)
        self.assertIn("allowed_chat_ids: 100", rendered)
        self.assertIn("telegram_poll_timeout_seconds: 9", rendered)
        self.assertNotIn("redacted-test-value", rendered)

    def test_poll_once_loads_telegram_config_path(self):
        captured = {}

        class FakeHarness:
            def __init__(self, config):
                captured["config"] = config

            def poll_telegram_once(self):
                return object()

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir, "telegram.json")
            state_path = Path(temp_dir, "state.json")
            config_path.write_text(
                """
{
  "telegram": {
    "allowed_chat_ids": [100],
    "allowed_user_ids": [200],
    "poll_timeout_seconds": 9,
    "state_path": "%s"
  }
}
""".strip()
                % state_path,
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"VERA_TELEGRAM_BOT_TOKEN": "token-placeholder"}, clear=True):
                with patch.object(cli, "VeraHarness", FakeHarness):
                    with patch.object(cli, "format_poll_once", return_value="poll ok"):
                        with contextlib.redirect_stdout(io.StringIO()):
                            status = cli.main(["--poll-once", "--telegram-config", str(config_path)])

        self.assertEqual(status, 0)
        self.assertEqual(captured["config"].telegram_bot_token, "token-placeholder")
        self.assertEqual(captured["config"].allowed_chat_ids, (100,))
        self.assertEqual(captured["config"].allowed_user_ids, (200,))
        self.assertEqual(captured["config"].telegram_poll_timeout_seconds, 9)
        self.assertEqual(captured["config"].telegram_state_path, state_path.resolve())


if __name__ == "__main__":
    unittest.main()
