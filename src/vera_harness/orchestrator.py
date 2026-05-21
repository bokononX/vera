"""Top-level orchestration for the Vera harness."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, replace
from typing import Callable, Dict, List, Optional, Protocol, Tuple

from .chat import JsonTelegramChatSessionStore, TelegramChatSession

from .codex import (
    CodexAppServerRuntime,
    CodexAppServerSession,
    CodexInvocation,
    CodexPendingRequest,
    CodexRunResult,
    CodexRunStatus,
    CodexRuntimeEvent,
    CodexRuntimeEventType,
    CodexRuntimePlanner,
    CodexSessionMetadata,
)
from .config import HarnessConfig
from .models import (
    HarnessRun,
    HarnessRunStatus,
    OrchestrationDecision,
    OwnerProfile,
    RunState,
    TaskEvent,
    TaskEventType,
    TelegramTask,
    Workspace,
    WorkspaceReusePolicy,
)
from .prompt import PromptPolicy, build_prompt_policy
from .state import JsonRunStateStore
from .telegram import (
    TelegramIntake,
    TelegramIntakeOutcome,
    TelegramLongPollingIntake,
    TelegramTaskStatus,
    TelegramUpdateStatus,
    format_telegram_status,
)
from .workspace import WorkspaceBootstrapError, WorkspaceManager


RuntimeEventCallback = Callable[[CodexRuntimeEvent], None]
TaskEventCallback = Callable[[TaskEvent], None]


class CodexRuntime(Protocol):
    """Runtime boundary used by the orchestrator."""

    def run_turn(
        self,
        invocation: CodexInvocation,
        on_event: Optional[RuntimeEventCallback] = None,
    ) -> CodexRunResult:
        """Run one Codex turn."""


class CodexChatRuntime(Protocol):
    """Persistent runtime boundary used by Telegram chat mode."""

    @property
    def thread_id(self) -> Optional[str]:
        """Return the active Codex thread id if known."""

    @property
    def turn_id(self) -> Optional[str]:
        """Return the active or last Codex turn id if known."""

    @property
    def pending_request(self) -> Optional[CodexPendingRequest]:
        """Return a pending Codex input/approval request if one is blocked."""

    def run_turn(
        self,
        invocation: CodexInvocation,
        on_event: Optional[RuntimeEventCallback] = None,
    ) -> CodexRunResult:
        """Run or resume one Codex turn in the persistent session."""

    def close(self) -> None:
        """Close the persistent app-server process."""


ChatRuntimeFactory = Callable[[Optional[str]], CodexChatRuntime]


class RunStateStore(Protocol):
    """Minimal persistence boundary for orchestration run state."""

    def active_run_for_task(self, task_id: str) -> Optional[RunState]:
        """Return an active run for a task if one exists."""

    def create_run(self, task: TelegramTask, run_id: str, dry_run: bool) -> RunState:
        """Create a new run unless an active one already exists."""

    def save_run(self, state: RunState) -> RunState:
        """Persist a run-state update."""


class ChatSessionStore(Protocol):
    """Minimal persistence boundary for Telegram chat sessions."""

    def get_or_create(self, task: TelegramTask) -> TelegramChatSession:
        """Return an existing chat session for this Telegram source or create one."""

    def save(self, session: TelegramChatSession) -> TelegramChatSession:
        """Persist a chat-session update."""


@dataclass(frozen=True)
class TurnDecision:
    action: OrchestrationDecision
    status: HarnessRunStatus
    reason: str
    marker: Optional[str] = None


@dataclass(frozen=True)
class TaskRunResult:
    task: TelegramTask
    workspace: Workspace
    harness_run: HarnessRun
    policy: Optional[PromptPolicy]
    invocation: Optional[CodexInvocation]
    events: Tuple[TaskEvent, ...]
    turn_results: Tuple[CodexRunResult, ...]
    final_decision: TurnDecision
    duplicate_of: Optional[RunState] = None


DryRunResult = TaskRunResult


@dataclass(frozen=True)
class PollOnceResult:
    outcomes: Tuple[TelegramIntakeOutcome, ...]
    queued_tasks: Tuple[TelegramTask, ...]


@dataclass(frozen=True)
class TelegramStatusDelivery:
    """A Telegram status message emitted for a task lifecycle transition."""

    update_id: Optional[int]
    task_id: Optional[str]
    chat_id: Optional[int]
    message_id: Optional[int]
    status: TelegramTaskStatus
    text: str
    reason: Optional[str] = None


@dataclass(frozen=True)
class TelegramTaskRunResult:
    """A task run correlated back to the Telegram update that produced it."""

    update_id: Optional[int]
    result: TaskRunResult


@dataclass(frozen=True)
class TelegramLoopResult:
    """One Telegram polling cycle plus any Codex task runs it produced."""

    poll_result: PollOnceResult
    task_runs: Tuple[TelegramTaskRunResult, ...]
    status_deliveries: Tuple[TelegramStatusDelivery, ...]


@dataclass(frozen=True)
class TelegramChatResponseDelivery:
    """A user-facing Telegram chat response emitted after a Codex turn."""

    update_id: Optional[int]
    session_id: str
    task_id: str
    chat_id: int
    message_id: int
    text: str
    status: TelegramTaskStatus


@dataclass(frozen=True)
class TelegramChatTurnResult:
    """A Codex chat turn correlated back to the Telegram update that produced it."""

    update_id: Optional[int]
    task: TelegramTask
    session: TelegramChatSession
    run_result: CodexRunResult


@dataclass(frozen=True)
class TelegramChatLoopResult:
    """One Telegram polling cycle plus persistent Codex chat turns."""

    poll_result: PollOnceResult
    chat_turns: Tuple[TelegramChatTurnResult, ...]
    response_deliveries: Tuple[TelegramChatResponseDelivery, ...]


class VeraHarness:
    """Coordinates intake, workspace lifecycle, policy prompts, and Codex turns."""

    def __init__(
        self,
        config: HarnessConfig,
        runtime: Optional[CodexRuntime] = None,
        run_store: Optional[RunStateStore] = None,
        chat_store: Optional[ChatSessionStore] = None,
        chat_runtime_factory: Optional[ChatRuntimeFactory] = None,
        on_event: Optional[TaskEventCallback] = None,
    ) -> None:
        self._config = config
        self._telegram = TelegramIntake(config)
        self._workspaces = WorkspaceManager(config)
        self._planner = CodexRuntimePlanner(config)
        self._runtime = runtime or CodexAppServerRuntime(config)
        self._run_store = run_store or JsonRunStateStore(config.run_state_path)
        self._chat_store = chat_store or JsonTelegramChatSessionStore(config.chat_session_state_path)
        self._chat_runtime_factory = chat_runtime_factory or (
            lambda resume_thread_id: CodexAppServerSession(config, resume_thread_id=resume_thread_id)
        )
        self._chat_runtimes: Dict[str, CodexChatRuntime] = {}
        self._on_event = on_event

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
        return self.run_task(
            task,
            dry_run=True,
            create_workspace=create_workspace,
            run_bootstrap=False,
            runtime=FakeCodexRuntime(),
        )

    def run_task(
        self,
        task: TelegramTask,
        dry_run: bool = False,
        create_workspace: bool = True,
        workspace_policy: WorkspaceReusePolicy = WorkspaceReusePolicy.REUSE,
        run_bootstrap: bool = True,
        runtime: Optional[CodexRuntime] = None,
    ) -> TaskRunResult:
        """Run a normalized task through the supervised Codex loop."""

        selected_runtime = runtime or self._runtime
        events: List[TaskEvent] = []
        turn_results: List[CodexRunResult] = []
        run_id = _run_id(task, dry_run=dry_run)

        active = self._run_store.active_run_for_task(task.task_id)
        workspace = self._workspaces.workspace_for_task(task, create=False)
        if active is not None:
            decision = TurnDecision(
                action=OrchestrationDecision.BLOCK,
                status=HarnessRunStatus.DUPLICATE_ACTIVE,
                reason="active run already exists for task",
            )
            harness_run = HarnessRun(
                run_id=active.run_id,
                task=task,
                workspace=workspace,
                max_turns=self._config.max_turns,
                status=HarnessRunStatus.DUPLICATE_ACTIVE,
                dry_run=dry_run,
            )
            self._emit(
                events,
                TaskEventType.DUPLICATE_ACTIVE,
                task,
                active.run_id,
                status=active.status.value,
                message=decision.reason,
                payload={"existing_run_id": active.run_id},
            )
            return TaskRunResult(
                task=task,
                workspace=workspace,
                harness_run=harness_run,
                policy=None,
                invocation=None,
                events=tuple(events),
                turn_results=(),
                final_decision=decision,
                duplicate_of=active,
            )

        state = self._run_store.create_run(task, run_id, dry_run=dry_run)
        harness_run = HarnessRun(
            run_id=state.run_id,
            task=task,
            workspace=workspace,
            max_turns=self._config.max_turns,
            status=HarnessRunStatus.PLANNED,
            dry_run=dry_run,
        )
        self._emit(events, TaskEventType.RUN_STARTED, task, state.run_id, status="planned")

        try:
            workspace = self._workspaces.prepare_workspace(
                task,
                policy=workspace_policy,
                create=create_workspace,
                run_bootstrap=run_bootstrap and not dry_run,
            )
        except WorkspaceBootstrapError as exc:
            workspace = exc.workspace
            decision = TurnDecision(
                action=OrchestrationDecision.FAIL,
                status=HarnessRunStatus.FAILED,
                reason=workspace.bootstrap_error or str(exc),
            )
            state = self._run_store.save_run(
                replace(
                    state,
                    status=HarnessRunStatus.FAILED,
                    workspace_path=str(workspace.path),
                    last_error=decision.reason,
                    last_decision=decision.action.value,
                )
            )
            self._emit(
                events,
                TaskEventType.RUN_FAILED,
                task,
                state.run_id,
                status=decision.status.value,
                message=decision.reason,
            )
            return _result(
                task=task,
                workspace=workspace,
                harness_run=harness_run,
                policy=None,
                invocation=None,
                events=events,
                turn_results=turn_results,
                decision=decision,
            )

        state = self._run_store.save_run(
            replace(
                state,
                status=HarnessRunStatus.RUNNING,
                workspace_path=str(workspace.path),
            )
        )
        harness_run = replace(harness_run, workspace=workspace, status=HarnessRunStatus.RUNNING)
        workspace_payload = {
            "workspace_path": str(workspace.path),
            "created": workspace.created,
            "reused": workspace.reused,
            "reuse_policy": workspace.reuse_policy.value,
        }
        workspace_payload.update(_telegram_identity_payload(task, self._config.owner_profile))
        self._emit(
            events,
            TaskEventType.WORKSPACE_PREPARED,
            task,
            state.run_id,
            status=workspace.bootstrap_status.value,
            payload=workspace_payload,
        )

        policy = build_prompt_policy(task, owner_profile=self._config.owner_profile)
        prompt = policy.render_prompt()
        invocation = self._planner.plan(workspace, prompt)
        self._emit(
            events,
            TaskEventType.PROMPT_BUILT,
            task,
            state.run_id,
            payload={
                "policy_lines": len(policy.summary_lines),
                "owner_profile_applied": policy.owner_profile is not None,
                "session_identity": _session_identity(task, self._config.owner_profile),
            },
        )

        retry_count = 0
        final_decision = TurnDecision(
            action=OrchestrationDecision.FAIL,
            status=HarnessRunStatus.FAILED,
            reason="max turns reached without terminal decision",
        )

        for turn_number in range(1, self._config.max_turns + 1):
            self._emit(
                events,
                TaskEventType.CODEX_TURN_STARTED,
                task,
                state.run_id,
                turn_number=turn_number,
            )
            observed_runtime_events: List[CodexRuntimeEvent] = []

            def on_runtime_event(event: CodexRuntimeEvent) -> None:
                observed_runtime_events.append(event)
                self._emit_runtime_event(events, task, state.run_id, turn_number, event)

            run_result = selected_runtime.run_turn(invocation, on_event=on_runtime_event)
            for runtime_event in run_result.events[len(observed_runtime_events) :]:
                self._emit_runtime_event(events, task, state.run_id, turn_number, runtime_event)

            turn_results.append(run_result)
            self._emit(
                events,
                TaskEventType.CODEX_TURN_COMPLETED,
                task,
                state.run_id,
                status=run_result.status.value,
                turn_number=turn_number,
                message=run_result.error,
            )

            decision = _decide_after_turn(
                run_result,
                turn_number=turn_number,
                max_turns=self._config.max_turns,
                retry_count=retry_count,
                max_retries=self._config.max_retries,
            )
            state = self._run_store.save_run(
                replace(
                    state,
                    status=HarnessRunStatus.RUNNING
                    if decision.action in {OrchestrationDecision.CONTINUE, OrchestrationDecision.RETRY}
                    else decision.status,
                    turns_completed=turn_number,
                    last_error=run_result.error,
                    last_decision=decision.action.value,
                )
            )
            self._emit(
                events,
                TaskEventType.DECISION_RECORDED,
                task,
                state.run_id,
                status=decision.action.value,
                turn_number=turn_number,
                message=decision.reason,
                payload={"marker": decision.marker},
            )

            if decision.action == OrchestrationDecision.CONTINUE:
                continue
            if decision.action == OrchestrationDecision.RETRY:
                retry_count += 1
                self._emit(
                    events,
                    TaskEventType.RETRY_SCHEDULED,
                    task,
                    state.run_id,
                    status="retry",
                    turn_number=turn_number,
                    message=decision.reason,
                    payload={"retry_count": retry_count, "max_retries": self._config.max_retries},
                )
                continue

            final_decision = decision
            break

        if state.status == HarnessRunStatus.RUNNING:
            state = self._run_store.save_run(
                replace(
                    state,
                    status=final_decision.status,
                    last_error=final_decision.reason
                    if final_decision.status == HarnessRunStatus.FAILED
                    else state.last_error,
                    last_decision=final_decision.action.value,
                )
            )

        final_event_type = {
            HarnessRunStatus.COMPLETED: TaskEventType.RUN_COMPLETED,
            HarnessRunStatus.BLOCKED: TaskEventType.RUN_BLOCKED,
            HarnessRunStatus.APPROVAL_REQUIRED: TaskEventType.RUN_BLOCKED,
            HarnessRunStatus.INPUT_REQUIRED: TaskEventType.RUN_BLOCKED,
        }.get(final_decision.status, TaskEventType.RUN_FAILED)
        self._emit(
            events,
            final_event_type,
            task,
            state.run_id,
            status=final_decision.status.value,
            message=final_decision.reason,
        )

        self._apply_workspace_retention(workspace, final_decision.status)

        return _result(
            task=task,
            workspace=workspace,
            harness_run=replace(harness_run, status=final_decision.status),
            policy=policy,
            invocation=invocation,
            events=events,
            turn_results=turn_results,
            decision=final_decision,
        )

    def poll_telegram_once(self) -> PollOnceResult:
        """Poll Telegram once and queue accepted tasks for future orchestration."""

        polling_intake = TelegramLongPollingIntake(self._config)
        outcomes = polling_intake.poll_once()
        return PollOnceResult(
            outcomes=outcomes,
            queued_tasks=polling_intake.queue.queued_tasks(),
        )

    def run_telegram_poll_once(
        self,
        polling_intake: Optional[TelegramLongPollingIntake] = None,
        runtime: Optional[CodexRuntime] = None,
        dry_run: bool = False,
        create_workspace: bool = True,
        workspace_policy: WorkspaceReusePolicy = WorkspaceReusePolicy.REUSE,
        run_bootstrap: bool = True,
    ) -> TelegramLoopResult:
        """Poll Telegram once, run accepted tasks, and send lifecycle statuses."""

        intake = polling_intake or TelegramLongPollingIntake(self._config)
        outcomes = intake.poll_once()
        poll_result = PollOnceResult(
            outcomes=outcomes,
            queued_tasks=intake.queue.queued_tasks(),
        )
        task_update_ids = {
            outcome.task.task_id: outcome.update_id
            for outcome in outcomes
            if outcome.task is not None
        }
        deliveries: List[TelegramStatusDelivery] = []
        task_runs: List[TelegramTaskRunResult] = []

        for outcome in outcomes:
            if outcome.task is not None and outcome.status == TelegramUpdateStatus.ACCEPTED:
                deliveries.append(
                    _status_delivery(
                        outcome.task,
                        outcome.update_id,
                        TelegramTaskStatus.ACCEPTED,
                    )
                )

        for task in intake.queue.drain():
            update_id = task_update_ids.get(task.task_id)
            intake.send_task_status(task, TelegramTaskStatus.STARTED)
            deliveries.append(
                _status_delivery(task, update_id, TelegramTaskStatus.STARTED)
            )
            result = self.run_task(
                task,
                dry_run=dry_run,
                create_workspace=create_workspace,
                workspace_policy=workspace_policy,
                run_bootstrap=run_bootstrap,
                runtime=runtime,
            )
            final_status, reason = _telegram_status_for_result(result)
            intake.send_task_status(task, final_status, reason=reason)
            deliveries.append(
                _status_delivery(task, update_id, final_status, reason=reason)
            )
            task_runs.append(TelegramTaskRunResult(update_id=update_id, result=result))

        return TelegramLoopResult(
            poll_result=poll_result,
            task_runs=tuple(task_runs),
            status_deliveries=tuple(deliveries),
        )

    def run_telegram_chat_poll_once(
        self,
        polling_intake: Optional[TelegramLongPollingIntake] = None,
        create_workspace: bool = True,
        workspace_policy: WorkspaceReusePolicy = WorkspaceReusePolicy.REUSE,
        run_bootstrap: bool = True,
    ) -> TelegramChatLoopResult:
        """Poll Telegram once and pass accepted messages into persistent Codex chat sessions."""

        intake = polling_intake or TelegramLongPollingIntake(
            self._config,
            send_accepted_reply=False,
        )
        outcomes = intake.poll_once()
        poll_result = PollOnceResult(
            outcomes=outcomes,
            queued_tasks=intake.queue.queued_tasks(),
        )
        task_update_ids = {
            outcome.task.task_id: outcome.update_id
            for outcome in outcomes
            if outcome.task is not None
        }
        turns: List[TelegramChatTurnResult] = []
        responses: List[TelegramChatResponseDelivery] = []

        for task in intake.queue.drain():
            update_id = task_update_ids.get(task.task_id)
            session, run_result = self.run_chat_turn(
                task,
                create_workspace=create_workspace,
                workspace_policy=workspace_policy,
                run_bootstrap=run_bootstrap,
            )
            response_status, response_text = _telegram_chat_response_for_result(run_result)
            intake.send_chat_response(task, response_text, status=response_status)
            responses.append(
                TelegramChatResponseDelivery(
                    update_id=update_id,
                    session_id=session.session_id,
                    task_id=task.task_id,
                    chat_id=task.chat_id,
                    message_id=task.message_id,
                    text=response_text,
                    status=response_status,
                )
            )
            turns.append(
                TelegramChatTurnResult(
                    update_id=update_id,
                    task=task,
                    session=session,
                    run_result=run_result,
                )
            )

        return TelegramChatLoopResult(
            poll_result=poll_result,
            chat_turns=tuple(turns),
            response_deliveries=tuple(responses),
        )

    def run_chat_turn(
        self,
        task: TelegramTask,
        create_workspace: bool = True,
        workspace_policy: WorkspaceReusePolicy = WorkspaceReusePolicy.REUSE,
        run_bootstrap: bool = True,
    ) -> Tuple[TelegramChatSession, CodexRunResult]:
        """Pass one Telegram message into its persistent Codex chat session."""

        session = self._chat_store.get_or_create(task)
        events: List[TaskEvent] = []
        runtime = self._chat_runtimes.get(session.session_id)

        workspace = self._workspaces.prepare_workspace_for_id(
            session.session_id,
            task_id=session.session_id,
            policy=workspace_policy,
            create=create_workspace,
            run_bootstrap=run_bootstrap,
        )
        workspace_payload = {
            "workspace_path": str(workspace.path),
            "created": workspace.created,
            "reused": workspace.reused,
            "reuse_policy": workspace.reuse_policy.value,
        }
        workspace_payload.update(_telegram_identity_payload(task, self._config.owner_profile))
        self._emit_session_event(
            events,
            TaskEventType.WORKSPACE_PREPARED,
            session.session_id,
            session.session_id,
            status=workspace.bootstrap_status.value,
            payload=workspace_payload,
        )
        session = self._chat_store.save(
            replace(
                session,
                workspace_path=str(workspace.path),
                last_status="running",
                pending_prompt=None,
            )
        )
        self._save_chat_run_state(session, HarnessRunStatus.RUNNING)

        if runtime is None:
            runtime = self._chat_runtime_factory(session.thread_id)
            self._chat_runtimes[session.session_id] = runtime

        prompt = task.text
        if session.turns_completed == 0 and session.thread_id is None and runtime.pending_request is None:
            policy = build_prompt_policy(task, owner_profile=self._config.owner_profile)
            prompt = policy.render_prompt()
            self._emit_session_event(
                events,
                TaskEventType.PROMPT_BUILT,
                session.session_id,
                session.session_id,
                payload={
                    "policy": "initial_chat_prompt",
                    "policy_lines": len(policy.summary_lines),
                    "owner_profile_applied": policy.owner_profile is not None,
                    "session_identity": _session_identity(task, self._config.owner_profile),
                },
            )

        invocation = self._planner.plan(workspace, prompt)
        self._emit_session_event(
            events,
            TaskEventType.CODEX_TURN_STARTED,
            session.session_id,
            session.session_id,
            turn_number=session.turns_completed + 1,
        )

        observed_runtime_events: List[CodexRuntimeEvent] = []

        def on_runtime_event(event: CodexRuntimeEvent) -> None:
            observed_runtime_events.append(event)
            self._emit_runtime_event_for_ids(
                events,
                session.session_id,
                session.session_id,
                session.turns_completed + 1,
                event,
            )

        run_result = runtime.run_turn(invocation, on_event=on_runtime_event)
        for runtime_event in run_result.events[len(observed_runtime_events) :]:
            self._emit_runtime_event_for_ids(
                events,
                session.session_id,
                session.session_id,
                session.turns_completed + 1,
                runtime_event,
            )

        completed_turns = session.turns_completed
        if run_result.status == CodexRunStatus.COMPLETED:
            completed_turns += 1
        session_status = _chat_session_status(run_result)
        session = self._chat_store.save(
            replace(
                session,
                thread_id=run_result.metadata.thread_id or runtime.thread_id or session.thread_id,
                last_turn_id=run_result.metadata.turn_id or runtime.turn_id,
                turns_completed=completed_turns,
                last_status=session_status.value,
                last_assistant_response=run_result.assistant_response or session.last_assistant_response,
                pending_prompt=run_result.pending_prompt,
            )
        )
        self._save_chat_run_state(session, session_status)
        self._emit_session_event(
            events,
            TaskEventType.CODEX_TURN_COMPLETED,
            session.session_id,
            session.session_id,
            status=run_result.status.value,
            message=run_result.error,
            turn_number=max(1, completed_turns),
            payload={
                "thread_id": session.thread_id,
                "turn_id": session.last_turn_id,
                "assistant_response": run_result.assistant_response,
                "pending_prompt": run_result.pending_prompt,
            },
        )
        if run_result.assistant_response:
            self._emit_session_event(
                events,
                TaskEventType.ASSISTANT_RESPONSE,
                session.session_id,
                session.session_id,
                status="completed",
                message=run_result.assistant_response,
                turn_number=completed_turns,
                payload={
                    "thread_id": session.thread_id,
                    "turn_id": session.last_turn_id,
                    "assistant_response": run_result.assistant_response,
                },
            )
        return session, run_result

    def _emit(
        self,
        events: List[TaskEvent],
        event_type: TaskEventType,
        task: TelegramTask,
        run_id: str,
        status: Optional[str] = None,
        message: Optional[str] = None,
        turn_number: Optional[int] = None,
        payload: Optional[dict[str, object]] = None,
    ) -> None:
        event = TaskEvent(
            type=event_type,
            task_id=task.task_id,
            run_id=run_id,
            status=status,
            message=message,
            turn_number=turn_number,
            payload=payload or {},
        )
        events.append(event)
        if self._on_event is not None:
            self._on_event(event)

    def _emit_session_event(
        self,
        events: List[TaskEvent],
        event_type: TaskEventType,
        task_id: str,
        run_id: str,
        status: Optional[str] = None,
        message: Optional[str] = None,
        turn_number: Optional[int] = None,
        payload: Optional[dict[str, object]] = None,
    ) -> None:
        event = TaskEvent(
            type=event_type,
            task_id=task_id,
            run_id=run_id,
            status=status,
            message=message,
            turn_number=turn_number,
            payload=payload or {},
        )
        events.append(event)
        if self._on_event is not None:
            self._on_event(event)

    def _emit_runtime_event(
        self,
        events: List[TaskEvent],
        task: TelegramTask,
        run_id: str,
        turn_number: int,
        runtime_event: CodexRuntimeEvent,
    ) -> None:
        self._emit(
            events,
            TaskEventType.CODEX_RUNTIME_EVENT,
            task,
            run_id,
            status=runtime_event.type.value,
            message=runtime_event.message,
            turn_number=turn_number,
            payload={
                "method": runtime_event.method,
                "thread_id": runtime_event.thread_id,
                "turn_id": runtime_event.turn_id,
            },
        )

    def _emit_runtime_event_for_ids(
        self,
        events: List[TaskEvent],
        task_id: str,
        run_id: str,
        turn_number: int,
        runtime_event: CodexRuntimeEvent,
    ) -> None:
        self._emit_session_event(
            events,
            TaskEventType.CODEX_RUNTIME_EVENT,
            task_id,
            run_id,
            status=runtime_event.type.value,
            message=runtime_event.message,
            turn_number=turn_number,
            payload={
                "method": runtime_event.method,
                "thread_id": runtime_event.thread_id,
                "turn_id": runtime_event.turn_id,
            },
        )

    def _save_chat_run_state(
        self,
        session: TelegramChatSession,
        status: HarnessRunStatus,
    ) -> None:
        self._run_store.save_run(
            RunState(
                run_id=session.session_id,
                task_id=session.session_id,
                status=status,
                turns_completed=session.turns_completed,
                workspace_path=session.workspace_path,
                last_error=session.pending_prompt if status in {HarnessRunStatus.APPROVAL_REQUIRED, HarnessRunStatus.INPUT_REQUIRED, HarnessRunStatus.FAILED} else None,
                last_decision="chat",
            )
        )

    def _apply_workspace_retention(
        self,
        workspace: Workspace,
        status: HarnessRunStatus,
    ) -> None:
        if self._config.workspace_retention_policy == "retain":
            return
        if self._config.workspace_retention_policy == "cleanup_on_success":
            if status != HarnessRunStatus.COMPLETED:
                return
        self._workspaces.cleanup_workspace(workspace)


class FakeCodexRuntime:
    """Deterministic runtime used by dry-run mode and unit tests."""

    def __init__(
        self,
        statuses: Tuple[CodexRunStatus, ...] = (CodexRunStatus.COMPLETED,),
        markers: Tuple[str, ...] = ("completed",),
    ) -> None:
        self._statuses = statuses
        self._markers = markers
        self.calls: List[CodexInvocation] = []

    def run_turn(
        self,
        invocation: CodexInvocation,
        on_event: Optional[RuntimeEventCallback] = None,
    ) -> CodexRunResult:
        self.calls.append(invocation)
        index = len(self.calls) - 1
        status = self._statuses[min(index, len(self._statuses) - 1)]
        marker = self._markers[min(index, len(self._markers) - 1)]
        event = CodexRuntimeEvent(
            type=CodexRuntimeEventType.NOTIFICATION,
            method="fake/turn",
            message="VERA_TASK_STATUS: {}\nVERA_STATUS_REASON: fake runtime dry-run".format(marker),
        )
        if on_event is not None:
            on_event(event)
        return CodexRunResult(
            status=status,
            metadata=CodexSessionMetadata(
                command=invocation.display_command,
                cwd=invocation.workspace_path,
                approval_policy=invocation.approval_policy,
                sandbox_mode=invocation.sandbox_mode,
                thread_id="fake-thread",
                turn_id="fake-turn-{}".format(len(self.calls)),
                model="fake-codex-runtime",
                model_provider="vera-harness",
            ),
            events=(event,),
            error=None if status == CodexRunStatus.COMPLETED else status.value,
            elapsed_seconds=0.0,
        )


def format_dry_run(result: DryRunResult) -> str:
    invocation = result.invocation
    repo_clone = invocation.repo_clone_command.display if invocation and invocation.repo_clone_command else "not configured"
    repo_bootstrap = (
        invocation.repo_bootstrap_command.display if invocation and invocation.repo_bootstrap_command else "not configured"
    )
    policy_lines = "\n".join(
        "- {}".format(line) for line in (result.policy.summary_lines if result.policy else ())
    )
    event_lines = "\n".join(
        "- {}{}".format(
            event.type.value,
            " ({})".format(event.status) if event.status else "",
        )
        for event in result.events
    )

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
            "command: {}".format(invocation.display_command if invocation else "not planned"),
            "workspace: {}".format(invocation.workspace_path if invocation else "not planned"),
            "max_turns: {}".format(invocation.max_turns if invocation else "not planned"),
            "turn_timeout_seconds: {}".format(invocation.turn_timeout_seconds if invocation else "not planned"),
            "run_timeout_seconds: {}".format(invocation.run_timeout_seconds if invocation else "not planned"),
            "approval_policy: {}".format(invocation.approval_policy if invocation else "not planned"),
            "sandbox_mode: {}".format(invocation.sandbox_mode if invocation else "not planned"),
            "repo_clone_command: {}".format(repo_clone),
            "repo_bootstrap_command: {}".format(repo_bootstrap),
            "",
            "final_status: {}".format(result.harness_run.status.value),
            "final_decision: {}".format(result.final_decision.action.value),
            "turns_completed: {}".format(len(result.turn_results)),
            "",
            "event_sequence:",
            event_lines,
            "",
            "codex_launch: skipped (fake runtime dry run)",
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


def format_telegram_loop(
    result: TelegramLoopResult,
    title: str = "Vera Telegram-to-Codex loop",
) -> str:
    counts = {
        status: sum(1 for outcome in result.poll_result.outcomes if outcome.status == status)
        for status in TelegramUpdateStatus
    }
    lines = [
        title,
        "updates_seen: {}".format(len(result.poll_result.outcomes)),
        "accepted: {}".format(counts[TelegramUpdateStatus.ACCEPTED]),
        "rejected: {}".format(counts[TelegramUpdateStatus.REJECTED]),
        "blocked: {}".format(counts[TelegramUpdateStatus.BLOCKED]),
        "duplicates: {}".format(counts[TelegramUpdateStatus.DUPLICATE]),
        "ignored: {}".format(counts[TelegramUpdateStatus.IGNORED]),
        "queued_tasks: {}".format(len(result.poll_result.queued_tasks)),
        "task_runs: {}".format(len(result.task_runs)),
        "",
        "task_run_log:",
    ]
    if not result.task_runs:
        lines.append("- none")
    for task_run in result.task_runs:
        run = task_run.result
        metadata = _last_metadata(run)
        lines.extend(
            [
                "- task_id: {}".format(run.task.task_id),
                "  telegram_chat_id: {}".format(run.task.chat_id),
                "  telegram_update_id: {}".format(_display_optional(task_run.update_id)),
                "  telegram_message_id: {}".format(run.task.message_id),
                "  run_id: {}".format(run.harness_run.run_id),
                "  workspace_path: {}".format(run.workspace.path),
                "  codex_thread_id: {}".format(_display_optional(metadata.thread_id if metadata else None)),
                "  codex_turn_id: {}".format(_display_optional(metadata.turn_id if metadata else None)),
                "  final_status: {}".format(run.harness_run.status.value),
                "  final_decision: {}".format(run.final_decision.action.value),
                "  final_reason: {}".format(_compact_log_value(run.final_decision.reason)),
            ]
        )

    lines.extend(["", "telegram_status_messages:"])
    if not result.status_deliveries:
        lines.append("- none")
    for delivery in result.status_deliveries:
        lines.extend(
            [
                "- status: {}".format(delivery.status.value),
                "  task_id: {}".format(_display_optional(delivery.task_id)),
                "  telegram_chat_id: {}".format(_display_optional(delivery.chat_id)),
                "  telegram_update_id: {}".format(_display_optional(delivery.update_id)),
                "  telegram_message_id: {}".format(_display_optional(delivery.message_id)),
                "  telegram_text: {}".format(delivery.text),
            ]
        )

    lines.extend(["", "event_sequence:"])
    any_events = False
    for task_run in result.task_runs:
        for event in task_run.result.events:
            any_events = True
            thread_id = event.payload.get("thread_id")
            turn_id = event.payload.get("turn_id")
            lines.append(
                "- task_id: {} run_id: {} event: {} status: {} turn: {} codex_thread_id: {} codex_turn_id: {}".format(
                    event.task_id,
                    event.run_id,
                    event.type.value,
                    _display_optional(event.status),
                    _display_optional(event.turn_number),
                    _display_optional(thread_id if isinstance(thread_id, str) else None),
                    _display_optional(turn_id if isinstance(turn_id, str) else None),
                )
            )
    if not any_events:
        lines.append("- none")
    return "\n".join(lines)


def format_telegram_chat_loop(
    result: TelegramChatLoopResult,
    title: str = "Vera Telegram-to-Codex chat loop",
) -> str:
    counts = {
        status: sum(1 for outcome in result.poll_result.outcomes if outcome.status == status)
        for status in TelegramUpdateStatus
    }
    lines = [
        title,
        "updates_seen: {}".format(len(result.poll_result.outcomes)),
        "accepted: {}".format(counts[TelegramUpdateStatus.ACCEPTED]),
        "rejected: {}".format(counts[TelegramUpdateStatus.REJECTED]),
        "blocked: {}".format(counts[TelegramUpdateStatus.BLOCKED]),
        "duplicates: {}".format(counts[TelegramUpdateStatus.DUPLICATE]),
        "ignored: {}".format(counts[TelegramUpdateStatus.IGNORED]),
        "queued_messages: {}".format(len(result.poll_result.queued_tasks)),
        "chat_turns: {}".format(len(result.chat_turns)),
        "",
        "chat_session_log:",
    ]
    if not result.chat_turns:
        lines.append("- none")
    for turn in result.chat_turns:
        metadata = turn.run_result.metadata
        lines.extend(
            [
                "- session_id: {}".format(turn.session.session_id),
                "  telegram_chat_id: {}".format(turn.task.chat_id),
                "  telegram_user_id: {}".format(turn.task.user_id),
                "  telegram_update_id: {}".format(_display_optional(turn.update_id)),
                "  telegram_message_id: {}".format(turn.task.message_id),
                "  workspace_path: {}".format(_display_optional(turn.session.workspace_path)),
                "  codex_thread_id: {}".format(_display_optional(metadata.thread_id)),
                "  codex_turn_id: {}".format(_display_optional(metadata.turn_id)),
                "  codex_status: {}".format(turn.run_result.status.value),
                "  last_status: {}".format(turn.session.last_status),
                "  assistant_response: {}".format(_compact_log_value(turn.run_result.assistant_response)),
            ]
        )

    lines.extend(["", "telegram_chat_responses:"])
    if not result.response_deliveries:
        lines.append("- none")
    for delivery in result.response_deliveries:
        lines.extend(
            [
                "- status: {}".format(delivery.status.value),
                "  session_id: {}".format(delivery.session_id),
                "  task_id: {}".format(delivery.task_id),
                "  telegram_chat_id: {}".format(delivery.chat_id),
                "  telegram_update_id: {}".format(_display_optional(delivery.update_id)),
                "  telegram_message_id: {}".format(delivery.message_id),
                "  telegram_text: {}".format(_compact_log_value(delivery.text)),
            ]
        )
    return "\n".join(lines)


def _telegram_identity_payload(
    task: TelegramTask,
    owner_profile: Optional[OwnerProfile],
) -> dict[str, object]:
    identity = _session_identity(task, owner_profile)
    payload: dict[str, object] = {
        "telegram_chat_id": task.chat_id,
        "telegram_user_id": task.user_id,
        "session_identity": identity,
        "session_identity_label": "authorized Telegram user_id {}".format(task.user_id),
    }
    if owner_profile is not None and owner_profile.matches(task):
        payload["session_identity_label"] = owner_profile.redacted_identity_label(
            fallback_username=task.username
        )
        payload["owner_profile"] = (
            "<redacted owner profile>"
            if owner_profile.has_profile_content
            else "<owner profile empty>"
        )
    return payload


def _session_identity(
    task: TelegramTask,
    owner_profile: Optional[OwnerProfile],
) -> str:
    if owner_profile is not None and owner_profile.matches(task):
        return "owner"
    return "authorized_user"


def _telegram_status_for_result(
    result: TaskRunResult,
) -> Tuple[TelegramTaskStatus, Optional[str]]:
    status = result.harness_run.status
    if status == HarnessRunStatus.COMPLETED:
        return TelegramTaskStatus.COMPLETED, None
    if status == HarnessRunStatus.FAILED:
        return TelegramTaskStatus.FAILED, result.final_decision.reason
    return TelegramTaskStatus.BLOCKED, result.final_decision.reason


def _telegram_chat_response_for_result(result: CodexRunResult) -> Tuple[TelegramTaskStatus, str]:
    if result.status == CodexRunStatus.COMPLETED and result.assistant_response:
        return TelegramTaskStatus.COMPLETED, result.assistant_response
    if result.status == CodexRunStatus.APPROVAL_REQUIRED:
        return TelegramTaskStatus.BLOCKED, result.pending_prompt or result.error or "Codex requested approval."
    if result.status == CodexRunStatus.INPUT_REQUIRED:
        return TelegramTaskStatus.BLOCKED, result.pending_prompt or result.error or "Codex requested input."
    if result.status == CodexRunStatus.COMPLETED:
        return TelegramTaskStatus.COMPLETED, "Codex completed the turn without a user-facing response."
    return TelegramTaskStatus.FAILED, format_telegram_status(
        TelegramTaskStatus.FAILED,
        reason=result.error or "Codex did not complete the chat turn.",
    )


def _chat_session_status(result: CodexRunResult) -> HarnessRunStatus:
    if result.status == CodexRunStatus.APPROVAL_REQUIRED:
        return HarnessRunStatus.APPROVAL_REQUIRED
    if result.status == CodexRunStatus.INPUT_REQUIRED:
        return HarnessRunStatus.INPUT_REQUIRED
    if result.status == CodexRunStatus.FAILED:
        return HarnessRunStatus.FAILED
    if result.status in {CodexRunStatus.CANCELLED, CodexRunStatus.TIMED_OUT}:
        return HarnessRunStatus.FAILED
    return HarnessRunStatus.RUNNING


def _status_delivery(
    task: TelegramTask,
    update_id: Optional[int],
    status: TelegramTaskStatus,
    reason: Optional[str] = None,
) -> TelegramStatusDelivery:
    return TelegramStatusDelivery(
        update_id=update_id,
        task_id=task.task_id,
        chat_id=task.chat_id,
        message_id=task.message_id,
        status=status,
        text=format_telegram_status(status, reason=reason),
        reason=reason,
    )


def _last_metadata(result: TaskRunResult) -> Optional[CodexSessionMetadata]:
    for turn_result in reversed(result.turn_results):
        return turn_result.metadata
    return None


def _display_optional(value: object) -> str:
    if value is None:
        return "not available"
    return str(value)


def _compact_log_value(value: Optional[str]) -> str:
    if value is None:
        return "not available"
    compact = " ".join(value.split())
    return compact[:280] if compact else "not available"


def _decide_after_turn(
    result: CodexRunResult,
    turn_number: int,
    max_turns: int,
    retry_count: int,
    max_retries: int,
) -> TurnDecision:
    if result.status == CodexRunStatus.COMPLETED:
        marker = _extract_status_marker(result)
        if marker == "blocked":
            return TurnDecision(
                action=OrchestrationDecision.BLOCK,
                status=HarnessRunStatus.BLOCKED,
                reason="Codex reported a task blocker",
                marker=marker,
            )
        if marker == "failed":
            return TurnDecision(
                action=OrchestrationDecision.FAIL,
                status=HarnessRunStatus.FAILED,
                reason="Codex reported task failure",
                marker=marker,
            )
        if marker == "continue":
            if turn_number >= max_turns:
                return TurnDecision(
                    action=OrchestrationDecision.FAIL,
                    status=HarnessRunStatus.FAILED,
                    reason="max turns reached after continue decision",
                    marker=marker,
                )
            return TurnDecision(
                action=OrchestrationDecision.CONTINUE,
                status=HarnessRunStatus.RUNNING,
                reason="Codex requested another turn",
                marker=marker,
            )
        return TurnDecision(
            action=OrchestrationDecision.COMPLETE,
            status=HarnessRunStatus.COMPLETED,
            reason="Codex completed the task",
            marker=marker,
        )

    if result.status == CodexRunStatus.APPROVAL_REQUIRED:
        return TurnDecision(
            action=OrchestrationDecision.BLOCK,
            status=HarnessRunStatus.APPROVAL_REQUIRED,
            reason=result.error or "Codex requested approval",
        )
    if result.status == CodexRunStatus.INPUT_REQUIRED:
        return TurnDecision(
            action=OrchestrationDecision.BLOCK,
            status=HarnessRunStatus.INPUT_REQUIRED,
            reason=result.error or "Codex requested human input",
        )

    if result.status in {
        CodexRunStatus.FAILED,
        CodexRunStatus.TIMED_OUT,
        CodexRunStatus.CANCELLED,
    }:
        if retry_count < max_retries and turn_number < max_turns:
            return TurnDecision(
                action=OrchestrationDecision.RETRY,
                status=HarnessRunStatus.RUNNING,
                reason=result.error or "Codex turn failed; retrying",
            )
        return TurnDecision(
            action=OrchestrationDecision.FAIL,
            status=HarnessRunStatus.FAILED,
            reason=result.error or "Codex turn failed",
        )

    return TurnDecision(
        action=OrchestrationDecision.FAIL,
        status=HarnessRunStatus.FAILED,
        reason="unrecognized Codex status: {}".format(result.status.value),
    )


_STATUS_MARKER_RE = re.compile(
    r"VERA_TASK_STATUS:\s*(completed|continue|blocked|failed)\b",
    re.IGNORECASE,
)


def _extract_status_marker(result: CodexRunResult) -> Optional[str]:
    haystack = "\n".join(_event_text(event) for event in result.events)
    match = None
    for match in _STATUS_MARKER_RE.finditer(haystack):
        pass
    if match is None:
        return None
    return match.group(1).lower()


def _event_text(event: CodexRuntimeEvent) -> str:
    parts = [event.message or "", str(event.payload)]
    return "\n".join(parts)


def _run_id(task: TelegramTask, dry_run: bool) -> str:
    if dry_run:
        return "dry-run-{}".format(task.task_id)
    return "run-{}-{}".format(task.task_id, int(time.time() * 1000))


def _result(
    task: TelegramTask,
    workspace: Workspace,
    harness_run: HarnessRun,
    policy: Optional[PromptPolicy],
    invocation: Optional[CodexInvocation],
    events: List[TaskEvent],
    turn_results: List[CodexRunResult],
    decision: TurnDecision,
) -> TaskRunResult:
    return TaskRunResult(
        task=task,
        workspace=workspace,
        harness_run=replace(harness_run, workspace=workspace, status=decision.status),
        policy=policy,
        invocation=invocation,
        events=tuple(events),
        turn_results=tuple(turn_results),
        final_decision=decision,
    )
