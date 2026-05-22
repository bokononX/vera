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

    def test_fake_smoke_defaults_to_runtime_workspace_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            previous_cwd = Path.cwd()
            try:
                os.chdir(temp_dir)
                with patch.dict(os.environ, {}, clear=True):
                    with contextlib.redirect_stdout(output):
                        status = cli.main(
                            [
                                "--fake-smoke",
                                "--message",
                                "Default runtime workspace task",
                                "--chat-id",
                                "100",
                                "--user-id",
                                "200",
                                "--message-id",
                                "300",
                                "--update-id",
                                "77",
                            ]
                        )
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(status, 0)
            workspace = Path(temp_dir, "runtime", "workspaces", "telegram-100-300").resolve()
            self.assertTrue(workspace.is_dir())
            self.assertFalse(Path(temp_dir, ".vera").resolve().exists())

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

    def test_user_memory_ingest_dry_run_does_not_require_live_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            conversation_path = Path(temp_dir, "conversation.txt")
            memory_root = Path(temp_dir, "memory")
            conversation_path.write_text(
                "User: I prefer concise engineering updates.\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with patch.dict(os.environ, {}, clear=True):
                with contextlib.redirect_stdout(stdout):
                    status = cli.main(
                        [
                            "--ingest-user-memory",
                            "--conversation-file",
                            str(conversation_path),
                            "--memory-root",
                            str(memory_root),
                            "--memory-user-id",
                            "user-test",
                            "--captured-at",
                            "2026-05-21T00:00:00Z",
                        ]
                    )

        self.assertEqual(status, 0)
        rendered = stdout.getvalue()
        self.assertIn("User memory ingest plan (dry-run)", rendered)
        self.assertIn("wiki/preferences/concise-engineering-updates.md", rendered)
        self.assertFalse(memory_root.exists())


class CliUserMemoryLintTests(unittest.TestCase):
    def test_user_memory_lint_dry_run_does_not_require_live_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_root = Path(temp_dir, "memory")
            page = memory_root / "wiki" / "preferences" / "direct-updates.md"
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text(
                "\n".join(
                    [
                        "---",
                        "id: mem-preference-direct-updates",
                        "title: Direct Updates",
                        "page_type: preference",
                        "owner_user: user-test",
                        "status: active",
                        "memory_state: confirmed",
                        "confidence:",
                        "  level: high",
                        "  score: 0.90",
                        "sensitivity: private",
                        "prompt_visibility: task_only",
                        "review_status: user_confirmed",
                        "created_at: 2026-05-01T00:00:00Z",
                        "updated_at: 2026-05-01T00:00:00Z",
                        "last_observed_at: 2026-05-01T00:00:00Z",
                        "last_confirmed_at: 2026-05-01T00:00:00Z",
                        "stale_after: P90D",
                        "source_refs: []",
                        "related: []",
                        "supersedes: []",
                        "superseded_by: []",
                        "contradictions: []",
                        "corrections: []",
                        "tags: [test]",
                        "---",
                        "",
                        "# Direct Updates",
                        "",
                        "User prefers direct updates.",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with patch.dict(os.environ, {}, clear=True):
                with contextlib.redirect_stdout(stdout):
                    status = cli.main(
                        [
                            "--lint-user-memory",
                            "--memory-root",
                            str(memory_root),
                            "--memory-user-id",
                            "user-test",
                            "--memory-lint-as-of",
                            "2026-05-21T00:00:00Z",
                        ]
                    )

            rendered = stdout.getvalue()

        self.assertEqual(status, 0)
        self.assertIn("User memory lint/consolidation report (dry-run)", rendered)
        self.assertIn("Missing metadata:", rendered)
        self.assertIn("Dry-run only: no files were mutated.", rendered)
        self.assertFalse((memory_root / "log.md").exists())


class CliIMessageContactTests(unittest.TestCase):
    def test_imessage_contact_ingest_disabled_does_not_require_messages_access(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stdout = io.StringIO()

            with patch.dict(os.environ, {}, clear=True):
                with contextlib.redirect_stdout(stdout):
                    status = cli.main(
                        [
                            "--ingest-imessage-contacts",
                            "--memory-root",
                            str(Path(temp_dir, "memory")),
                            "--memory-user-id",
                            "user-test",
                        ]
                    )

            rendered = stdout.getvalue()

        self.assertEqual(status, 0)
        self.assertIn("iMessage contact ingestion disabled", rendered)
        self.assertIn("No Messages database was opened", rendered)

    def test_imessage_contact_ingest_enabled_reports_missing_chat_db_clearly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stderr = io.StringIO()
            missing_db = Path(temp_dir, "missing-chat.db")

            with patch.dict(
                os.environ,
                {
                    "VERA_IMESSAGE_CONTACT_INGESTION_ENABLED": "true",
                    "VERA_IMESSAGE_CHAT_DB_PATH": str(missing_db),
                },
                clear=True,
            ):
                with contextlib.redirect_stderr(stderr):
                    status = cli.main(
                        [
                            "--ingest-imessage-contacts",
                            "--memory-root",
                            str(Path(temp_dir, "memory")),
                            "--memory-user-id",
                            "user-test",
                        ]
                    )

            rendered = stderr.getvalue()

        self.assertEqual(status, 2)
        self.assertIn("iMessage chat.db not found", rendered)
        self.assertIn("Full Disk Access", rendered)


if __name__ == "__main__":
    unittest.main()
