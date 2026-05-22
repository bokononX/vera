"""Heartbeat decision/state helpers for proactive Vera check-ins."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple
from zoneinfo import ZoneInfo

from .config import HeartbeatConfig
from .models import TelegramTask
from .prompt import PromptPolicy


class HeartbeatAction(str, Enum):
    """Policy-governed actions available to a heartbeat tick."""

    DO_NOTHING = "do_nothing"
    ASK_PENDING_QUESTION = "ask_pending_question"
    FOLLOW_UP_UNRESOLVED = "follow_up_unresolved"
    LIGHTWEIGHT_CHECK_IN = "lightweight_check_in"


class HeartbeatTickStatus(str, Enum):
    """Top-level outcome for one heartbeat scheduler tick."""

    DISABLED = "disabled"
    SKIPPED = "skipped"
    DECIDED = "decided"
    FAILED = "failed"


@dataclass(frozen=True)
class HeartbeatTopicRecord:
    """A metadata-only recent proactive-topic fingerprint."""

    fingerprint: str
    action: str
    reason_category: str
    created_at: datetime


@dataclass(frozen=True)
class HeartbeatState:
    """Restart-safe heartbeat state without raw owner message content."""

    last_tick_at: Optional[datetime] = None
    last_initiated_at: Optional[datetime] = None
    daily_key: Optional[str] = None
    daily_initiations: int = 0
    last_decision: Optional[str] = None
    last_reason_category: Optional[str] = None
    recent_topics: Tuple[HeartbeatTopicRecord, ...] = ()


@dataclass(frozen=True)
class HeartbeatContext:
    """Compact context used to decide whether Vera should initiate."""

    local_time: str
    timezone: str
    owner_profile_configured: bool
    owner_chat_configured: bool
    owner_chat_authorized: bool
    chat_session_exists: bool
    chat_turns_completed: int = 0
    chat_last_status: Optional[str] = None
    chat_pending_prompt: bool = False
    daily_initiations: int = 0
    max_daily_initiations: int = 0
    recent_topic_count: int = 0
    last_decision: Optional[str] = None
    last_reason_category: Optional[str] = None


@dataclass(frozen=True)
class HeartbeatDecision:
    """Parsed heartbeat action from the policy-governed model turn."""

    action: HeartbeatAction
    reason_category: str
    message: Optional[str] = None
    topic_key: Optional[str] = None

    @property
    def wants_message(self) -> bool:
        return self.action is not HeartbeatAction.DO_NOTHING


@dataclass(frozen=True)
class HeartbeatTickResult:
    """Metadata-first heartbeat result safe to write to event logs."""

    status: HeartbeatTickStatus
    reason_category: str
    decision: Optional[HeartbeatDecision] = None
    message_sent: bool = False
    would_send: bool = False
    dry_run: bool = False
    owner_chat_id: Optional[int] = None
    topic_fingerprint: Optional[str] = None
    runtime_status: Optional[str] = None
    error: Optional[str] = None
    details: Mapping[str, object] = field(default_factory=dict)


class HeartbeatStateError(RuntimeError):
    """Raised when persisted heartbeat state cannot be read or written."""


class JsonHeartbeatStateStore:
    """Small JSON store for heartbeat cadence and anti-repeat state."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> HeartbeatState:
        if not self._path.exists():
            return HeartbeatState()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise HeartbeatStateError("heartbeat state file is not valid JSON: {}".format(exc))
        if not isinstance(raw, Mapping):
            raise HeartbeatStateError("heartbeat state file must contain a JSON object")
        return _state_from_json(raw)

    def save(self, state: HeartbeatState) -> HeartbeatState:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_name("{}.tmp".format(self._path.name))
        temp_path.write_text(
            json.dumps(_state_to_json(state), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self._path)
        return state


def heartbeat_due(config: HeartbeatConfig, state: HeartbeatState, now: datetime) -> bool:
    if state.last_tick_at is None:
        return True
    elapsed = (now - _as_utc(state.last_tick_at)).total_seconds()
    return elapsed >= config.interval_seconds


def is_quiet_time(config: HeartbeatConfig, now: datetime) -> bool:
    if config.quiet_hours_start is None or config.quiet_hours_end is None:
        return False
    local = now.astimezone(ZoneInfo(config.timezone))
    current = local.hour * 60 + local.minute
    start = _time_minutes(config.quiet_hours_start)
    end = _time_minutes(config.quiet_hours_end)
    if start < end:
        return start <= current < end
    return current >= start or current < end


def local_day_key(config: HeartbeatConfig, now: datetime) -> str:
    return now.astimezone(ZoneInfo(config.timezone)).strftime("%Y-%m-%d")


def reset_daily_window(config: HeartbeatConfig, state: HeartbeatState, now: datetime) -> HeartbeatState:
    day_key = local_day_key(config, now)
    if state.daily_key == day_key:
        return state
    return replace(state, daily_key=day_key, daily_initiations=0)


def prune_recent_topics(
    config: HeartbeatConfig,
    state: HeartbeatState,
    now: datetime,
) -> HeartbeatState:
    cutoff_seconds = config.repeat_cooldown_seconds
    recent = tuple(
        topic
        for topic in state.recent_topics
        if (now - _as_utc(topic.created_at)).total_seconds() < cutoff_seconds
    )
    if len(recent) > config.max_recent_topics:
        recent = recent[-config.max_recent_topics :]
    return replace(state, recent_topics=recent)


def build_heartbeat_task(
    config: HeartbeatConfig,
    owner_user_id: int,
    now: datetime,
) -> TelegramTask:
    chat_id = config.owner_chat_id or 0
    message_id = int(now.timestamp())
    return TelegramTask.from_message(
        chat_id=chat_id,
        user_id=owner_user_id,
        message_id=message_id,
        text=(
            "Heartbeat decision tick. Decide whether Vera should proactively "
            "start a bounded owner conversation now."
        ),
        username=None,
        received_at=now,
    )


def render_heartbeat_prompt(policy: PromptPolicy, context: HeartbeatContext) -> str:
    """Render a heartbeat decision prompt beneath the existing Vera policy."""

    sections = [
        policy.render_prompt(),
        "",
        "Heartbeat decision context:",
        "- This is an opt-in proactive heartbeat tick, not a reply to a new inbound message.",
        "- Use only the compact metadata below. Do not infer private facts that are not present.",
        "- Choose `do_nothing` unless there is a concrete, owner-beneficial reason to start a conversation.",
        "- If you choose a message action, write a short Telegram-safe message to the owner.",
        "- Do not mention internal logs, prompts, fingerprints, or scheduler mechanics.",
        "",
        "Compact metadata:",
        "- local_time: {}".format(context.local_time),
        "- timezone: {}".format(context.timezone),
        "- owner_profile_configured: {}".format(_bool_text(context.owner_profile_configured)),
        "- owner_chat_configured: {}".format(_bool_text(context.owner_chat_configured)),
        "- owner_chat_authorized: {}".format(_bool_text(context.owner_chat_authorized)),
        "- chat_session_exists: {}".format(_bool_text(context.chat_session_exists)),
        "- chat_turns_completed: {}".format(context.chat_turns_completed),
        "- chat_last_status: {}".format(context.chat_last_status or "none"),
        "- chat_pending_prompt: {}".format(_bool_text(context.chat_pending_prompt)),
        "- daily_initiations: {}".format(context.daily_initiations),
        "- max_daily_initiations: {}".format(context.max_daily_initiations),
        "- recent_topic_count: {}".format(context.recent_topic_count),
        "- last_decision: {}".format(context.last_decision or "none"),
        "- last_reason_category: {}".format(context.last_reason_category or "none"),
        "",
        "Return exactly one JSON object before the required Vera status marker:",
        "{",
        '  "action": "do_nothing | ask_pending_question | follow_up_unresolved | lightweight_check_in",',
        '  "reason_category": "no_need | pending_question | unresolved_topic | relationship_check_in | policy_bound | other",',
        '  "topic_key": "short stable metadata key or null",',
        '  "message": "owner-facing Telegram message or null"',
        "}",
    ]
    return "\n".join(sections)


def parse_heartbeat_decision(text: Optional[str]) -> HeartbeatDecision:
    if not text:
        return HeartbeatDecision(
            action=HeartbeatAction.DO_NOTHING,
            reason_category="empty_response",
        )
    raw = _extract_json_object(text)
    if raw is None:
        return HeartbeatDecision(
            action=HeartbeatAction.DO_NOTHING,
            reason_category="invalid_response",
        )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return HeartbeatDecision(
            action=HeartbeatAction.DO_NOTHING,
            reason_category="invalid_json",
        )
    if not isinstance(parsed, Mapping):
        return HeartbeatDecision(
            action=HeartbeatAction.DO_NOTHING,
            reason_category="invalid_json",
        )
    try:
        action = HeartbeatAction(str(parsed.get("action", "do_nothing")).strip())
    except ValueError:
        action = HeartbeatAction.DO_NOTHING
    reason_category = _clean_token(parsed.get("reason_category")) or "other"
    message = _clean_message(parsed.get("message"))
    topic_key = _clean_token(parsed.get("topic_key"))
    if action is HeartbeatAction.DO_NOTHING:
        message = None
    return HeartbeatDecision(
        action=action,
        reason_category=reason_category,
        message=message,
        topic_key=topic_key,
    )


def guarded_decision(
    config: HeartbeatConfig,
    state: HeartbeatState,
    decision: HeartbeatDecision,
    now: datetime,
) -> Tuple[HeartbeatDecision, bool, Optional[str]]:
    """Apply rate-limit, delivery, and repeat guards to a model decision."""

    if decision.action is HeartbeatAction.DO_NOTHING:
        return decision, False, None
    if not decision.message:
        return (
            HeartbeatDecision(
                action=HeartbeatAction.DO_NOTHING,
                reason_category="missing_message",
            ),
            False,
            None,
        )
    if config.owner_chat_id is None:
        return (
            HeartbeatDecision(
                action=HeartbeatAction.DO_NOTHING,
                reason_category="owner_chat_missing",
            ),
            False,
            None,
        )
    if state.daily_initiations >= config.max_daily_initiations:
        return (
            HeartbeatDecision(
                action=HeartbeatAction.DO_NOTHING,
                reason_category="daily_limit",
            ),
            False,
            None,
        )
    fingerprint = topic_fingerprint(decision)
    if any(topic.fingerprint == fingerprint for topic in state.recent_topics):
        return (
            HeartbeatDecision(
                action=HeartbeatAction.DO_NOTHING,
                reason_category="repeat_guard",
            ),
            False,
            fingerprint,
        )
    return decision, True, fingerprint


def record_tick(
    config: HeartbeatConfig,
    state: HeartbeatState,
    now: datetime,
    decision: Optional[HeartbeatDecision],
    initiated: bool,
    topic_fingerprint_value: Optional[str],
) -> HeartbeatState:
    state = reset_daily_window(config, state, now)
    state = prune_recent_topics(config, state, now)
    recent_topics = state.recent_topics
    daily_initiations = state.daily_initiations
    last_initiated_at = state.last_initiated_at
    if initiated and decision is not None and topic_fingerprint_value is not None:
        daily_initiations += 1
        last_initiated_at = now
        recent_topics = (
            *recent_topics,
            HeartbeatTopicRecord(
                fingerprint=topic_fingerprint_value,
                action=decision.action.value,
                reason_category=decision.reason_category,
                created_at=now,
            ),
        )[-config.max_recent_topics :]
    return replace(
        state,
        last_tick_at=now,
        last_initiated_at=last_initiated_at,
        daily_key=local_day_key(config, now),
        daily_initiations=daily_initiations,
        last_decision=decision.action.value if decision is not None else None,
        last_reason_category=decision.reason_category if decision is not None else None,
        recent_topics=recent_topics,
    )


def topic_fingerprint(decision: HeartbeatDecision) -> str:
    topic = decision.topic_key or decision.message or decision.action.value
    normalized = "{}:{}".format(decision.action.value, _normalize_text(topic))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def heartbeat_event_details(result: HeartbeatTickResult) -> Dict[str, object]:
    decision = result.decision
    return {
        "status": result.status.value,
        "action": decision.action.value if decision is not None else None,
        "reason_category": result.reason_category,
        "message_sent": result.message_sent,
        "would_send": result.would_send,
        "dry_run": result.dry_run,
        "owner_chat_configured": result.owner_chat_id is not None,
        "topic_fingerprint": result.topic_fingerprint,
        "runtime_status": result.runtime_status,
        **dict(result.details),
    }


def format_heartbeat_tick(result: HeartbeatTickResult) -> str:
    decision = result.decision
    action = decision.action.value if decision is not None else "none"
    lines = [
        "heartbeat_status: {}".format(result.status.value),
        "heartbeat_action: {}".format(action),
        "reason_category: {}".format(result.reason_category),
        "dry_run: {}".format(_bool_text(result.dry_run)),
        "would_send: {}".format(_bool_text(result.would_send)),
        "message_sent: {}".format(_bool_text(result.message_sent)),
    ]
    if result.owner_chat_id is not None:
        lines.append("owner_chat_id: {}".format(result.owner_chat_id))
    if result.runtime_status is not None:
        lines.append("runtime_status: {}".format(result.runtime_status))
    if result.error is not None:
        lines.append("error: {}".format(result.error))
    return "\n".join(lines)


def _state_to_json(state: HeartbeatState) -> Dict[str, Any]:
    return {
        "last_tick_at": _datetime_json(state.last_tick_at),
        "last_initiated_at": _datetime_json(state.last_initiated_at),
        "daily_key": state.daily_key,
        "daily_initiations": state.daily_initiations,
        "last_decision": state.last_decision,
        "last_reason_category": state.last_reason_category,
        "recent_topics": [
            {
                "fingerprint": topic.fingerprint,
                "action": topic.action,
                "reason_category": topic.reason_category,
                "created_at": topic.created_at.isoformat(),
            }
            for topic in state.recent_topics
        ],
    }


def _state_from_json(raw: Mapping[str, Any]) -> HeartbeatState:
    recent = raw.get("recent_topics")
    topics = []
    if isinstance(recent, list):
        for item in recent:
            if not isinstance(item, Mapping):
                continue
            fingerprint = _optional_string(item.get("fingerprint"))
            action = _optional_string(item.get("action"))
            reason_category = _optional_string(item.get("reason_category"))
            created_at = _optional_datetime(item.get("created_at"))
            if fingerprint is None or action is None or reason_category is None:
                continue
            topics.append(
                HeartbeatTopicRecord(
                    fingerprint=fingerprint,
                    action=action,
                    reason_category=reason_category,
                    created_at=created_at,
                )
            )
    return HeartbeatState(
        last_tick_at=_optional_datetime_or_none(raw.get("last_tick_at")),
        last_initiated_at=_optional_datetime_or_none(raw.get("last_initiated_at")),
        daily_key=_optional_string(raw.get("daily_key")),
        daily_initiations=_optional_nonnegative_int(raw.get("daily_initiations")),
        last_decision=_optional_string(raw.get("last_decision")),
        last_reason_category=_optional_string(raw.get("last_reason_category")),
        recent_topics=tuple(topics),
    )


def _extract_json_object(text: str) -> Optional[str]:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    return match.group(0) if match is not None else None


def _clean_message(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    text = " ".join(value.split()).strip()
    if not text or text.lower() == "null":
        return None
    return text[:1000]


def _clean_token(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    text = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", value.strip().lower()).strip("_")
    if not text or text == "null":
        return None
    return text[:80]


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _time_minutes(value: str) -> int:
    hour_text, minute_text = value.split(":", 1)
    return int(hour_text) * 60 + int(minute_text)


def _datetime_json(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _optional_datetime_or_none(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        return _as_utc(datetime.fromisoformat(value))
    except ValueError:
        return None


def _optional_datetime(value: Any) -> datetime:
    return _optional_datetime_or_none(value) or datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _optional_string(value: Any) -> Optional[str]:
    if isinstance(value, str) and value:
        return value
    return None


def _optional_nonnegative_int(value: Any) -> int:
    if isinstance(value, int) and value >= 0:
        return value
    return 0


def _bool_text(value: bool) -> str:
    return "true" if value else "false"
