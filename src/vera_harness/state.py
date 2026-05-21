"""Persistent run-state storage for Vera orchestration."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from .models import HarnessRunStatus, RunState, TelegramTask


class RunStateError(RuntimeError):
    """Raised when persisted run state cannot be loaded or written."""


class JsonRunStateStore:
    """Small JSON store for restart-safe task run state."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def active_run_for_task(self, task_id: str) -> Optional[RunState]:
        state = self.run_for_task(task_id)
        if state is not None and state.is_active:
            return state
        return None

    def run_for_task(self, task_id: str) -> Optional[RunState]:
        payload = self._load()
        raw = payload.get("runs", {}).get(task_id)
        if not isinstance(raw, Mapping):
            return None
        return _run_state_from_json(raw)

    def all_runs(self) -> Tuple[RunState, ...]:
        runs = self._load().get("runs", {})
        if not isinstance(runs, Mapping):
            return ()
        return tuple(
            _run_state_from_json(raw)
            for raw in runs.values()
            if isinstance(raw, Mapping)
        )

    def create_run(self, task: TelegramTask, run_id: str, dry_run: bool) -> RunState:
        active = self.active_run_for_task(task.task_id)
        if active is not None:
            return active
        state = RunState(
            run_id=run_id,
            task_id=task.task_id,
            status=HarnessRunStatus.PLANNED,
            dry_run=dry_run,
        )
        self.save_run(state)
        return state

    def save_run(self, state: RunState) -> RunState:
        updated = replace(state, updated_at=datetime.now(timezone.utc))
        payload = self._load()
        runs = payload.setdefault("runs", {})
        if not isinstance(runs, dict):
            runs = {}
            payload["runs"] = runs
        runs[updated.task_id] = _run_state_to_json(updated)
        self._write(payload)
        return updated

    def _load(self) -> Dict[str, Any]:
        if not self._path.exists():
            return {"runs": {}}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RunStateError("run state file is not valid JSON: {}".format(exc))
        if not isinstance(raw, dict):
            raise RunStateError("run state file must contain a JSON object")
        runs = raw.get("runs")
        if not isinstance(runs, dict):
            raw["runs"] = {}
        return raw

    def _write(self, payload: Mapping[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_name("{}.tmp".format(self._path.name))
        temp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self._path)


def _run_state_to_json(state: RunState) -> Dict[str, Any]:
    return {
        "run_id": state.run_id,
        "task_id": state.task_id,
        "status": state.status.value,
        "turns_completed": state.turns_completed,
        "dry_run": state.dry_run,
        "workspace_path": state.workspace_path,
        "memory_pages_used": list(state.memory_pages_used),
        "last_error": state.last_error,
        "last_decision": state.last_decision,
        "created_at": state.created_at.isoformat(),
        "updated_at": state.updated_at.isoformat(),
    }


def _run_state_from_json(raw: Mapping[str, Any]) -> RunState:
    run_id = _required_string(raw, "run_id")
    task_id = _required_string(raw, "task_id")
    status = HarnessRunStatus(_required_string(raw, "status"))
    return RunState(
        run_id=run_id,
        task_id=task_id,
        status=status,
        turns_completed=_optional_int(raw.get("turns_completed")),
        dry_run=bool(raw.get("dry_run", False)),
        workspace_path=_optional_string(raw.get("workspace_path")),
        memory_pages_used=_optional_string_tuple(raw.get("memory_pages_used")),
        last_error=_optional_string(raw.get("last_error")),
        last_decision=_optional_string(raw.get("last_decision")),
        created_at=_optional_datetime(raw.get("created_at")),
        updated_at=_optional_datetime(raw.get("updated_at")),
    )


def _required_string(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise RunStateError("run state is missing required string field: {}".format(key))
    return value


def _optional_string(value: Any) -> Optional[str]:
    if isinstance(value, str) and value:
        return value
    return None


def _optional_int(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _optional_string_tuple(value: Any) -> Tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    result = []
    for item in value:
        if isinstance(item, str) and item:
            result.append(item)
    return tuple(result)


def _optional_datetime(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(timezone.utc)
