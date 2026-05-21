import contextlib
import io
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from vera_harness import cli
from vera_harness.console_gui import run_gui
from vera_harness.console_tui import render_tui_frame, run_tui
from vera_harness.observability import fake_observability_provider


class ConsoleSurfaceTests(unittest.TestCase):
    def test_tui_smoke_renders_fake_state(self):
        provider = fake_observability_provider()
        snapshot = provider.snapshot()

        frame = render_tui_frame(snapshot, width=200, height=30)

        self.assertIn("Vera Agent Console", frame)
        self.assertIn("Available agents", frame)
        self.assertIn("Last turn and current plan", frame)
        self.assertIn("Agent log stream", frame)
        self.assertIn("<redacted private message>", frame)
        self.assertNotIn("sk-live-secret", frame)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = run_tui(provider, smoke=True)

        self.assertEqual(status, 0)
        self.assertIn("Vera TUI smoke OK", output.getvalue())

    def test_gui_smoke_serves_fake_state(self):
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            status = run_gui(fake_observability_provider(), port=0, smoke=True)

        self.assertEqual(status, 0)
        self.assertIn("Vera GUI smoke OK", output.getvalue())

    def test_cli_console_smoke_modes_do_not_require_live_secrets(self):
        with patch.dict(os.environ, {}, clear=True):
            tui_output = io.StringIO()
            with contextlib.redirect_stdout(tui_output):
                tui_status = cli.main(["--console-tui", "--console-fake-state", "--console-smoke"])

            gui_output = io.StringIO()
            with contextlib.redirect_stdout(gui_output):
                gui_status = cli.main(
                    [
                        "--console-gui",
                        "--console-fake-state",
                        "--console-smoke",
                        "--console-port",
                        "0",
                    ]
                )

        self.assertEqual(tui_status, 0)
        self.assertEqual(gui_status, 0)
        self.assertIn("Vera TUI smoke OK", tui_output.getvalue())
        self.assertIn("Vera GUI smoke OK", gui_output.getvalue())

    def test_cli_console_tui_missing_live_config_renders_error_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            env = {
                "VERA_RUN_STATE_PATH": str(Path(temp_dir, "run-state.json")),
                "VERA_EVENT_LOG_PATH": str(Path(temp_dir, "events.jsonl")),
            }

            with patch.dict(os.environ, env, clear=True):
                with contextlib.redirect_stdout(output):
                    status = cli.main(["--console-tui", "--console-smoke"])

        self.assertEqual(status, 0)
        rendered = output.getvalue()
        self.assertIn("console_monitor_startup_failed", rendered)
        self.assertIn("VERA_TELEGRAM_BOT_TOKEN", rendered)

    def test_cli_console_view_only_does_not_start_monitor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            env = {
                "VERA_RUN_STATE_PATH": str(Path(temp_dir, "run-state.json")),
                "VERA_EVENT_LOG_PATH": str(Path(temp_dir, "events.jsonl")),
            }

            with patch.dict(os.environ, env, clear=True):
                with patch.object(cli, "VeraHarness", side_effect=AssertionError("monitor should not start")):
                    with contextlib.redirect_stdout(output):
                        status = cli.main(["--console-tui", "--console-view-only", "--console-smoke"])

        self.assertEqual(status, 0)
        rendered = output.getvalue()
        self.assertIn("Vera TUI smoke OK", rendered)
        self.assertNotIn("console_monitor_startup_failed", rendered)

    def test_cli_console_tui_starts_and_stops_managed_monitor(self):
        started = threading.Event()
        calls = []

        class FakeHarness:
            def __init__(self, config, on_event=None):
                self._on_event = on_event

            def run_telegram_chat_poll_once(self):
                calls.append("poll")
                started.set()
                time.sleep(0.01)

                class Result:
                    response_deliveries = ()

                return Result()

        def fake_run_tui(provider, focused_agent_id=None, event_filter=None, smoke=False):
            self.assertTrue(started.wait(timeout=1.0))
            return 0

        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "VERA_TELEGRAM_BOT_TOKEN": "token-placeholder",
                "VERA_ALLOWED_CHAT_IDS": "100",
                "VERA_CODEX_APP_SERVER_COMMAND": "python3 -m fake_codex_server",
                "VERA_RUN_STATE_PATH": str(Path(temp_dir, "run-state.json")),
                "VERA_CHAT_SESSION_STATE_PATH": str(Path(temp_dir, "chat-sessions.json")),
                "VERA_EVENT_LOG_PATH": str(Path(temp_dir, "events.jsonl")),
                "VERA_TELEGRAM_STATE_PATH": str(Path(temp_dir, "telegram-state.json")),
            }

            with patch.dict(os.environ, env, clear=True):
                with patch.object(cli, "VeraHarness", FakeHarness):
                    with patch("vera_harness.console_tui.run_tui", side_effect=fake_run_tui):
                        status = cli.main(["--console-tui", "--poll-interval-seconds", "1"])

            events = Path(temp_dir, "events.jsonl").read_text(encoding="utf-8")

        self.assertEqual(status, 0)
        self.assertGreaterEqual(len(calls), 1)
        self.assertIn("console_monitor_started", events)
        self.assertIn("console_monitor_stopped", events)


if __name__ == "__main__":
    unittest.main()
