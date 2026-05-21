import json
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
from vera_harness.orchestrator import (
    FakeCodexRuntime,
    VeraHarness,
    format_dry_run,
    format_telegram_chat_loop,
    format_telegram_loop,
)
from vera_harness.state import JsonRunStateStore
from vera_harness.telegram import TelegramLongPollingIntake, TelegramUpdateStore


MEMORY_FIXTURE = Path(__file__).parent / "fixtures" / "user_memory"


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

    def test_prompt_build_includes_user_memory_and_persists_audit_refs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = FakeCodexRuntime()
            config = _config(
                temp_dir,
                {
                    "VERA_USER_MEMORY_ROOT": str(MEMORY_FIXTURE),
                },
            )
            task = TelegramTask.from_message(
                chat_id=1,
                user_id=2,
                message_id=4,
                text="Implement Herald user memory retrieval with concise engineering status.",
            )
            harness = VeraHarness(config, runtime=runtime)

            result = harness.run_task(task, run_bootstrap=False)

            self.assertEqual(result.harness_run.status, HarnessRunStatus.COMPLETED)
            self.assertIn("## User Memory Context", result.invocation.prompt)
            self.assertIn("Direct Engineering Updates", result.invocation.prompt)
            state = JsonRunStateStore(config.run_state_path).run_for_task(task.task_id)
            self.assertTrue(
                any("wiki/preferences/direct-engineering-updates.md" in item for item in state.memory_pages_used)
            )
            prompt_event = next(event for event in result.events if event.type == TaskEventType.PROMPT_BUILT)
            self.assertTrue(
                any("wiki/preferences/direct-engineering-updates.md" in item for item in prompt_event.payload["user_memory_pages"])
            )

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


class TelegramChatSessionTests(unittest.TestCase):
    def test_chat_poll_returns_assistant_response_and_reuses_thread_for_followup(self):
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
                    _message_update(update_id=80, chat_id=100, user_id=200, message_id=300, text="hello"),
                    _message_update(update_id=81, chat_id=100, user_id=200, message_id=301, text="what did I just say?"),
                )
            )
            intake = TelegramLongPollingIntake(
                config,
                api=api,
                store=TelegramUpdateStore(config.telegram_state_path),
                send_accepted_reply=False,
            )
            runtime = ScriptedChatRuntime(("Hello from persistent Codex.", "You said hello."))
            harness = VeraHarness(config, chat_runtime_factory=lambda resume_thread_id: runtime)

            result = harness.run_telegram_chat_poll_once(
                polling_intake=intake,
                run_bootstrap=False,
            )
            output = format_telegram_chat_loop(result)

            self.assertEqual([message["text"] for message in api.sent_messages], ["Hello from persistent Codex.", "You said hello."])
            self.assertEqual(runtime.calls, 2)
            self.assertIn("User-facing assistant name: Vera", runtime.prompts[0])
            self.assertIn("Assistant identity:", runtime.prompts[1])
            self.assertIn("Telegram message:\nwhat did I just say?", runtime.prompts[1])
            self.assertEqual(result.chat_turns[0].session.session_id, result.chat_turns[1].session.session_id)
            self.assertEqual(result.chat_turns[1].session.thread_id, "thread-1")
            self.assertEqual(result.chat_turns[1].session.turns_completed, 2)
            self.assertIn("assistant_response: You said hello.", output)
            state = Path(config.chat_session_state_path).read_text(encoding="utf-8")
            self.assertIn("thread-1", state)
            self.assertIn("telegram-chat-100-user-200", state)

    def test_who_are_you_returns_assistant_identity_without_codex_leak(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                {
                    "VERA_ALLOWED_CHAT_IDS": "100",
                    "VERA_ALLOWED_USER_IDS": "200",
                },
            )
            api = FakeTelegramApi(
                (_message_update(update_id=83, chat_id=100, user_id=200, message_id=300, text="who are you?"),)
            )
            intake = TelegramLongPollingIntake(
                config,
                api=api,
                store=TelegramUpdateStore(config.telegram_state_path),
                send_accepted_reply=False,
            )
            runtime = ScriptedChatRuntime(("I am Codex, a coding-focused AI assistant.",))
            harness = VeraHarness(config, chat_runtime_factory=lambda resume_thread_id: runtime)

            result = harness.run_telegram_chat_poll_once(
                polling_intake=intake,
                run_bootstrap=False,
            )

            self.assertEqual(runtime.calls, 0)
            self.assertEqual(len(result.chat_turns), 0)
            response = api.sent_messages[0]["text"]
            self.assertIn("I'm Vera", response)
            self.assertIn("My mission is to help the owner think clearly", response)
            self.assertNotIn("I'm Codex", response)
            self.assertNotIn("coding-focused AI assistant", response)

    def test_runtime_identity_question_preserves_codex_transparency(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                {
                    "VERA_ALLOWED_CHAT_IDS": "100",
                    "VERA_ALLOWED_USER_IDS": "200",
                },
            )
            api = FakeTelegramApi(
                (_message_update(update_id=84, chat_id=100, user_id=200, message_id=300, text="are you Codex?"),)
            )
            intake = TelegramLongPollingIntake(
                config,
                api=api,
                store=TelegramUpdateStore(config.telegram_state_path),
                send_accepted_reply=False,
            )
            runtime = ScriptedChatRuntime(("unused",))
            harness = VeraHarness(config, chat_runtime_factory=lambda resume_thread_id: runtime)

            harness.run_telegram_chat_poll_once(
                polling_intake=intake,
                run_bootstrap=False,
            )

            response = api.sent_messages[0]["text"]
            self.assertIn("I'm Vera", response)
            self.assertIn("Codex/OpenAI tooling is the runtime layer", response)
            self.assertIn("not my normal user-facing identity", response)

    def test_assistant_identity_interview_updates_future_prompt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                {
                    "VERA_ALLOWED_CHAT_IDS": "100",
                    "VERA_ALLOWED_USER_IDS": "200",
                },
            )
            texts = (
                "/assistant identity",
                "Mira",
                "a focused thinking partner",
                "Help Victor reason clearly and remember durable context.",
                "truth; agency; low drama",
                "brief, precise, and candid",
                "Never claim to be human; ask before irreversible actions",
                "A configured assistant for the owner.",
                "Proactive about risks; quiet when scope is narrow",
                "Use owner profile only for the configured owner",
                "Say Mira is powered by Codex/OpenAI when asked",
                "confirm",
                "Use the new assistant identity on this task.",
            )
            api = FakeTelegramApi(_message_updates(190, texts))
            intake = TelegramLongPollingIntake(
                config,
                api=api,
                store=TelegramUpdateStore(config.telegram_state_path),
                send_accepted_reply=False,
            )
            runtime = ScriptedChatRuntime(("Mira-shaped response.",))
            harness = VeraHarness(config, chat_runtime_factory=lambda resume_thread_id: runtime)

            result = harness.run_telegram_chat_poll_once(
                polling_intake=intake,
                run_bootstrap=False,
            )

            self.assertEqual(runtime.calls, 1)
            self.assertEqual(len(result.chat_turns), 1)
            self.assertIn("Assistant identity 1/10", api.sent_messages[0]["text"])
            self.assertIn("Here is the assistant identity profile", api.sent_messages[10]["text"])
            self.assertIn("Saved assistant identity for Mira", api.sent_messages[11]["text"])
            self.assertEqual(api.sent_messages[12]["text"], "Mira-shaped response.")
            self.assertIn("User-facing assistant name: Mira", runtime.prompts[0])
            self.assertIn("Mission: Help Victor reason clearly", runtime.prompts[0])
            self.assertIn("Communication principles: brief, precise, and candid", runtime.prompts[0])

            profile = json.loads(Path(config.assistant_identity_path).read_text(encoding="utf-8"))
            self.assertEqual(profile["name"], "Mira")
            self.assertEqual(profile["core_values"], ["truth", "agency", "low drama"])
            self.assertIn("Codex/OpenAI", profile["transparency_rules"][0])

    def test_owner_chat_session_receives_owner_profile_prompt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                {
                    "VERA_ALLOWED_CHAT_IDS": "100",
                    "VERA_ALLOWED_USER_IDS": "200,201",
                },
                owner_config={
                    "user_id": 200,
                    "display_name": "Vera Owner",
                    "communication_style": ["direct and concrete"],
                    "escalation_boundaries": ["require approval before irreversible actions"],
                },
            )
            runtime = ScriptedChatRuntime(("Owner-shaped response.",))
            harness = VeraHarness(config, chat_runtime_factory=lambda resume_thread_id: runtime)

            session, run_result = harness.run_chat_turn(
                TelegramTask.from_message(
                    chat_id=100,
                    user_id=200,
                    message_id=300,
                    text="hello",
                ),
                run_bootstrap=False,
            )

            self.assertEqual(run_result.assistant_response, "Owner-shaped response.")
            self.assertEqual(session.session_id, "telegram-chat-100-user-200")
            self.assertIn("Owner relationship:", runtime.prompts[0])
            self.assertIn("direct and concrete", runtime.prompts[0])
            self.assertIn("not an authorization override", runtime.prompts[0])

    def test_authorized_non_owner_chat_session_uses_fallback_prompt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                {
                    "VERA_ALLOWED_CHAT_IDS": "100",
                    "VERA_ALLOWED_USER_IDS": "200,201",
                },
                owner_config={
                    "user_id": 200,
                    "display_name": "Vera Owner",
                    "communication_style": ["direct and concrete"],
                },
            )
            runtime = ScriptedChatRuntime(("Plain response.",))
            harness = VeraHarness(config, chat_runtime_factory=lambda resume_thread_id: runtime)

            harness.run_chat_turn(
                TelegramTask.from_message(
                    chat_id=100,
                    user_id=201,
                    message_id=300,
                    text="hello",
                ),
                run_bootstrap=False,
            )

            self.assertNotIn("Owner relationship:", runtime.prompts[0])
            self.assertNotIn("direct and concrete", runtime.prompts[0])

    def test_chat_poll_codex_launch_failure_does_not_send_lifecycle_acceptance(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                {
                    "VERA_ALLOWED_CHAT_IDS": "100",
                    "VERA_ALLOWED_USER_IDS": "200",
                },
            )
            api = FakeTelegramApi((_message_update(update_id=82, chat_id=100, user_id=200, message_id=300, text="hello"),))
            intake = TelegramLongPollingIntake(
                config,
                api=api,
                store=TelegramUpdateStore(config.telegram_state_path),
                send_accepted_reply=False,
            )
            runtime = ScriptedChatRuntime((), status=CodexRunStatus.FAILED, error="failed to launch Codex app-server: missing codex")
            harness = VeraHarness(config, chat_runtime_factory=lambda resume_thread_id: runtime)

            result = harness.run_telegram_chat_poll_once(
                polling_intake=intake,
                run_bootstrap=False,
            )

            self.assertEqual(len(api.sent_messages), 1)
            self.assertNotEqual(api.sent_messages[0]["text"], "Accepted: queued.")
            self.assertIn("Failed: Vera could not complete the task.", api.sent_messages[0]["text"])
            self.assertIn("missing codex", api.sent_messages[0]["text"])
            self.assertEqual(result.chat_turns[0].session.last_status, HarnessRunStatus.FAILED.value)

    def test_identity_interview_from_telegram_confirms_profile_and_updates_future_prompt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                {
                    "VERA_ALLOWED_CHAT_IDS": "100",
                    "VERA_ALLOWED_USER_IDS": "200",
                },
            )
            texts = (
                "/identity",
                "Victor; avoid formal titles.",
                "Optimize for correct, useful progress.",
                "Brief, direct, and enough detail to verify.",
                "Challenge weak assumptions early.",
                "Prefer truth, agency, reversibility, and low drama.",
                "Be careful with personal data and irreversible choices.",
                "Remember stable preferences; do not persist throwaway moods.",
                "confirm",
                "Use my profile on this task.",
            )
            api = FakeTelegramApi(_message_updates(90, texts))
            intake = TelegramLongPollingIntake(
                config,
                api=api,
                store=TelegramUpdateStore(config.telegram_state_path),
                send_accepted_reply=False,
            )
            runtime = ScriptedChatRuntime(("Profile-aware Codex response.",))
            harness = VeraHarness(config, chat_runtime_factory=lambda resume_thread_id: runtime)

            result = harness.run_telegram_chat_poll_once(
                polling_intake=intake,
                run_bootstrap=False,
            )

            self.assertEqual(runtime.calls, 1)
            self.assertEqual(len(result.chat_turns), 1)
            self.assertIn("Identity interview 1/7", api.sent_messages[0]["text"])
            self.assertIn("Here is what I would save", api.sent_messages[7]["text"])
            self.assertIn("Saved 7 confirmed identity/style facts", api.sent_messages[8]["text"])
            self.assertEqual(api.sent_messages[9]["text"], "Profile-aware Codex response.")
            self.assertIn("Confirmed owner profile guidance", runtime.prompts[0])
            self.assertIn("Victor; avoid formal titles.", runtime.prompts[0])
            self.assertIn("Brief, direct, and enough detail to verify.", runtime.prompts[0])

            profile = json.loads(Path(config.identity_profile_path).read_text(encoding="utf-8"))
            self.assertEqual(len(profile["entries"]), 7)
            first_entry = profile["entries"][0]
            self.assertEqual(first_entry["category"], "address_name")
            self.assertEqual(first_entry["source"], "telegram_identity_interview")
            self.assertIn("confidence", first_entry)
            self.assertIn("correction_path", first_entry)
            self.assertIn(308, first_entry["source_message_ids"])

            interview_state = json.loads(
                Path(config.identity_interview_state_path).read_text(encoding="utf-8")
            )
            session = interview_state["sessions"]["telegram-chat-100-user-200"]
            self.assertEqual(session["status"], "completed")
            self.assertGreater(len(session["transcript"]), len(profile["entries"]))

    def test_identity_profile_guidance_is_owner_only_when_owner_is_configured(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                {
                    "VERA_ALLOWED_CHAT_IDS": "100",
                    "VERA_ALLOWED_USER_IDS": "200,201",
                },
                owner_config={
                    "user_id": 200,
                    "display_name": "Vera Owner",
                },
            )
            owner_texts = (
                "/identity",
                "Victor.",
                "Useful and correct.",
                "Detailed when risk is high.",
                "Disagree plainly.",
                "Truth and agency.",
                "Privacy.",
                "Remember durable preferences only.",
                "confirm",
            )
            owner_intake = TelegramLongPollingIntake(
                config,
                api=FakeTelegramApi(_message_updates(130, owner_texts)),
                store=TelegramUpdateStore(config.telegram_state_path),
                send_accepted_reply=False,
            )
            VeraHarness(
                config,
                chat_runtime_factory=lambda resume_thread_id: ScriptedChatRuntime(()),
            ).run_telegram_chat_poll_once(
                polling_intake=owner_intake,
                run_bootstrap=False,
            )

            non_owner_api = FakeTelegramApi(
                _message_updates(150, ("/identity profile",), user_id=201)
            )
            non_owner_runtime = ScriptedChatRuntime(("Generic non-owner response.",))
            non_owner_intake = TelegramLongPollingIntake(
                config,
                api=non_owner_api,
                store=TelegramUpdateStore(config.telegram_state_path),
                send_accepted_reply=False,
            )

            VeraHarness(
                config,
                chat_runtime_factory=lambda resume_thread_id: non_owner_runtime,
            ).run_telegram_chat_poll_once(
                polling_intake=non_owner_intake,
                run_bootstrap=False,
            )

            self.assertEqual(non_owner_runtime.calls, 1)
            self.assertEqual(
                non_owner_api.sent_messages[0]["text"],
                "Generic non-owner response.",
            )
            self.assertNotIn("Confirmed owner profile guidance", non_owner_runtime.prompts[0])
            self.assertNotIn("Victor.", non_owner_runtime.prompts[0])
            self.assertNotIn("Confirmed identity/style facts", non_owner_api.sent_messages[0]["text"])

    def test_identity_interview_can_cancel_without_profile_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                {
                    "VERA_ALLOWED_CHAT_IDS": "100",
                    "VERA_ALLOWED_USER_IDS": "200",
                },
            )
            api = FakeTelegramApi(_message_updates(120, ("/interview", "cancel", "normal task")))
            intake = TelegramLongPollingIntake(
                config,
                api=api,
                store=TelegramUpdateStore(config.telegram_state_path),
                send_accepted_reply=False,
            )
            runtime = ScriptedChatRuntime(("Normal response.",))
            harness = VeraHarness(config, chat_runtime_factory=lambda resume_thread_id: runtime)

            result = harness.run_telegram_chat_poll_once(
                polling_intake=intake,
                run_bootstrap=False,
            )

            self.assertEqual(runtime.calls, 1)
            self.assertEqual(len(result.chat_turns), 1)
            self.assertIn("Identity interview cancelled", api.sent_messages[1]["text"])
            self.assertFalse(Path(config.identity_profile_path).exists())
            self.assertNotIn("Confirmed owner profile guidance", runtime.prompts[0])

    def test_identity_profile_inspection_correction_and_forget(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                {
                    "VERA_ALLOWED_CHAT_IDS": "100",
                    "VERA_ALLOWED_USER_IDS": "200",
                },
            )
            harness = VeraHarness(config, chat_runtime_factory=lambda resume_thread_id: ScriptedChatRuntime(()))
            first_api = FakeTelegramApi(
                _message_updates(
                    150,
                    (
                        "/identity",
                        "Victor.",
                        "Useful and correct.",
                        "Detailed when risk is high.",
                        "Disagree plainly.",
                        "Truth and agency.",
                        "Privacy.",
                        "Remember durable preferences only.",
                        "confirm",
                    ),
                )
            )
            first_intake = TelegramLongPollingIntake(
                config,
                api=first_api,
                store=TelegramUpdateStore(config.telegram_state_path),
                send_accepted_reply=False,
            )
            harness.run_telegram_chat_poll_once(polling_intake=first_intake, run_bootstrap=False)

            second_api = FakeTelegramApi(
                _message_updates(
                    170,
                    (
                        "/identity profile",
                        "change my style preference to concise and direct",
                        "/identity profile",
                        "forget that",
                    ),
                )
            )
            second_intake = TelegramLongPollingIntake(
                config,
                api=second_api,
                store=TelegramUpdateStore(config.telegram_state_path),
                send_accepted_reply=False,
            )

            harness.run_telegram_chat_poll_once(polling_intake=second_intake, run_bootstrap=False)

            self.assertIn("Tone and detail: Detailed when risk is high.", second_api.sent_messages[0]["text"])
            self.assertIn("Updated Tone and detail: concise and direct", second_api.sent_messages[1]["text"])
            self.assertIn("Tone and detail: concise and direct", second_api.sent_messages[2]["text"])
            self.assertIn("Forgot Tone and detail: concise and direct.", second_api.sent_messages[3]["text"])

            profile = json.loads(Path(config.identity_profile_path).read_text(encoding="utf-8"))
            tone_entries = [entry for entry in profile["entries"] if entry["category"] == "tone_detail"]
            self.assertEqual([entry["status"] for entry in tone_entries], ["archived", "archived"])
            self.assertEqual(tone_entries[1]["source"], "telegram_identity_correction")


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


class ScriptedChatRuntime:
    def __init__(self, responses, status=CodexRunStatus.COMPLETED, error=None):
        self._responses = list(responses)
        self._status = status
        self._error = error
        self.calls = 0
        self.prompts = []
        self._thread_id = "thread-1"
        self._turn_id = None
        self._pending_request = None

    @property
    def thread_id(self):
        return self._thread_id

    @property
    def turn_id(self):
        return self._turn_id

    @property
    def pending_request(self):
        return self._pending_request

    def run_turn(self, invocation, on_event=None):
        self.calls += 1
        self.prompts.append(invocation.prompt)
        self._turn_id = "turn-{}".format(self.calls)
        response = self._responses.pop(0) if self._responses else None
        event = CodexRuntimeEvent(
            type=CodexRuntimeEventType.TURN_COMPLETED,
            method="turn/completed",
            message=response,
            thread_id=self._thread_id,
            turn_id=self._turn_id,
        )
        if on_event is not None:
            on_event(event)
        return CodexRunResult(
            status=self._status,
            metadata=CodexSessionMetadata(
                command=invocation.display_command,
                cwd=invocation.workspace_path,
                approval_policy=invocation.approval_policy,
                sandbox_mode=invocation.sandbox_mode,
                thread_id=self._thread_id,
                turn_id=self._turn_id,
            ),
            events=(event,),
            error=self._error,
            assistant_response=response,
        )

    def close(self):
        pass


def _config(temp_dir, extra_env=None, owner_config=None):
    env = {
        "VERA_WORKSPACE_ROOT": temp_dir,
        "VERA_RUN_STATE_PATH": str(Path(temp_dir, "run-state.json")),
        "VERA_CHAT_SESSION_STATE_PATH": str(Path(temp_dir, "chat-sessions.json")),
        "VERA_ASSISTANT_IDENTITY_PATH": str(Path(temp_dir, "assistant-identity.json")),
        "VERA_ASSISTANT_IDENTITY_INTERVIEW_STATE_PATH": str(
            Path(temp_dir, "assistant-identity-interviews.json")
        ),
        "VERA_IDENTITY_PROFILE_PATH": str(Path(temp_dir, "identity-profile.json")),
        "VERA_IDENTITY_INTERVIEW_STATE_PATH": str(Path(temp_dir, "identity-interviews.json")),
        "VERA_TELEGRAM_STATE_PATH": str(Path(temp_dir, "telegram-state.json")),
        "VERA_CODEX_APP_SERVER_COMMAND": "fake-codex app-server",
    }
    if extra_env:
        env.update(extra_env)
    return HarnessConfig.from_env(env, require_secrets=False, owner_config=owner_config)


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


def _message_updates(first_update_id, texts, chat_id=100, user_id=200, first_message_id=300):
    return tuple(
        _message_update(
            update_id=first_update_id + index,
            chat_id=chat_id,
            user_id=user_id,
            message_id=first_message_id + index,
            text=text,
        )
        for index, text in enumerate(texts)
    )


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
