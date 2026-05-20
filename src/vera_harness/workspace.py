"""Workspace management for per-task Codex runs."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .config import CommandSpec, HarnessConfig
from .models import (
    TelegramTask,
    Workspace,
    WorkspaceBootstrapStatus,
    WorkspaceReusePolicy,
)


class WorkspaceError(RuntimeError):
    """Raised when workspace lifecycle constraints cannot be satisfied."""


class WorkspaceBootstrapError(WorkspaceError):
    """Raised when a configured workspace bootstrap command fails."""

    def __init__(self, message: str, workspace: Workspace) -> None:
        super().__init__(message)
        self.workspace = workspace


class WorkspaceManager:
    """Creates, reuses, bootstraps, and cleans isolated task workspaces."""

    _METADATA_FILENAME = ".vera_workspace.json"

    def __init__(self, config: HarnessConfig) -> None:
        self._config = config
        self._root = config.workspace_root.resolve()

    def workspace_for_task(self, task: TelegramTask, create: bool = False) -> Workspace:
        """Backward-compatible workspace resolution used by dry-run planning."""

        return self.prepare_workspace(
            task,
            policy=WorkspaceReusePolicy.REUSE,
            create=create,
            run_bootstrap=False,
        )

    def prepare_workspace(
        self,
        task: TelegramTask,
        policy: WorkspaceReusePolicy = WorkspaceReusePolicy.REUSE,
        create: bool = True,
        run_bootstrap: bool = True,
    ) -> Workspace:
        """Resolve and prepare a task workspace according to an explicit policy."""

        workspace_id = _safe_workspace_id(task.task_id)
        if create:
            self._ensure_root()
        elif self._root.exists() and not self._root.is_dir():
            raise WorkspaceError("workspace root is not a directory: {}".format(self._root))
        path = self._workspace_path(workspace_id)
        exists = path.exists()

        if exists and policy == WorkspaceReusePolicy.FRESH:
            self.cleanup_workspace_path(path)
            exists = False
        elif not exists and policy == WorkspaceReusePolicy.REQUIRE_EXISTING:
            raise WorkspaceError("workspace does not exist for task: {}".format(task.task_id))

        if create and not exists:
            path.mkdir(parents=False, exist_ok=False)
            exists = True
            created = True
            reused = False
        else:
            created = False
            reused = exists and not created

        if create or exists:
            resolved = path.resolve()
            _ensure_under_root(self._root, resolved)
            if resolved != path:
                raise WorkspaceError("workspace path resolves through a symlink: {}".format(path))

        workspace = self._workspace(
            workspace_id=workspace_id,
            task=task,
            path=path,
            created=created,
            reused=reused,
            policy=policy,
            bootstrap_status=(
                WorkspaceBootstrapStatus.SKIPPED
                if not run_bootstrap
                else WorkspaceBootstrapStatus.NOT_CONFIGURED
            ),
        )

        if create or exists:
            self._write_metadata(workspace)

        if run_bootstrap and (created or policy == WorkspaceReusePolicy.FRESH):
            try:
                workspace = self._run_bootstrap(workspace)
            except WorkspaceBootstrapError as exc:
                self._write_metadata(exc.workspace)
                raise
            self._write_metadata(workspace)

        return workspace

    def cleanup_workspace(self, workspace: Workspace) -> None:
        """Remove one managed workspace after validating root containment."""

        self.cleanup_workspace_path(workspace.path)

    def cleanup_workspace_path(self, path: Path) -> None:
        """Remove one workspace path, refusing any path outside the workspace root."""

        raw_path = Path(path)
        _ensure_under_root(self._root, raw_path.absolute())
        if raw_path.is_symlink():
            raise WorkspaceError("refusing to clean symlink workspace: {}".format(raw_path))
        if not raw_path.exists():
            return
        resolved = raw_path.resolve()
        _ensure_under_root(self._root, resolved)
        if resolved == self._root:
            raise WorkspaceError("refusing to clean workspace root")
        shutil.rmtree(resolved)

    def validate_cwd(self, cwd: Path) -> Path:
        """Return a resolved cwd only if it is inside the configured workspace root."""

        resolved = Path(cwd).expanduser().resolve()
        _ensure_under_root(self._root, resolved)
        return resolved

    def _ensure_root(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        if not self._root.is_dir():
            raise WorkspaceError("workspace root is not a directory: {}".format(self._root))

    def _workspace_path(self, workspace_id: str) -> Path:
        path = self._root / workspace_id
        _ensure_under_root(self._root, path.absolute())
        return path

    def _workspace(
        self,
        workspace_id: str,
        task: TelegramTask,
        path: Path,
        created: bool,
        reused: bool,
        policy: WorkspaceReusePolicy,
        bootstrap_status: WorkspaceBootstrapStatus,
        bootstrap_stdout: str = "",
        bootstrap_stderr: str = "",
        bootstrap_returncode: Optional[int] = None,
        bootstrap_error: Optional[str] = None,
    ) -> Workspace:
        return Workspace(
            workspace_id=workspace_id,
            task_id=task.task_id,
            root=self._root,
            path=path,
            created=created,
            reused=reused,
            reuse_policy=policy,
            metadata_path=path / self._METADATA_FILENAME,
            bootstrap_status=bootstrap_status,
            bootstrap_stdout=bootstrap_stdout,
            bootstrap_stderr=bootstrap_stderr,
            bootstrap_returncode=bootstrap_returncode,
            bootstrap_error=bootstrap_error,
            repo_clone_command=(
                self._config.repo_clone_command.display if self._config.repo_clone_command else None
            ),
            repo_bootstrap_command=(
                self._config.repo_bootstrap_command.display
                if self._config.repo_bootstrap_command
                else None
            ),
        )

    def _run_bootstrap(self, workspace: Workspace) -> Workspace:
        commands = [
            command
            for command in (self._config.repo_clone_command, self._config.repo_bootstrap_command)
            if command is not None
        ]
        if not commands:
            return replace(workspace, bootstrap_status=WorkspaceBootstrapStatus.NOT_CONFIGURED)

        stdout_parts: List[str] = []
        stderr_parts: List[str] = []
        for command in commands:
            try:
                result = self._run_command(command, workspace.path)
            except subprocess.TimeoutExpired as exc:
                timed_out = replace(
                    workspace,
                    bootstrap_status=WorkspaceBootstrapStatus.TIMED_OUT,
                    bootstrap_stdout="".join(stdout_parts) + _coerce_output(exc.stdout),
                    bootstrap_stderr="".join(stderr_parts) + _coerce_output(exc.stderr),
                    bootstrap_error="bootstrap command timed out: {}".format(command.display),
                )
                raise WorkspaceBootstrapError(
                    timed_out.bootstrap_error or "bootstrap timed out",
                    timed_out,
                )
            stdout_parts.append(_command_output_header(command, result.stdout))
            stderr_parts.append(_command_output_header(command, result.stderr))
            if result.returncode != 0:
                failed = replace(
                    workspace,
                    bootstrap_status=WorkspaceBootstrapStatus.FAILED,
                    bootstrap_stdout="".join(stdout_parts),
                    bootstrap_stderr="".join(stderr_parts),
                    bootstrap_returncode=result.returncode,
                    bootstrap_error="bootstrap command failed: {}".format(command.display),
                )
                raise WorkspaceBootstrapError(failed.bootstrap_error or "bootstrap failed", failed)

        return replace(
            workspace,
            bootstrap_status=WorkspaceBootstrapStatus.SUCCEEDED,
            bootstrap_stdout="".join(stdout_parts),
            bootstrap_stderr="".join(stderr_parts),
            bootstrap_returncode=0,
        )

    def _run_command(self, command: CommandSpec, cwd: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            command.argv,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=self._config.workspace_bootstrap_timeout_seconds,
            check=False,
        )

    def _write_metadata(self, workspace: Workspace) -> None:
        if workspace.metadata_path is None:
            return
        payload = {
            "workspace_id": workspace.workspace_id,
            "task_id": workspace.task_id,
            "root": str(workspace.root),
            "path": str(workspace.path),
            "created": workspace.created,
            "reused": workspace.reused,
            "reuse_policy": workspace.reuse_policy.value,
            "retention_policy": self._config.workspace_retention_policy,
            "bootstrap_status": workspace.bootstrap_status.value,
            "bootstrap_returncode": workspace.bootstrap_returncode,
            "bootstrap_error": workspace.bootstrap_error,
            "bootstrap_stdout": workspace.bootstrap_stdout,
            "bootstrap_stderr": workspace.bootstrap_stderr,
            "repo_clone_command": workspace.repo_clone_command,
            "repo_bootstrap_command": workspace.repo_bootstrap_command,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        workspace.metadata_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _safe_workspace_id(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")
    if not slug:
        raise ValueError("task id does not contain usable workspace characters")
    if slug in {".", ".."}:
        raise ValueError("task id resolves to a reserved workspace name")
    return slug[:120]


def _ensure_under_root(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError:
        raise WorkspaceError("path escapes workspace root: {}".format(path))


def _command_output_header(command: CommandSpec, output: str) -> str:
    if not output:
        return ""
    return "$ {}\n{}".format(command.display, output)


def _coerce_output(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)
