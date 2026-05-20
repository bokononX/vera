import tempfile
import unittest
from pathlib import Path

from vera_harness.config import HarnessConfig
from vera_harness.orchestrator import VeraHarness, format_dry_run


class DryRunOrchestrationTests(unittest.TestCase):
    def test_dry_run_builds_workspace_prompt_and_invocation_without_live_dependencies(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = HarnessConfig.from_env(
                {
                    "VERA_WORKSPACE_ROOT": temp_dir,
                    "VERA_ALLOWED_CHAT_IDS": "100",
                    "VERA_ALLOWED_USER_IDS": "200",
                    "VERA_CODEX_APP_SERVER_COMMAND": "codex app-server --port 0",
                    "VERA_REPO_BOOTSTRAP_COMMAND": "make setup",
                },
                require_secrets=False,
            )
            harness = VeraHarness(config)

            result = harness.dry_run_task(
                text="Plan the next reversible implementation step.",
                chat_id=100,
                user_id=200,
                message_id=300,
                create_workspace=True,
            )
            output = format_dry_run(result)

            self.assertEqual(result.task.task_id, "telegram-100-300")
            self.assertTrue(result.workspace.path.is_dir())
            self.assertEqual(result.workspace.path, Path(temp_dir, "telegram-100-300").resolve())
            self.assertIn("Represent the user's agency", result.invocation.prompt)
            self.assertEqual(result.invocation.display_command, "codex app-server --port 0")
            self.assertIn("workspace_path: {}".format(result.workspace.path), output)
            self.assertIn("prompt_policy_summary:", output)
            self.assertIn("planned_codex_invocation:", output)
            self.assertIn("codex_launch: skipped (dry run)", output)
            self.assertIn("telegram_network_calls: skipped (dry run)", output)

    def test_dry_run_rejects_unauthorized_telegram_origin(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = HarnessConfig.from_env(
                {
                    "VERA_WORKSPACE_ROOT": temp_dir,
                    "VERA_ALLOWED_CHAT_IDS": "100",
                },
                require_secrets=False,
            )
            harness = VeraHarness(config)

            with self.assertRaises(PermissionError):
                harness.dry_run_task(
                    text="hello",
                    chat_id=999,
                    user_id=200,
                    message_id=1,
                    create_workspace=False,
                )


if __name__ == "__main__":
    unittest.main()
