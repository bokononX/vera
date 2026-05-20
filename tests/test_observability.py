import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from vera_harness.config import HarnessConfig
from vera_harness.models import HarnessRunStatus, TaskEvent, TaskEventType, TelegramTask
from vera_harness.observability import (
    ConsoleEventCategory,
    JsonConsoleEventLog,
    JsonObservabilityProvider,
    TelemetryState,
    console_event_from_task_event,
    budget_from_sources,
    format_budget_bar,
    redact_mapping,
    select_focused_agent,
)
from vera_harness.state import JsonRunStateStore


class ObservabilityProviderTests(unittest.TestCase):
    def test_provider_projects_run_state_events_budget_and_focus(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                {
                    "VERA_MONTHLY_BUDGET_USD": "250",
                    "VERA_PROJECT_BUDGET_USD": "50",
                },
            )
            task = TelegramTask.from_message(
                chat_id=100,
                user_id=200,
                message_id=300,
                text="Private work request",
            )
            store = JsonRunStateStore(config.run_state_path)
            state = store.create_run(task, "run-1", dry_run=False)
            store.save_run(
                replace(
                    state,
                    status=HarnessRunStatus.RUNNING,
                    turns_completed=1,
                    workspace_path=str(Path(temp_dir, "workspace")),
                )
            )
            JsonConsoleEventLog(config.event_log_path).append_task_event(
                TaskEvent(
                    type=TaskEventType.DECISION_RECORDED,
                    task_id=task.task_id,
                    run_id="run-1",
                    status="continue",
                    message="continue with API key sk-test-secret-123456",
                    turn_number=1,
                    payload={"total_tokens": 42, "cost_usd": 0.12},
                )
            )

            snapshot = JsonObservabilityProvider.from_config(config, env={}).snapshot()

        self.assertEqual(len(snapshot.agents), 1)
        self.assertEqual(snapshot.focused_agent_id, "telegram-100-300:run-1")
        self.assertEqual(snapshot.agents[0].source_channel, "telegram")
        self.assertEqual(snapshot.agents[0].current_turn, 2)
        self.assertEqual(snapshot.agents[0].token_usage, 42)
        self.assertEqual(snapshot.agents[0].budget_usd, 0.12)
        self.assertEqual(snapshot.budget.rate_limits.state, TelemetryState.UNAVAILABLE)
        self.assertEqual(snapshot.budget.thresholds.monthly_budget_usd, 250.0)
        self.assertIn("<redacted secret>", snapshot.events[0].summary)
        self.assertNotIn("sk-test-secret", snapshot.focused.last_turn_summary)

    def test_select_focus_prefers_requested_then_active_then_first(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir)
            store = JsonRunStateStore(config.run_state_path)
            completed_task = TelegramTask.from_message(1, 2, 3, "done")
            active_task = TelegramTask.from_message(1, 2, 4, "active")
            completed = store.create_run(completed_task, "run-done", dry_run=False)
            active = store.create_run(active_task, "run-active", dry_run=False)
            store.save_run(replace(completed, status=HarnessRunStatus.COMPLETED, turns_completed=1))
            store.save_run(replace(active, status=HarnessRunStatus.RUNNING, turns_completed=0))
            agents = JsonObservabilityProvider.from_config(config, env={}).snapshot().agents

        self.assertEqual(select_focused_agent(agents).task_id, active_task.task_id)
        self.assertEqual(
            select_focused_agent(agents, requested_agent_id=completed_task.task_id).task_id,
            completed_task.task_id,
        )


class BudgetTelemetryTests(unittest.TestCase):
    def test_budget_fallback_states_and_snapshot_values(self):
        unavailable = budget_from_sources(env={})

        self.assertEqual(unavailable.rate_limits.state, TelemetryState.UNAVAILABLE)
        self.assertEqual(unavailable.usage.state, TelemetryState.UNAVAILABLE)
        self.assertEqual(unavailable.thresholds.state, TelemetryState.UNKNOWN)
        self.assertIn("unavailable", format_budget_bar(unavailable))

        unknown = budget_from_sources(env={"OPENAI_API_KEY": "sk-test-secret-123456"})
        self.assertEqual(unknown.rate_limits.state, TelemetryState.UNKNOWN)
        self.assertEqual(unknown.usage.state, TelemetryState.UNAVAILABLE)

        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_path = Path(temp_dir, "budget.json")
            snapshot_path.write_text(
                json.dumps(
                    {
                        "rate_limits": {
                            "remaining_requests": 17,
                            "remaining_tokens": 1234,
                            "reset_requests_at": "2026-05-20T18:00:00Z",
                            "reset_tokens_at": "2026-05-20T18:05:00Z",
                        },
                        "usage": {
                            "daily_usd": 1.25,
                            "weekly_usd": 9.5,
                            "monthly_usd": 31.0,
                            "monthly_tokens": 10000,
                        },
                    }
                ),
                encoding="utf-8",
            )

            available = budget_from_sources(snapshot_path=snapshot_path, env={})

        self.assertEqual(available.rate_limits.state, TelemetryState.AVAILABLE)
        self.assertEqual(available.rate_limits.remaining_requests, 17)
        self.assertEqual(available.usage.monthly_usd, 31.0)
        self.assertIn("17 req", format_budget_bar(available))


class RedactionTests(unittest.TestCase):
    def test_redacts_secrets_and_private_message_bodies(self):
        redacted = redact_mapping(
            {
                "telegram_message_text": "Please use sk-test-secret-123456",
                "authorization": "Bearer verysecretvalue",
                "nested": {"api_key": "sk-nested-secret-123456"},
                "safe": "remaining tokens are 100",
            }
        )

        rendered = json.dumps(redacted, sort_keys=True)
        self.assertIn("<redacted private message>", rendered)
        self.assertIn("<redacted secret>", rendered)
        self.assertIn("remaining tokens are 100", rendered)
        self.assertNotIn("sk-test-secret", rendered)
        self.assertNotIn("verysecretvalue", rendered)

    def test_tool_runtime_events_are_classified_as_tool_events(self):
        event = TaskEvent(
            type=TaskEventType.CODEX_RUNTIME_EVENT,
            task_id="telegram-1-2",
            run_id="run-1",
            payload={"method": "item/tool/requestUserInput"},
        )

        console_event = console_event_from_task_event(event)

        self.assertEqual(console_event.category, ConsoleEventCategory.TOOL)


def _config(temp_dir, extra_env=None):
    env = {
        "VERA_WORKSPACE_ROOT": str(Path(temp_dir, "workspaces")),
        "VERA_RUN_STATE_PATH": str(Path(temp_dir, "run-state.json")),
        "VERA_EVENT_LOG_PATH": str(Path(temp_dir, "events.jsonl")),
        "VERA_TELEGRAM_STATE_PATH": str(Path(temp_dir, "telegram-state.json")),
        "VERA_CODEX_APP_SERVER_COMMAND": "fake-codex app-server",
    }
    if extra_env:
        env.update(extra_env)
    return HarnessConfig.from_env(env, require_secrets=False)


if __name__ == "__main__":
    unittest.main()
