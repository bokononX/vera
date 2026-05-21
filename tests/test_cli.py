import contextlib
import io
import os
import shlex
import sys
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

            with patch.dict(
                os.environ,
                {
                    "VERA_TELEGRAM_BOT_TOKEN": "redacted-test-value",
                    "VERA_CODEX_APP_SERVER_COMMAND": "{} app-server".format(
                        shlex.quote(sys.executable)
                    ),
                },
                clear=True,
            ):
                with contextlib.redirect_stdout(output):
                    status = cli.main(["--check-config", "--telegram-config", str(config_path)])

        self.assertEqual(status, 0)
        rendered = output.getvalue()
        self.assertIn("Vera configuration OK", rendered)
        self.assertIn("telegram_bot_token: <secret-present>", rendered)
        self.assertIn("allowed_chat_ids: 100", rendered)
        self.assertIn("telegram_poll_timeout_seconds: 9", rendered)
        self.assertIn("identity_profile_path:", rendered)
        self.assertIn("identity_interview_state_path:", rendered)
        self.assertIn(
            "codex_app_server_executable: {}".format(Path(sys.executable).resolve()),
            rendered,
        )
        self.assertNotIn("redacted-test-value", rendered)

    def test_check_config_fails_when_codex_executable_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir, "telegram.json")
            config_path.write_text(
                """
{
  "telegram": {
    "allowed_chat_ids": [100],
    "state_path": "%s"
  }
}
""".strip()
                % Path(temp_dir, "state.json"),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with patch.dict(
                os.environ,
                {
                    "VERA_TELEGRAM_BOT_TOKEN": "redacted-test-value",
                    "VERA_CODEX_APP_SERVER_COMMAND": "definitely-missing-codex app-server",
                },
                clear=True,
            ):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    status = cli.main(["--check-config", "--telegram-config", str(config_path)])

        self.assertEqual(status, 2)
        self.assertEqual(stdout.getvalue(), "")
        rendered = stderr.getvalue()
        self.assertIn("VERA_CODEX_APP_SERVER_COMMAND executable not found on PATH", rendered)
        self.assertIn("definitely-missing-codex", rendered)
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

    def test_fake_smoke_runs_without_live_secrets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()

            with patch.dict(os.environ, {}, clear=True):
                with contextlib.redirect_stdout(output):
                    status = cli.main(
                        [
                            "--fake-smoke",
                            "--message",
                            "Sensitive fake smoke task text",
                            "--chat-id",
                            "100",
                            "--user-id",
                            "200",
                            "--message-id",
                            "300",
                            "--update-id",
                            "77",
                            "--workspace-root",
                            temp_dir,
                        ]
                    )

        self.assertEqual(status, 0)
        rendered = output.getvalue()
        self.assertIn("Vera Telegram-to-Codex fake smoke", rendered)
        self.assertIn("task_id: telegram-100-300", rendered)
        self.assertIn("telegram_update_id: 77", rendered)
        self.assertIn("codex_thread_id: fake-thread", rendered)
        self.assertIn("codex_turn_id: fake-turn-1", rendered)
        self.assertIn("telegram_text: Accepted: queued.", rendered)
        self.assertIn("telegram_text: Started: working on it.", rendered)
        self.assertIn("telegram_text: Completed.", rendered)
        self.assertNotIn("Sensitive fake smoke task text", rendered)

    def test_live_smoke_fails_clearly_without_required_live_config(self):
        stderr = io.StringIO()

        with patch.dict(os.environ, {}, clear=True):
            with contextlib.redirect_stderr(stderr):
                status = cli.main(["--live-smoke"])

        self.assertEqual(status, 2)
        self.assertIn("VERA_TELEGRAM_BOT_TOKEN is required for live runs", stderr.getvalue())

        stderr = io.StringIO()
        with patch.dict(os.environ, {"VERA_TELEGRAM_BOT_TOKEN": "token-placeholder"}, clear=True):
            with contextlib.redirect_stderr(stderr):
                status = cli.main(["--live-smoke"])

        self.assertEqual(status, 2)
        self.assertIn(
            "telegram.allowed_chat_ids or telegram.allowed_user_ids is required for live runs",
            stderr.getvalue(),
        )

    def test_monitor_validates_codex_before_polling(self):
        stderr = io.StringIO()

        with patch.dict(
            os.environ,
            {
                "VERA_TELEGRAM_BOT_TOKEN": "token-placeholder",
                "VERA_ALLOWED_CHAT_IDS": "100",
                "VERA_CODEX_APP_SERVER_COMMAND": "definitely-missing-codex app-server",
            },
            clear=True,
        ):
            with contextlib.redirect_stderr(stderr):
                status = cli.main(["--monitor", "--max-poll-cycles", "1"])

        self.assertEqual(status, 2)
        self.assertIn("VERA_CODEX_APP_SERVER_COMMAND executable not found on PATH", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
