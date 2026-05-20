import json
import shlex
import sys
import tempfile
import unittest
from pathlib import Path

from vera_harness.config import HarnessConfig
from vera_harness.models import TelegramTask, WorkspaceBootstrapStatus, WorkspaceReusePolicy
from vera_harness.workspace import WorkspaceBootstrapError, WorkspaceError, WorkspaceManager


class WorkspaceManagerTests(unittest.TestCase):
    def test_sanitizes_task_id_to_deterministic_path_under_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            task = TelegramTask(
                task_id="telegram chat/../run?alpha",
                chat_id=1,
                user_id=2,
                message_id=3,
                text="work",
            )
            manager = WorkspaceManager(_config(temp_dir))

            workspace = manager.prepare_workspace(task, run_bootstrap=False)

            self.assertEqual(workspace.workspace_id, "telegram-chat-..-run-alpha")
            self.assertEqual(workspace.path, Path(temp_dir, workspace.workspace_id).resolve())
            self.assertTrue(workspace.path.is_dir())
            self.assertEqual(workspace.bootstrap_status, WorkspaceBootstrapStatus.SKIPPED)
            self.assertEqual(_metadata(workspace)["path"], str(workspace.path))

    def test_rejects_task_id_without_usable_workspace_characters(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = WorkspaceManager(_config(temp_dir))
            task = TelegramTask(
                task_id="../../",
                chat_id=1,
                user_id=2,
                message_id=3,
                text="work",
            )

            with self.assertRaises(ValueError):
                manager.prepare_workspace(task, run_bootstrap=False)

    def test_resolve_without_create_does_not_create_workspace_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir, "missing-root")
            manager = WorkspaceManager(_config(root))

            workspace = manager.prepare_workspace(_task(), create=False, run_bootstrap=False)

            self.assertEqual(workspace.path, root.resolve() / "telegram-1-3")
            self.assertFalse(root.exists())
            self.assertFalse(workspace.path.exists())

    def test_rejects_symlink_workspace_that_escapes_root(self):
        with tempfile.TemporaryDirectory() as root_dir, tempfile.TemporaryDirectory() as outside_dir:
            root = Path(root_dir).resolve()
            outside = Path(outside_dir).resolve()
            (root / "telegram-1-3").symlink_to(outside, target_is_directory=True)
            manager = WorkspaceManager(_config(root))

            with self.assertRaises(WorkspaceError):
                manager.prepare_workspace(_task(), run_bootstrap=False)

            self.assertTrue(outside.is_dir())

    def test_reuse_and_fresh_policy_are_explicit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = WorkspaceManager(_config(temp_dir))
            first = manager.prepare_workspace(_task(), run_bootstrap=False)
            marker = first.path / "marker.txt"
            marker.write_text("keep", encoding="utf-8")

            reused = manager.prepare_workspace(
                _task(),
                policy=WorkspaceReusePolicy.REUSE,
                run_bootstrap=False,
            )
            self.assertFalse(reused.created)
            self.assertTrue(reused.reused)
            self.assertTrue(marker.exists())

            fresh = manager.prepare_workspace(
                _task(),
                policy=WorkspaceReusePolicy.FRESH,
                run_bootstrap=False,
            )
            self.assertTrue(fresh.created)
            self.assertFalse((fresh.path / "marker.txt").exists())

    def test_require_existing_policy_fails_when_workspace_is_absent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = WorkspaceManager(_config(temp_dir))

            with self.assertRaises(WorkspaceError):
                manager.prepare_workspace(
                    _task(),
                    policy=WorkspaceReusePolicy.REQUIRE_EXISTING,
                    run_bootstrap=False,
                )

    def test_bootstrap_success_captures_output_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            command = _python_command(
                'from pathlib import Path; Path("boot.txt").write_text("ok"); print("booted")'
            )
            manager = WorkspaceManager(
                _config(temp_dir, {"VERA_REPO_BOOTSTRAP_COMMAND": command})
            )

            workspace = manager.prepare_workspace(_task(), run_bootstrap=True)

            self.assertEqual(workspace.bootstrap_status, WorkspaceBootstrapStatus.SUCCEEDED)
            self.assertEqual(workspace.bootstrap_returncode, 0)
            self.assertIn("booted", workspace.bootstrap_stdout)
            self.assertEqual((workspace.path / "boot.txt").read_text(encoding="utf-8"), "ok")
            self.assertEqual(_metadata(workspace)["bootstrap_status"], "succeeded")

    def test_bootstrap_failure_captures_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            command = _python_command('import sys; print("bad", file=sys.stderr); sys.exit(7)')
            manager = WorkspaceManager(
                _config(temp_dir, {"VERA_REPO_BOOTSTRAP_COMMAND": command})
            )

            with self.assertRaises(WorkspaceBootstrapError) as raised:
                manager.prepare_workspace(_task(), run_bootstrap=True)

            workspace = raised.exception.workspace
            self.assertEqual(workspace.bootstrap_status, WorkspaceBootstrapStatus.FAILED)
            self.assertEqual(workspace.bootstrap_returncode, 7)
            self.assertIn("bad", workspace.bootstrap_stderr)
            self.assertEqual(_metadata(workspace)["bootstrap_status"], "failed")

    def test_bootstrap_timeout_captures_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            command = _python_command('import time; print("started"); time.sleep(2)')
            manager = WorkspaceManager(
                _config(
                    temp_dir,
                    {
                        "VERA_REPO_BOOTSTRAP_COMMAND": command,
                        "VERA_WORKSPACE_BOOTSTRAP_TIMEOUT_SECONDS": "1",
                    },
                )
            )

            with self.assertRaises(WorkspaceBootstrapError) as raised:
                manager.prepare_workspace(_task(), run_bootstrap=True)

            workspace = raised.exception.workspace
            self.assertEqual(workspace.bootstrap_status, WorkspaceBootstrapStatus.TIMED_OUT)
            self.assertIn("timed out", workspace.bootstrap_error)
            self.assertEqual(_metadata(workspace)["bootstrap_status"], "timed_out")

    def test_cleanup_refuses_paths_outside_root_and_removes_managed_workspace(self):
        with tempfile.TemporaryDirectory() as root_dir, tempfile.TemporaryDirectory() as outside_dir:
            manager = WorkspaceManager(_config(root_dir))
            workspace = manager.prepare_workspace(_task(), run_bootstrap=False)

            with self.assertRaises(WorkspaceError):
                manager.cleanup_workspace_path(Path(outside_dir))

            self.assertTrue(Path(outside_dir).exists())
            manager.cleanup_workspace(workspace)
            self.assertFalse(workspace.path.exists())

    def test_cleanup_refuses_symlink_inside_root(self):
        with tempfile.TemporaryDirectory() as root_dir, tempfile.TemporaryDirectory() as outside_dir:
            root = Path(root_dir).resolve()
            link = root / "link-workspace"
            link.symlink_to(Path(outside_dir), target_is_directory=True)
            manager = WorkspaceManager(_config(root))

            with self.assertRaises(WorkspaceError):
                manager.cleanup_workspace_path(link)

            self.assertTrue(Path(outside_dir).is_dir())


def _config(temp_dir, extra_env=None):
    env = {"VERA_WORKSPACE_ROOT": str(temp_dir)}
    if extra_env:
        env.update(extra_env)
    return HarnessConfig.from_env(env, require_secrets=False)


def _task():
    return TelegramTask.from_message(chat_id=1, user_id=2, message_id=3, text="work")


def _metadata(workspace):
    return json.loads(workspace.metadata_path.read_text(encoding="utf-8"))


def _python_command(code):
    return "{} -c {}".format(shlex.quote(sys.executable), shlex.quote(code))


if __name__ == "__main__":
    unittest.main()
