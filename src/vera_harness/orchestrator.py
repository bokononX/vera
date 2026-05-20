"""Top-level orchestration for the Vera harness scaffold."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from .codex import CodexInvocation, CodexRuntimePlanner
from .config import HarnessConfig
from .models import HarnessRun, TelegramTask, Workspace
from .prompt import PromptPolicy, build_prompt_policy
from .telegram import TelegramIntake, TelegramIntakeOutcome, TelegramLongPollingIntake, TelegramUpdateStatus
from .workspace import WorkspaceManager


@dataclass(frozen=True)
class DryRunResult:
    task: TelegramTask
    workspace: Workspace
    harness_run: HarnessRun
    policy: PromptPolicy
    invocation: CodexInvocation


@dataclass(frozen=True)
class PollOnceResult:
    outcomes: Tuple[TelegramIntakeOutcome, ...]
    queued_tasks: Tuple[TelegramTask, ...]


class VeraHarness:
    """Coordinates intake, workspace planning, policy prompts, and Codex plans."""

    def __init__(self, config: HarnessConfig) -> None:
        self._config = config
        self._telegram = TelegramIntake(config)
        self._workspaces = WorkspaceManager(config)
        self._codex = CodexRuntimePlanner(config)

    def dry_run_task(
        self,
        text: str,
        chat_id: int,
        user_id: int,
        message_id: int,
        username: Optional[str] = None,
        create_workspace: bool = True,
    ) -> DryRunResult:
        task = self._telegram.task_from_message(
            chat_id=chat_id,
            user_id=user_id,
            message_id=message_id,
            text=text,
            username=username,
        )
        workspace = self._workspaces.workspace_for_task(task, create=create_workspace)
        policy = build_prompt_policy(task)
        harness_run = HarnessRun(
            run_id="dry-run-{}".format(task.task_id),
            task=task,
            workspace=workspace,
            max_turns=self._config.max_turns,
            dry_run=True,
        )
        invocation = self._codex.plan(workspace, policy.render_prompt())
        return DryRunResult(
            task=task,
            workspace=workspace,
            harness_run=harness_run,
            policy=policy,
            invocation=invocation,
        )

    def poll_telegram_once(self) -> PollOnceResult:
        """Poll Telegram once and queue accepted tasks for future orchestration."""

        polling_intake = TelegramLongPollingIntake(self._config)
        outcomes = polling_intake.poll_once()
        return PollOnceResult(
            outcomes=outcomes,
            queued_tasks=polling_intake.queue.queued_tasks(),
        )


def format_dry_run(result: DryRunResult) -> str:
    invocation = result.invocation
    repo_clone = invocation.repo_clone_command.display if invocation.repo_clone_command else "not configured"
    repo_bootstrap = (
        invocation.repo_bootstrap_command.display if invocation.repo_bootstrap_command else "not configured"
    )
    policy_lines = "\n".join("- {}".format(line) for line in result.policy.summary_lines)

    return "\n".join(
        [
            "Vera harness dry-run",
            "task_id: {}".format(result.task.task_id),
            "task_summary: {}".format(result.task.summary()),
            "workspace_path: {}".format(result.workspace.path),
            "workspace_created: {}".format(str(result.workspace.created).lower()),
            "workspace_reused: {}".format(str(result.workspace.reused).lower()),
            "workspace_reuse_policy: {}".format(result.workspace.reuse_policy.value),
            "workspace_metadata_path: {}".format(result.workspace.metadata_path),
            "workspace_bootstrap_status: {}".format(result.workspace.bootstrap_status.value),
            "",
            "prompt_policy_summary:",
            policy_lines,
            "",
            "planned_codex_invocation:",
            "command: {}".format(invocation.display_command),
            "workspace: {}".format(invocation.workspace_path),
            "max_turns: {}".format(invocation.max_turns),
            "turn_timeout_seconds: {}".format(invocation.turn_timeout_seconds),
            "run_timeout_seconds: {}".format(invocation.run_timeout_seconds),
            "approval_policy: {}".format(invocation.approval_policy),
            "sandbox_mode: {}".format(invocation.sandbox_mode),
            "repo_clone_command: {}".format(repo_clone),
            "repo_bootstrap_command: {}".format(repo_bootstrap),
            "",
            "codex_launch: skipped (dry run)",
            "telegram_network_calls: skipped (dry run)",
        ]
    )


def format_poll_once(result: PollOnceResult) -> str:
    counts = {
        status: sum(1 for outcome in result.outcomes if outcome.status == status)
        for status in TelegramUpdateStatus
    }
    return "\n".join(
        [
            "Vera Telegram poll",
            "updates_seen: {}".format(len(result.outcomes)),
            "accepted: {}".format(counts[TelegramUpdateStatus.ACCEPTED]),
            "rejected: {}".format(counts[TelegramUpdateStatus.REJECTED]),
            "blocked: {}".format(counts[TelegramUpdateStatus.BLOCKED]),
            "duplicates: {}".format(counts[TelegramUpdateStatus.DUPLICATE]),
            "ignored: {}".format(counts[TelegramUpdateStatus.IGNORED]),
            "queued_tasks: {}".format(len(result.queued_tasks)),
            "codex_launch: skipped (queued only)",
        ]
    )
