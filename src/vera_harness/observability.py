"""Shared console observability state for Vera TUI and GUI surfaces."""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .config import HarnessConfig
from .models import HarnessRunStatus, RunState, TaskEvent, TaskEventType
from .state import JsonRunStateStore, RunStateError


class TelemetryState(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class PlanOrigin(str, Enum):
    AGENT_GENERATED = "agent_generated"
    USER_CONFIRMED = "user_confirmed"
    BLOCKER = "blocker"


class ConsoleEventCategory(str, Enum):
    STATUS = "status"
    REASONING = "reasoning"
    TOOL = "tool"
    CODEX = "codex"
    SOURCE = "source"
    ERROR = "error"


@dataclass(frozen=True)
class RateLimitTelemetry:
    state: TelemetryState
    remaining_requests: Optional[int] = None
    remaining_tokens: Optional[int] = None
    reset_requests_at: Optional[str] = None
    reset_tokens_at: Optional[str] = None
    source: str = "not configured"
    note: str = ""


@dataclass(frozen=True)
class UsageTelemetry:
    state: TelemetryState
    daily_usd: Optional[float] = None
    weekly_usd: Optional[float] = None
    monthly_usd: Optional[float] = None
    daily_tokens: Optional[int] = None
    weekly_tokens: Optional[int] = None
    monthly_tokens: Optional[int] = None
    source: str = "not configured"
    note: str = ""


@dataclass(frozen=True)
class BudgetThresholdTelemetry:
    state: TelemetryState
    monthly_budget_usd: Optional[float] = None
    project_budget_usd: Optional[float] = None
    note: str = ""


@dataclass(frozen=True)
class BudgetTelemetry:
    rate_limits: RateLimitTelemetry
    usage: UsageTelemetry
    thresholds: BudgetThresholdTelemetry
    captured_at: str


@dataclass(frozen=True)
class PlanEntry:
    text: str
    origin: PlanOrigin
    done: bool = False


@dataclass(frozen=True)
class ConsoleEvent:
    event_id: str
    created_at: str
    category: ConsoleEventCategory
    event_type: str
    source: str
    summary: str
    task_id: Optional[str] = None
    run_id: Optional[str] = None
    agent_id: Optional[str] = None
    turn_number: Optional[int] = None
    severity: str = "info"
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentSnapshot:
    agent_id: str
    task_id: str
    run_id: str
    status: str
    source_channel: str
    workspace_path: Optional[str]
    current_turn: int
    turns_completed: int
    age_seconds: int
    updated_seconds_ago: int
    token_usage: Optional[int] = None
    budget_usd: Optional[float] = None
    session_identity: Optional[str] = None
    session_identity_label: Optional[str] = None


@dataclass(frozen=True)
class FocusedAgentSnapshot:
    agent: AgentSnapshot
    last_turn_summary: str
    current_objective: str
    plan: Tuple[PlanEntry, ...]
    blockers: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ConsoleSnapshot:
    generated_at: str
    budget: BudgetTelemetry
    agents: Tuple[AgentSnapshot, ...]
    focused_agent_id: Optional[str]
    focused: Optional[FocusedAgentSnapshot]
    events: Tuple[ConsoleEvent, ...]
    event_filter: Optional[str] = None


class JsonConsoleEventLog:
    """Append-only JSONL event log consumed by console state providers."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def append_task_event(self, event: TaskEvent) -> None:
        self.append_console_event(console_event_from_task_event(event))

    def append_source_event(
        self,
        source: str,
        event_type: str,
        summary: str,
        task_id: Optional[str] = None,
        run_id: Optional[str] = None,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.append_console_event(
            ConsoleEvent(
                event_id=_event_id(),
                created_at=_now_iso(),
                category=ConsoleEventCategory.SOURCE,
                event_type=event_type,
                source=source,
                summary=redact_text(summary),
                task_id=task_id,
                run_id=run_id,
                agent_id=_agent_id(task_id, run_id) if task_id and run_id else task_id,
                details=redact_mapping(details or {}),
            )
        )

    def append_console_event(self, event: ConsoleEvent) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(console_event_to_json(event), sort_keys=True) + "\n")

    def read_events(self, limit: int = 200) -> Tuple[ConsoleEvent, ...]:
        if not self._path.exists():
            return ()
        lines = self._path.read_text(encoding="utf-8").splitlines()
        events: List[ConsoleEvent] = []
        for line in lines[-limit:]:
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            event = console_event_from_json(raw)
            if event is not None:
                events.append(event)
        return tuple(events)


class JsonObservabilityProvider:
    """Build a console-ready snapshot from run state, event log, and budget data."""

    def __init__(
        self,
        run_state_path: Path,
        event_log_path: Optional[Path] = None,
        budget_snapshot_path: Optional[Path] = None,
        monthly_budget_usd: Optional[float] = None,
        project_budget_usd: Optional[float] = None,
        env: Optional[Mapping[str, str]] = None,
        now: Optional[datetime] = None,
    ) -> None:
        self._run_state_path = run_state_path
        self._event_log_path = event_log_path
        self._budget_snapshot_path = budget_snapshot_path
        self._monthly_budget_usd = monthly_budget_usd
        self._project_budget_usd = project_budget_usd
        self._env = os.environ if env is None else env
        self._now = now

    @classmethod
    def from_config(
        cls,
        config: HarnessConfig,
        env: Optional[Mapping[str, str]] = None,
        now: Optional[datetime] = None,
    ) -> "JsonObservabilityProvider":
        return cls(
            run_state_path=config.run_state_path,
            event_log_path=config.event_log_path,
            budget_snapshot_path=config.budget_snapshot_path,
            monthly_budget_usd=config.monthly_budget_usd,
            project_budget_usd=config.project_budget_usd,
            env=env,
            now=now,
        )

    def snapshot(
        self,
        focused_agent_id: Optional[str] = None,
        event_filter: Optional[str] = None,
        event_limit: int = 200,
    ) -> ConsoleSnapshot:
        now = self._now or datetime.now(timezone.utc)
        events = self._read_events(event_limit)
        if event_filter:
            events = tuple(event for event in events if _event_matches(event, event_filter))
        agents = tuple(
            _agent_snapshot(run, events, now)
            for run in self._read_runs()
        )
        agents = tuple(sorted(agents, key=lambda agent: (_agent_sort_rank(agent.status), agent.task_id)))
        selected = select_focused_agent(agents, focused_agent_id)
        focused = _focused_snapshot(selected, events) if selected is not None else None
        return ConsoleSnapshot(
            generated_at=_iso(now),
            budget=budget_from_sources(
                snapshot_path=self._budget_snapshot_path,
                monthly_budget_usd=self._monthly_budget_usd,
                project_budget_usd=self._project_budget_usd,
                env=self._env,
                now=now,
            ),
            agents=agents,
            focused_agent_id=selected.agent_id if selected is not None else None,
            focused=focused,
            events=events,
            event_filter=event_filter or None,
        )

    def _read_runs(self) -> Tuple[RunState, ...]:
        try:
            return JsonRunStateStore(self._run_state_path).all_runs()
        except RunStateError:
            return ()

    def _read_events(self, limit: int) -> Tuple[ConsoleEvent, ...]:
        if self._event_log_path is None:
            return ()
        return JsonConsoleEventLog(self._event_log_path).read_events(limit=limit)


class StaticObservabilityProvider:
    """Provider backed by a fixed snapshot, useful for smoke tests."""

    def __init__(self, snapshot: ConsoleSnapshot) -> None:
        self._snapshot = snapshot

    def snapshot(
        self,
        focused_agent_id: Optional[str] = None,
        event_filter: Optional[str] = None,
        event_limit: int = 200,
    ) -> ConsoleSnapshot:
        agents = self._snapshot.agents
        selected = select_focused_agent(agents, focused_agent_id or self._snapshot.focused_agent_id)
        events = self._snapshot.events[-event_limit:]
        if event_filter:
            events = tuple(event for event in events if _event_matches(event, event_filter))
        focused = _focused_snapshot(selected, events) if selected is not None else None
        return ConsoleSnapshot(
            generated_at=_now_iso(),
            budget=self._snapshot.budget,
            agents=agents,
            focused_agent_id=selected.agent_id if selected is not None else None,
            focused=focused,
            events=events,
            event_filter=event_filter or None,
        )


def fake_observability_provider() -> StaticObservabilityProvider:
    """Return deterministic console state with redaction fixtures."""

    now = datetime.now(timezone.utc)
    active_agent = AgentSnapshot(
        agent_id="telegram-100-300:run-telegram-100-300-1",
        task_id="telegram-100-300",
        run_id="run-telegram-100-300-1",
        status=HarnessRunStatus.RUNNING.value,
        source_channel="telegram",
        workspace_path="/tmp/vera/workspaces/telegram-100-300",
        current_turn=2,
        turns_completed=1,
        age_seconds=184,
        updated_seconds_ago=4,
        token_usage=3120,
        budget_usd=0.19,
        session_identity="owner",
        session_identity_label="primary owner: Vera Owner (Telegram user_id 200)",
    )
    idle_agent = AgentSnapshot(
        agent_id="telegram-100-301:run-telegram-100-301-1",
        task_id="telegram-100-301",
        run_id="run-telegram-100-301-1",
        status=HarnessRunStatus.COMPLETED.value,
        source_channel="telegram",
        workspace_path="/tmp/vera/workspaces/telegram-100-301",
        current_turn=1,
        turns_completed=1,
        age_seconds=780,
        updated_seconds_ago=420,
        session_identity="authorized_user",
        session_identity_label="authorized Telegram user_id 201",
    )
    raw_events = (
        ConsoleEvent(
            event_id="evt-fake-1",
            created_at=_iso(now),
            category=ConsoleEventCategory.SOURCE,
            event_type="telegram_update",
            source="telegram",
            summary="Accepted private Telegram task",
            task_id=active_agent.task_id,
            run_id=active_agent.run_id,
            agent_id=active_agent.agent_id,
            details=redact_mapping(
                {
                    "telegram_message_text": "Please deploy with token sk-live-secret",
                    "telegram_bot_token": "12345:secret-bot-token",
                    "owner_profile": "Raw owner values and communication preferences should stay hidden.",
                }
            ),
        ),
        ConsoleEvent(
            event_id="evt-fake-2",
            created_at=_iso(now),
            category=ConsoleEventCategory.CODEX,
            event_type="codex_runtime_event",
            source="codex",
            summary="Codex completed turn 1 and requested continuation",
            task_id=active_agent.task_id,
            run_id=active_agent.run_id,
            agent_id=active_agent.agent_id,
            turn_number=1,
            details=redact_mapping({"method": "turn/completed", "authorization": "Bearer secret-value"}),
        ),
        ConsoleEvent(
            event_id="evt-fake-3",
            created_at=_iso(now),
            category=ConsoleEventCategory.STATUS,
            event_type="decision_recorded",
            source="orchestrator",
            summary="Decision recorded: continue",
            task_id=active_agent.task_id,
            run_id=active_agent.run_id,
            agent_id=active_agent.agent_id,
            turn_number=1,
            details={
                "marker": "continue",
                "current_objective": "Finish the supervised console implementation pass.",
                "plan": [
                    {
                        "text": "Confirm the Telegram-originated task was accepted.",
                        "origin": PlanOrigin.USER_CONFIRMED.value,
                        "done": True,
                    },
                    {
                        "text": "Inspect logs and continue implementation.",
                        "origin": PlanOrigin.AGENT_GENERATED.value,
                        "done": False,
                    },
                ],
            },
        ),
    )
    budget = BudgetTelemetry(
        rate_limits=RateLimitTelemetry(
            state=TelemetryState.UNAVAILABLE,
            source="fake",
            note="OpenAI rate-limit telemetry credentials are not configured.",
        ),
        usage=UsageTelemetry(
            state=TelemetryState.UNAVAILABLE,
            source="fake",
            note="Usage summary is unavailable without an admin usage snapshot.",
        ),
        thresholds=BudgetThresholdTelemetry(
            state=TelemetryState.AVAILABLE,
            monthly_budget_usd=250.0,
            project_budget_usd=50.0,
            note="Fake threshold values for console smoke tests.",
        ),
        captured_at=_iso(now),
    )
    snapshot = ConsoleSnapshot(
        generated_at=_iso(now),
        budget=budget,
        agents=(active_agent, idle_agent),
        focused_agent_id=active_agent.agent_id,
        focused=_focused_snapshot(active_agent, raw_events),
        events=raw_events,
    )
    return StaticObservabilityProvider(snapshot)


def console_event_from_task_event(event: TaskEvent) -> ConsoleEvent:
    category = _category_for_task_event(event)
    severity = "error" if category == ConsoleEventCategory.ERROR else "info"
    source = "codex" if event.type == TaskEventType.CODEX_RUNTIME_EVENT else "orchestrator"
    return ConsoleEvent(
        event_id=_event_id(),
        created_at=_iso(event.created_at),
        category=category,
        event_type=event.type.value,
        source=source,
        summary=_task_event_summary(event),
        task_id=event.task_id,
        run_id=event.run_id,
        agent_id=_agent_id(event.task_id, event.run_id),
        turn_number=event.turn_number,
        severity=severity,
        details=redact_mapping(event.payload),
    )


def console_event_to_json(event: ConsoleEvent) -> Dict[str, Any]:
    return {
        "event_id": event.event_id,
        "created_at": event.created_at,
        "category": event.category.value,
        "event_type": event.event_type,
        "source": event.source,
        "summary": event.summary,
        "task_id": event.task_id,
        "run_id": event.run_id,
        "agent_id": event.agent_id,
        "turn_number": event.turn_number,
        "severity": event.severity,
        "details": dict(event.details),
    }


def console_event_from_json(raw: Mapping[str, Any]) -> Optional[ConsoleEvent]:
    try:
        category = ConsoleEventCategory(str(raw.get("category", ConsoleEventCategory.STATUS.value)))
    except ValueError:
        category = ConsoleEventCategory.STATUS
    event_id = _optional_string(raw.get("event_id")) or _event_id()
    created_at = _optional_string(raw.get("created_at")) or _now_iso()
    event_type = _optional_string(raw.get("event_type")) or "unknown"
    source = _optional_string(raw.get("source")) or "unknown"
    summary = _optional_string(raw.get("summary")) or event_type
    details = raw.get("details")
    return ConsoleEvent(
        event_id=event_id,
        created_at=created_at,
        category=category,
        event_type=event_type,
        source=source,
        summary=redact_text(summary),
        task_id=_optional_string(raw.get("task_id")),
        run_id=_optional_string(raw.get("run_id")),
        agent_id=_optional_string(raw.get("agent_id")),
        turn_number=_optional_int(raw.get("turn_number")),
        severity=_optional_string(raw.get("severity")) or "info",
        details=redact_mapping(details if isinstance(details, Mapping) else {}),
    )


def snapshot_to_json(snapshot: ConsoleSnapshot) -> Dict[str, Any]:
    return {
        "generated_at": snapshot.generated_at,
        "budget": {
            "rate_limits": _dataclass_enum_dict(snapshot.budget.rate_limits),
            "usage": _dataclass_enum_dict(snapshot.budget.usage),
            "thresholds": _dataclass_enum_dict(snapshot.budget.thresholds),
            "captured_at": snapshot.budget.captured_at,
            "summary": format_budget_bar(snapshot.budget),
        },
        "agents": [_dataclass_enum_dict(agent) for agent in snapshot.agents],
        "focused_agent_id": snapshot.focused_agent_id,
        "focused": _focused_to_json(snapshot.focused),
        "events": [console_event_to_json(event) for event in snapshot.events],
        "event_filter": snapshot.event_filter,
    }


def select_focused_agent(
    agents: Sequence[AgentSnapshot],
    requested_agent_id: Optional[str] = None,
) -> Optional[AgentSnapshot]:
    if not agents:
        return None
    if requested_agent_id:
        for agent in agents:
            if agent.agent_id == requested_agent_id or agent.task_id == requested_agent_id:
                return agent
    for agent in agents:
        if agent.status in {HarnessRunStatus.PLANNED.value, HarnessRunStatus.RUNNING.value}:
            return agent
    return agents[0]


def budget_from_sources(
    snapshot_path: Optional[Path] = None,
    monthly_budget_usd: Optional[float] = None,
    project_budget_usd: Optional[float] = None,
    env: Optional[Mapping[str, str]] = None,
    now: Optional[datetime] = None,
) -> BudgetTelemetry:
    source_env = os.environ if env is None else env
    captured_at = _iso(now or datetime.now(timezone.utc))
    raw = _load_budget_snapshot(snapshot_path)

    rate_limits = _rate_limits_from_snapshot(raw, snapshot_path)
    usage = _usage_from_snapshot(raw, snapshot_path)
    threshold_monthly = _first_float(
        _nested(raw, ("thresholds", "monthly_budget_usd")),
        _nested(raw, ("budget", "monthly_budget_usd")),
        monthly_budget_usd,
    )
    threshold_project = _first_float(
        _nested(raw, ("thresholds", "project_budget_usd")),
        _nested(raw, ("budget", "project_budget_usd")),
        project_budget_usd,
    )

    if rate_limits is None:
        if _has_openai_telemetry_hint(source_env):
            rate_limits = RateLimitTelemetry(
                state=TelemetryState.UNKNOWN,
                source="environment",
                note="OpenAI credentials are configured, but no rate-limit snapshot has been captured yet.",
            )
        else:
            rate_limits = RateLimitTelemetry(
                state=TelemetryState.UNAVAILABLE,
                source="not configured",
                note="OpenAI rate-limit telemetry credentials are not configured.",
            )
    if usage is None:
        if _has_openai_admin_hint(source_env):
            usage = UsageTelemetry(
                state=TelemetryState.UNKNOWN,
                source="environment",
                note="OpenAI admin credentials are configured, but no usage snapshot has been captured yet.",
            )
        else:
            usage = UsageTelemetry(
                state=TelemetryState.UNAVAILABLE,
                source="not configured",
                note="Usage summary is unavailable without an admin usage snapshot.",
            )

    thresholds = BudgetThresholdTelemetry(
        state=TelemetryState.AVAILABLE
        if threshold_monthly is not None or threshold_project is not None
        else TelemetryState.UNKNOWN,
        monthly_budget_usd=threshold_monthly,
        project_budget_usd=threshold_project,
        note="Configured budget threshold."
        if threshold_monthly is not None or threshold_project is not None
        else "No monthly or project budget threshold is configured.",
    )
    return BudgetTelemetry(
        rate_limits=rate_limits,
        usage=usage,
        thresholds=thresholds,
        captured_at=captured_at,
    )


def format_budget_bar(budget: BudgetTelemetry) -> str:
    rate = budget.rate_limits
    usage = budget.usage
    thresholds = budget.thresholds
    rate_text = "rate limits: {}".format(rate.state.value)
    if rate.state == TelemetryState.AVAILABLE:
        rate_text = "rate limits: {} req / {} tok reset req {} tok {}".format(
            _display(rate.remaining_requests),
            _display(rate.remaining_tokens),
            _display(rate.reset_requests_at),
            _display(rate.reset_tokens_at),
        )
    usage_text = "usage: {}".format(usage.state.value)
    if usage.state == TelemetryState.AVAILABLE:
        usage_text = "usage: day ${} week ${} month ${}".format(
            _money(usage.daily_usd),
            _money(usage.weekly_usd),
            _money(usage.monthly_usd),
        )
    threshold_text = "thresholds: {}".format(thresholds.state.value)
    if thresholds.state == TelemetryState.AVAILABLE:
        threshold_text = "thresholds: monthly ${} project ${}".format(
            _money(thresholds.monthly_budget_usd),
            _money(thresholds.project_budget_usd),
        )
    return " | ".join((rate_text, usage_text, threshold_text))


def redact_mapping(mapping: Mapping[str, Any], include_private: bool = False) -> Dict[str, Any]:
    return {
        str(key): redact_value(value, key=str(key), include_private=include_private)
        for key, value in mapping.items()
    }


def redact_value(
    value: Any,
    key: Optional[str] = None,
    parent_key: Optional[str] = None,
    include_private: bool = False,
) -> Any:
    if key and _is_secret_key(key):
        return "<redacted secret>"
    if key and not include_private and _is_private_body_key(key, parent_key=parent_key):
        return "<redacted private message>"
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        context_key = key or parent_key
        return {
            str(child_key): redact_value(
                child_value,
                key=str(child_key),
                parent_key=context_key,
                include_private=include_private,
            )
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [
            redact_value(item, parent_key=key or parent_key, include_private=include_private)
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            redact_value(item, parent_key=key or parent_key, include_private=include_private)
            for item in value
        )
    return value


def redact_text(text: str) -> str:
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("<redacted secret>", redacted)
    return redacted


def _focused_snapshot(
    agent: Optional[AgentSnapshot],
    events: Sequence[ConsoleEvent],
) -> Optional[FocusedAgentSnapshot]:
    if agent is None:
        return None
    agent_events = [event for event in events if event.agent_id == agent.agent_id or event.task_id == agent.task_id]
    last_decision = _last_event(agent_events, ("assistant_response", "decision_recorded", "codex_turn_completed"))
    last_summary = last_decision.summary if last_decision is not None else "No completed turn has been recorded yet."
    blockers = tuple(
        event.summary
        for event in agent_events
        if event.category == ConsoleEventCategory.ERROR or event.event_type in {"run_blocked", "run_failed"}
    )
    plan = list(_latest_plan_detail(agent_events))
    if not plan:
        plan = [
            PlanEntry(
                text="User task accepted from {}".format(agent.source_channel),
                origin=PlanOrigin.USER_CONFIRMED,
                done=True,
            ),
            PlanEntry(
                text="Run supervised Codex turn {}".format(max(1, agent.current_turn)),
                origin=PlanOrigin.AGENT_GENERATED,
                done=agent.status not in {HarnessRunStatus.PLANNED.value, HarnessRunStatus.RUNNING.value},
            ),
        ]
    if blockers:
        plan.append(PlanEntry(text=blockers[-1], origin=PlanOrigin.BLOCKER, done=False))
    objective = _latest_string_detail(agent_events, ("current_objective", "objective")) or (
        "Continue supervised work for {}".format(agent.task_id)
        if agent.status in {HarnessRunStatus.PLANNED.value, HarnessRunStatus.RUNNING.value}
        else "No active turn; latest status is {}".format(agent.status)
    )
    return FocusedAgentSnapshot(
        agent=agent,
        last_turn_summary=last_summary,
        current_objective=objective,
        plan=tuple(plan),
        blockers=blockers,
    )


def _agent_snapshot(
    state: RunState,
    events: Sequence[ConsoleEvent],
    now: datetime,
) -> AgentSnapshot:
    agent_events = [
        event
        for event in events
        if event.task_id == state.task_id or event.run_id == state.run_id
    ]
    token_usage = _latest_int_detail(agent_events, ("total_tokens", "tokens", "token_count"))
    budget_usd = _latest_float_detail(agent_events, ("cost_usd", "budget_usd"))
    session_identity = _latest_string_detail(agent_events, ("session_identity",))
    session_identity_label = _latest_string_detail(agent_events, ("session_identity_label",))
    current_turn = state.turns_completed
    if state.status in {HarnessRunStatus.PLANNED, HarnessRunStatus.RUNNING}:
        current_turn = max(1, state.turns_completed + 1)
    return AgentSnapshot(
        agent_id=_agent_id(state.task_id, state.run_id),
        task_id=state.task_id,
        run_id=state.run_id,
        status=state.status.value,
        source_channel=_source_channel(state.task_id),
        workspace_path=state.workspace_path,
        current_turn=current_turn,
        turns_completed=state.turns_completed,
        age_seconds=max(0, int((now - _aware(state.created_at)).total_seconds())),
        updated_seconds_ago=max(0, int((now - _aware(state.updated_at)).total_seconds())),
        token_usage=token_usage,
        budget_usd=budget_usd,
        session_identity=session_identity,
        session_identity_label=session_identity_label,
    )


def _readable_task_event_type(event_type: TaskEventType) -> str:
    return event_type.value.replace("_", " ")


def _task_event_summary(event: TaskEvent) -> str:
    status = " {}".format(event.status) if event.status else ""
    message = ": {}".format(redact_text(event.message)) if event.message else ""
    return "{}{}{}".format(_readable_task_event_type(event.type), status, message)


def _category_for_task_event(event: TaskEvent) -> ConsoleEventCategory:
    if event.type in {TaskEventType.RUN_FAILED, TaskEventType.RUN_BLOCKED}:
        return ConsoleEventCategory.ERROR
    if event.type == TaskEventType.CODEX_RUNTIME_EVENT:
        method = event.payload.get("method")
        if isinstance(method, str) and (
            method.startswith("item/tool") or method.startswith("tool/")
        ):
            return ConsoleEventCategory.TOOL
        return ConsoleEventCategory.CODEX
    if event.type == TaskEventType.ASSISTANT_RESPONSE:
        return ConsoleEventCategory.CODEX
    if event.type in {TaskEventType.CODEX_TURN_STARTED, TaskEventType.CODEX_TURN_COMPLETED}:
        return ConsoleEventCategory.REASONING
    return ConsoleEventCategory.STATUS


def _load_budget_snapshot(snapshot_path: Optional[Path]) -> Mapping[str, Any]:
    if snapshot_path is None or not snapshot_path.exists():
        return {}
    try:
        raw = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, Mapping) else {}


def _rate_limits_from_snapshot(
    raw: Mapping[str, Any],
    snapshot_path: Optional[Path],
) -> Optional[RateLimitTelemetry]:
    source = str(snapshot_path) if snapshot_path is not None else "snapshot"
    rate = raw.get("rate_limits")
    if not isinstance(rate, Mapping):
        rate = raw.get("rate_limit")
    if not isinstance(rate, Mapping):
        return None
    return RateLimitTelemetry(
        state=TelemetryState.AVAILABLE,
        remaining_requests=_optional_int(rate.get("remaining_requests")),
        remaining_tokens=_optional_int(rate.get("remaining_tokens")),
        reset_requests_at=_optional_string(rate.get("reset_requests_at")),
        reset_tokens_at=_optional_string(rate.get("reset_tokens_at")),
        source=source,
        note=_optional_string(rate.get("note")) or "Loaded from local budget snapshot.",
    )


def _usage_from_snapshot(
    raw: Mapping[str, Any],
    snapshot_path: Optional[Path],
) -> Optional[UsageTelemetry]:
    source = str(snapshot_path) if snapshot_path is not None else "snapshot"
    usage = raw.get("usage")
    if not isinstance(usage, Mapping):
        return None
    return UsageTelemetry(
        state=TelemetryState.AVAILABLE,
        daily_usd=_optional_float(usage.get("daily_usd")),
        weekly_usd=_optional_float(usage.get("weekly_usd")),
        monthly_usd=_optional_float(usage.get("monthly_usd")),
        daily_tokens=_optional_int(usage.get("daily_tokens")),
        weekly_tokens=_optional_int(usage.get("weekly_tokens")),
        monthly_tokens=_optional_int(usage.get("monthly_tokens")),
        source=source,
        note=_optional_string(usage.get("note")) or "Loaded from local usage snapshot.",
    )


def _focused_to_json(focused: Optional[FocusedAgentSnapshot]) -> Optional[Dict[str, Any]]:
    if focused is None:
        return None
    return {
        "agent": _dataclass_enum_dict(focused.agent),
        "last_turn_summary": focused.last_turn_summary,
        "current_objective": focused.current_objective,
        "plan": [_dataclass_enum_dict(item) for item in focused.plan],
        "blockers": list(focused.blockers),
    }


def _dataclass_enum_dict(instance: Any) -> Dict[str, Any]:
    raw = dict(instance.__dict__)
    for key, value in list(raw.items()):
        if isinstance(value, Enum):
            raw[key] = value.value
    return raw


def _latest_int_detail(events: Sequence[ConsoleEvent], keys: Sequence[str]) -> Optional[int]:
    for event in reversed(events):
        for key in keys:
            value = event.details.get(key)
            parsed = _optional_int(value)
            if parsed is not None:
                return parsed
    return None


def _latest_float_detail(events: Sequence[ConsoleEvent], keys: Sequence[str]) -> Optional[float]:
    for event in reversed(events):
        for key in keys:
            value = event.details.get(key)
            parsed = _optional_float(value)
            if parsed is not None:
                return parsed
    return None


def _latest_string_detail(events: Sequence[ConsoleEvent], keys: Sequence[str]) -> Optional[str]:
    for event in reversed(events):
        for key in keys:
            value = event.details.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _latest_plan_detail(events: Sequence[ConsoleEvent]) -> Tuple[PlanEntry, ...]:
    for event in reversed(events):
        raw_plan = event.details.get("plan")
        if not isinstance(raw_plan, list):
            raw_plan = event.details.get("checklist")
        if not isinstance(raw_plan, list):
            continue
        parsed = tuple(_parse_plan_item(item) for item in raw_plan)
        parsed = tuple(item for item in parsed if item is not None)
        if parsed:
            return parsed
    return ()


def _parse_plan_item(item: Any) -> Optional[PlanEntry]:
    if isinstance(item, str) and item:
        return PlanEntry(text=item, origin=PlanOrigin.AGENT_GENERATED)
    if not isinstance(item, Mapping):
        return None
    text = item.get("text")
    if not isinstance(text, str) or not text:
        return None
    origin_text = item.get("origin")
    try:
        origin = PlanOrigin(str(origin_text)) if origin_text is not None else PlanOrigin.AGENT_GENERATED
    except ValueError:
        origin = PlanOrigin.AGENT_GENERATED
    return PlanEntry(
        text=text,
        origin=origin,
        done=bool(item.get("done", False)),
    )


def _last_event(events: Sequence[ConsoleEvent], types: Sequence[str]) -> Optional[ConsoleEvent]:
    for event in reversed(events):
        if event.event_type in types:
            return event
    return None


def _event_matches(event: ConsoleEvent, event_filter: str) -> bool:
    needle = event_filter.casefold()
    haystack = " ".join(
        (
            event.category.value,
            event.event_type,
            event.source,
            event.summary,
            event.task_id or "",
            event.run_id or "",
            json.dumps(dict(event.details), sort_keys=True),
        )
    ).casefold()
    return needle in haystack


def _agent_sort_rank(status: str) -> int:
    if status == HarnessRunStatus.RUNNING.value:
        return 0
    if status == HarnessRunStatus.PLANNED.value:
        return 1
    if status in {HarnessRunStatus.FAILED.value, HarnessRunStatus.BLOCKED.value}:
        return 2
    return 3


def _source_channel(task_id: str) -> str:
    if "-" in task_id:
        return task_id.split("-", 1)[0]
    return "unknown"


def _agent_id(task_id: str, run_id: str) -> str:
    return "{}:{}".format(task_id, run_id)


def _has_openai_telemetry_hint(env: Mapping[str, str]) -> bool:
    return any(env.get(name) for name in ("OPENAI_API_KEY", "OPENAI_ADMIN_KEY", "OPENAI_USAGE_API_KEY"))


def _has_openai_admin_hint(env: Mapping[str, str]) -> bool:
    return any(env.get(name) for name in ("OPENAI_ADMIN_KEY", "OPENAI_USAGE_API_KEY"))


def _is_secret_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return bool(_SECRET_KEY_RE.search(normalized))


def _is_private_body_key(key: str, parent_key: Optional[str] = None) -> bool:
    normalized = key.casefold().replace("-", "_")
    parent = (parent_key or "").casefold().replace("-", "_")
    if normalized == "text":
        return parent in {"message", "telegram", "telegram_update", "source", "task", ""}
    return normalized in _PRIVATE_BODY_KEYS or normalized.endswith("_message_text")


def _nested(raw: Mapping[str, Any], path: Sequence[str]) -> Any:
    value: Any = raw
    for part in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def _first_float(*values: Any) -> Optional[float]:
    for value in values:
        parsed = _optional_float(value)
        if parsed is not None:
            return parsed
    return None


def _optional_string(value: Any) -> Optional[str]:
    if isinstance(value, str) and value:
        return value
    return None


def _optional_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _optional_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (float, int)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _display(value: Any) -> str:
    if value is None:
        return "unknown"
    return str(value)


def _money(value: Optional[float]) -> str:
    if value is None:
        return "unknown"
    return "{:.2f}".format(value)


def _event_id() -> str:
    return "evt-{}".format(uuid.uuid4().hex[:12])


def _now_iso() -> str:
    return _iso(datetime.now(timezone.utc))


def _iso(value: datetime) -> str:
    return _aware(value).isoformat()


_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|secret|password|authorization|auth[_-]?header|bearer|bot[_-]?token|access[_-]?token|refresh[_-]?token)"
)
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{10,}\b", re.IGNORECASE),
    re.compile(r"\b\d{5,}:[A-Za-z0-9_\-]{10,}\b"),
)
_PRIVATE_BODY_KEYS = {
    "body",
    "content",
    "message_body",
    "message_text",
    "owner_profile",
    "owner_profile_excerpt",
    "prompt",
    "profile",
    "profile_excerpt",
    "raw_body",
    "raw_content",
    "raw_message",
    "raw_text",
    "task_text",
    "telegram_message_text",
    "wiki_profile_excerpt",
}
