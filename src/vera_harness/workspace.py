"""Workspace management for per-task Codex runs."""

from __future__ import annotations

import re
from pathlib import Path

from .config import HarnessConfig
from .models import TelegramTask, Workspace


class WorkspaceManager:
    """Resolves and optionally creates isolated task workspaces."""

    def __init__(self, config: HarnessConfig) -> None:
        self._config = config

    def workspace_for_task(self, task: TelegramTask, create: bool = False) -> Workspace:
        workspace_id = _safe_workspace_id(task.task_id)
        path = (self._config.workspace_root / workspace_id).resolve()
        created = False
        if create:
            path.mkdir(parents=True, exist_ok=True)
            created = True
        return Workspace(
            workspace_id=workspace_id,
            task_id=task.task_id,
            root=self._config.workspace_root,
            path=path,
            created=created,
            repo_clone_command=(
                self._config.repo_clone_command.display if self._config.repo_clone_command else None
            ),
            repo_bootstrap_command=(
                self._config.repo_bootstrap_command.display
                if self._config.repo_bootstrap_command
                else None
            ),
        )


def _safe_workspace_id(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")
    if not slug:
        raise ValueError("task id does not contain usable workspace characters")
    return slug[:120]
