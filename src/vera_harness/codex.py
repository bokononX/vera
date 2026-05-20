"""Codex runtime planning boundary.

This module intentionally does not launch Codex. It records the command and
runtime settings a future app-server adapter will execute.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import CommandSpec, HarnessConfig
from .models import Workspace


@dataclass(frozen=True)
class CodexInvocation:
    """A planned Codex app-server invocation for one harness run."""

    command: CommandSpec
    workspace_path: Path
    prompt: str
    max_turns: int
    turn_timeout_seconds: int
    run_timeout_seconds: int
    approval_policy: str
    sandbox_mode: str
    repo_clone_command: Optional[CommandSpec] = None
    repo_bootstrap_command: Optional[CommandSpec] = None

    @property
    def display_command(self) -> str:
        return self.command.display


class CodexRuntimePlanner:
    """Builds Codex runtime plans without performing side effects."""

    def __init__(self, config: HarnessConfig) -> None:
        self._config = config

    def plan(self, workspace: Workspace, prompt: str) -> CodexInvocation:
        return CodexInvocation(
            command=self._config.codex_app_server_command,
            workspace_path=workspace.path,
            prompt=prompt,
            max_turns=self._config.max_turns,
            turn_timeout_seconds=self._config.turn_timeout_seconds,
            run_timeout_seconds=self._config.run_timeout_seconds,
            approval_policy=self._config.approval_policy,
            sandbox_mode=self._config.sandbox_mode,
            repo_clone_command=self._config.repo_clone_command,
            repo_bootstrap_command=self._config.repo_bootstrap_command,
        )
