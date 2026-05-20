import contextlib
import io
import os
import unittest
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


if __name__ == "__main__":
    unittest.main()
