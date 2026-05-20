import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from vera_harness.codex import (
    CodexRunResult,
    CodexRunStatus,
    CodexRuntimeEvent,
    CodexRuntimeEventType,
    CodexSessionMetadata,
)
from vera_harness.config import HarnessConfig
from vera_harness.models import (
    HarnessRunStatus,
    OrchestrationDecision,
    TaskEventType,
    TelegramTask,
)
from vera_harness.orchestrator import FakeCodexRuntime, VeraHarness, format_dry_run, format_telegram_loop
from vera_harness.state import JsonRunStateStore
from vera_harness.telegram import TelegramLongPollingIntake, TelegramUpdateStore


class DryRunOrchestrationTests(unittest.TestCase):
    def test_dry_run_builds_workspace_prompt_fake_runtime_and_final_decision(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                {
                    "VERA_ALLOWED_CHAT_IDS": "100",
                    "VERA_ALLOWED_USER_IDS": "200",
                    "VERA_CODEX_APP_SERVER_COMMAND": "codex app-server --port 0",
                    "VERA_REPO_BOOTSTRAP_COMMAND": "make setup",
                },
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
            self.assertEqual(result.harness_run.status, HarnessRunStatus.COMPLETED)
            self.assertEqual(result.final_decision.action, OrchestrationDecision.COMPLETE)
            self.assertEqual(len(result.turn_results), 1)
            self.assertIn("Faithful representative", result.invocation.prompt)
            self.assertIn("The Place", result.invocation.prompt)
            self.assertIn("Vera", result.invocation.prompt)
            self.assertEqual(result.invocation.display_command, "codex app-server --port 0")
            self.assertIn("workspace_path: {}".format(result.workspace.path), output)
            self.assertIn("prompt_policy_summary:", output)
            self.assertIn("planned_codex_invocation:", output)
            self.assertIn("final_status: completed", output)
            self.assertIn("event_sequence:", output)
            self.assertIn("codex_launch: skipped (fake runtime dry run)", output)
            self.assertIn("telegram_network_calls: skipped (dry run)", output)

    def test_dry_run_rejects_unauthorized_telegram_origin(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                {
                    "VERA_ALLOWED_CHAT_IDS": "100",
                },
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


class OrchestrationLoopTests(unittest.TestCase):
    def test_completion_stops_after_one_turn_and_persists_final_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = ScriptedRuntime((_runtime_result(CodexRunStatus.COMPLETED, "completed"),))
            harness = VeraHarness(_config(temp_dir), runtime=runtime)

            result = harness.run_task(_task(), run_bootstrap=False)

            self.assertEqual(result.harness_run.status, HarnessRunStatus.COMPLETED)
            self.assertEqual(result.final_decision.action, OrchestrationDecision.COMPLETE)
            self.assertEqual(runtime.calls, 1)
            self.assertIn(TaskEventType.RUN_COMPLETED, [event.type for event in result.events])
            state = JsonRunStateStore(Path(temp_dir, "run-state.json")).run_for_task(_task().task_id)
            self.assertEqual(state.status, HarnessRunStatus.COMPLETED)
            self.assertEqual(state.turns_completed, 1)

    def test_continue_marker_runs_until_completion_or_max_turns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = ScriptedRuntime(
                (
                    _runtime_result(CodexRunStatus.COMPLETED, "continue"),
                    _runtime_result(CodexRunStatus.COMPLETED, "completed"),
                )
            )
            harness = VeraHarness(_config(temp_dir, {"VERA_MAX_TURNS": "3"}), runtime=runtime)

            result = harness.run_task(_task(), run_bootstrap=False)

            self.assertEqual(result.harness_run.status, HarnessRunStatus.COMPLETED)
            self.assertEqual(runtime.calls, 2)
            self.assertEqual(
                [event.status for event in result.events if event.type == TaskEventType.DECISION_RECORDED],
                ["continue", "complete"],
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = ScriptedRuntime((_runtime_result(CodexRunStatus.COMPLETED, "continue"),))
            harness = VeraHarness(_config(temp_dir, {"VERA_MAX_TURNS": "1"}), runtime=runtime)

            result = harness.run_task(_task(), run_bootstrap=False)

            self.assertEqual(result.harness_run.status, HarnessRunStatus.FAILED)
            self.assertIn("max turns", result.final_decision.reason)
            self.assertEqual(runtime.calls, 1)

    def test_blocked_approval_input_and_failed_outcomes_stop(self):
        cases = [
            (
                _runtime_result(CodexRunStatus.COMPLETED, "blocked"),
                HarnessRunStatus.BLOCKED,
                OrchestrationDecision.BLOCK,
            ),
            (
                _runtime_result(CodexRunStatus.APPROVAL_REQUIRED, "blocked", error="approval required"),
                HarnessRunStatus.APPROVAL_REQUIRED,
                OrchestrationDecision.BLOCK,
            ),
            (
                _runtime_result(CodexRunStatus.INPUT_REQUIRED, "blocked", error="input required"),
                HarnessRunStatus.INPUT_REQUIRED,
                OrchestrationDecision.BLOCK,
            ),
            (
                _runtime_result(CodexRunStatus.FAILED, "failed", error="model failed"),
                HarnessRunStatus.FAILED,
                OrchestrationDecision.FAIL,
            ),
        ]
        for runtime_result, status, decision in cases:
            with self.subTest(status=status):
                with tempfile.TemporaryDirectory() as temp_dir:
                    runtime = ScriptedRuntime((runtime_result,))
                    harness = VeraHarness(
                        _config(temp_dir, {"VERA_MAX_RETRIES": "0"}),
                        runtime=runtime,
                    )

                    result = harness.run_task(_task(), run_bootstrap=False)

                    self.assertEqual(result.harness_run.status, status)
                    self.assertEqual(result.final_decision.action, decision)
                    self.assertEqual(runtime.calls, 1)

    def test_failed_turn_retries_then_fails_after_retry_budget(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = ScriptedRuntime(
                (
                    _runtime_result(CodexRunStatus.FAILED, "failed", error="transient"),
                    _runtime_result(CodexRunStatus.COMPLETED, "completed"),
                )
            )
            harness = VeraHarness(_config(temp_dir, {"VERA_MAX_RETRIES": "1"}), runtime=runtime)

            result = harness.run_task(_task(), run_bootstrap=False)

            self.assertEqual(result.harness_run.status, HarnessRunStatus.COMPLETED)
            self.assertEqual(runtime.calls, 2)
            self.assertIn(TaskEventType.RETRY_SCHEDULED, [event.type for event in result.events])

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = ScriptedRuntime(
                (
                    _runtime_result(CodexRunStatus.FAILED, "failed", error="first"),
                    _runtime_result(CodexRunStatus.FAILED, "failed", error="second"),
                )
            )
            harness = VeraHarness(_config(temp_dir, {"VERA_MAX_RETRIES": "1"}), runtime=runtime)

            result = harness.run_task(_task(), run_bootstrap=False)

            self.assertEqual(result.harness_run.status, HarnessRunStatus.FAILED)
            self.assertEqual(runtime.calls, 2)
            self.assertEqual(result.final_decision.reason, "second")

    def test_duplicate_active_task_is_not_run_again_after_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir)
            store = JsonRunStateStore(config.run_state_path)
            active = store.create_run(_task(), "existing-run", dry_run=False)
            store.save_run(replace(active, status=HarnessRunStatus.RUNNING))
            runtime = ScriptedRuntime((_runtime_result(CodexRunStatus.COMPLETED, "completed"),))

            result = VeraHarness(config, runtime=runtime).run_task(_task(), run_bootstrap=False)

            self.assertEqual(result.harness_run.status, HarnessRunStatus.DUPLICATE_ACTIVE)
            self.assertEqual(result.duplicate_of.run_id, "existing-run")
            self.assertEqual(runtime.calls, 0)
            self.assertEqual(result.events[0].type, TaskEventType.DUPLICATE_ACTIVE)


class TelegramToCodexSmokeTests(unittest.TestCase):
    def test_fake_telegram_update_runs_workspace_codex_and_status_responses(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                {
                    "VERA_ALLOWED_CHAT_IDS": "100",
                    "VERA_ALLOWED_USER_IDS": "200",
                },
            )
            api = FakeTelegramApi(
                (
                    _message_update(
                        update_id=77,
                        chat_id=100,
                        user_id=200,
                        message_id=300,
                        text="Sensitive task body should not appear in logs",
                    ),
                )
            )
            intake = TelegramLongPollingIntake(
                config,
                api=api,
                store=TelegramUpdateStore(config.telegram_state_path),
            )
            harness = VeraHarness(config)

            result = harness.run_telegram_poll_once(
                polling_intake=intake,
                runtime=FakeCodexRuntime(),
                dry_run=True,
                run_bootstrap=False,
            )
            output = format_telegram_loop(result, title="test smoke")

            self.assertEqual(len(result.task_runs), 1)
            task_result = result.task_runs[0].result
            self.assertEqual(result.task_runs[0].update_id, 77)
            self.assertEqual(task_result.task.task_id, "telegram-100-300")
            self.assertTrue(task_result.workspace.path.is_dir())
            self.assertEqual(task_result.harness_run.status, HarnessRunStatus.COMPLETED)
            self.assertEqual(
                [message["text"] for message in api.sent_messages],
                ["Accepted: queued.", "Started: working on it.", "Completed."],
            )
            self.assertIn("task_id: telegram-100-300", output)
            self.assertIn("telegram_chat_id: 100", output)
            self.assertIn("telegram_update_id: 77", output)
            self.assertIn("workspace_path: {}".format(task_result.workspace.path), output)
            self.assertIn("codex_thread_id: fake-thread", output)
            self.assertIn("codex_turn_id: fake-turn-1", output)
            self.assertIn("final_status: completed", output)
            self.assertIn("telegram_text: Started: working on it.", output)
            self.assertNotIn("Sensitive task body", output)

    def test_failed_runtime_sends_failed_telegram_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                {
                    "VERA_ALLOWED_CHAT_IDS": "100",
                    "VERA_ALLOWED_USER_IDS": "200",
                    "VERA_MAX_RETRIES": "0",
                },
            )
            api = FakeTelegramApi((_message_update(update_id=78),))
            intake = TelegramLongPollingIntake(
                config,
                api=api,
                store=TelegramUpdateStore(config.telegram_state_path),
            )
            runtime = ScriptedRuntime(
                (
                    _runtime_result(
                        CodexRunStatus.FAILED,
                        "failed",
                        error="failed to launch Codex app-server: missing codex",
                    ),
                )
            )

            result = VeraHarness(config).run_telegram_poll_once(
                polling_intake=intake,
                runtime=runtime,
                run_bootstrap=False,
            )
            output = format_telegram_loop(result)

            self.assertEqual(result.task_runs[0].result.harness_run.status, HarnessRunStatus.FAILED)
            self.assertIn("Failed: Vera could not complete the task.", api.sent_messages[-1]["text"])
            self.assertIn("missing codex", api.sent_messages[-1]["text"])
            self.assertIn("final_status: failed", output)
            self.assertIn("failed to launch Codex app-server", output)

    def test_workspace_bootstrap_failure_sends_failed_telegram_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                {
                    "VERA_ALLOWED_CHAT_IDS": "100",
                    "VERA_ALLOWED_USER_IDS": "200",
                    "VERA_REPO_BOOTSTRAP_COMMAND": (
                        "python3 -c \"import sys; sys.stderr.write('bad bootstrap'); sys.exit(7)\""
                    ),
                },
            )
            api = FakeTelegramApi((_message_update(update_id=79),))
            intake = TelegramLongPollingIntake(
                config,
                api=api,
                store=TelegramUpdateStore(config.telegram_state_path),
            )
            runtime = ScriptedRuntime((_runtime_result(CodexRunStatus.COMPLETED, "completed"),))

            result = VeraHarness(config).run_telegram_poll_once(
                polling_intake=intake,
                runtime=runtime,
            )
            output = format_telegram_loop(result)

            self.assertEqual(result.task_runs[0].result.harness_run.status, HarnessRunStatus.FAILED)
            self.assertEqual(runtime.calls, 0)
            self.assertIn("Failed: Vera could not complete the task.", api.sent_messages[-1]["text"])
            self.assertIn("bootstrap command failed", api.sent_messages[-1]["text"])
            self.assertIn("final_status: failed", output)
            self.assertIn("bootstrap command failed", output)


class ScriptedRuntime:
    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    def run_turn(self, invocation, on_event=None):
        self.calls += 1
        result = self._results.pop(0) if self._results else _runtime_result(CodexRunStatus.COMPLETED, "completed")
        for event in result.events:
            if on_event is not None:
                on_event(event)
        return result


def _config(temp_dir, extra_env=None):
    env = {
        "VERA_WORKSPACE_ROOT": temp_dir,
        "VERA_RUN_STATE_PATH": str(Path(temp_dir, "run-state.json")),
        "VERA_TELEGRAM_STATE_PATH": str(Path(temp_dir, "telegram-state.json")),
        "VERA_CODEX_APP_SERVER_COMMAND": "fake-codex app-server",
    }
    if extra_env:
        env.update(extra_env)
    return HarnessConfig.from_env(env, require_secrets=False)


def _task():
    return TelegramTask.from_message(chat_id=1, user_id=2, message_id=3, text="work")


class FakeTelegramApi:
    def __init__(self, updates):
        self._updates = tuple(updates)
        self.sent_messages = []

    def get_updates(self, offset, timeout):
        return tuple(
            update
            for update in self._updates
            if offset is None or update["update_id"] >= offset
        )

    def send_message(self, chat_id, text, reply_to_message_id=None):
        self.sent_messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_to_message_id": reply_to_message_id,
            }
        )
        return {"message_id": len(self.sent_messages)}


def _message_update(update_id, chat_id=100, user_id=200, message_id=300, text="Do the work"):
    return {
        "update_id": update_id,
        "message": {
            "message_id": message_id,
            "chat": {"id": chat_id},
            "from": {"id": user_id, "username": "vera_user"},
            "text": text,
        },
    }


def _runtime_result(status, marker, error=None):
    event = CodexRuntimeEvent(
        type=CodexRuntimeEventType.NOTIFICATION,
        method="fake/turn",
        message="VERA_TASK_STATUS: {}\nVERA_STATUS_REASON: scripted".format(marker),
    )
    return CodexRunResult(
        status=status,
        metadata=CodexSessionMetadata(
            command="fake-codex app-server",
            cwd=Path("/tmp/fake-workspace"),
            approval_policy="on-request",
            sandbox_mode="read-only",
        ),
        events=(event,),
        error=error,
        elapsed_seconds=0.0,
    )


if __name__ == "__main__":
    unittest.main()
