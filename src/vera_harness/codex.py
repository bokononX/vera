"""Codex app-server runtime boundary."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from dataclasses import dataclass, field, replace as dataclass_replace
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from . import __version__
from .config import CommandSpec, ConfigError, HarnessConfig
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


class CodexRunStatus(str, Enum):
    """Terminal status for one app-server driven Codex turn."""

    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    APPROVAL_REQUIRED = "approval_required"
    INPUT_REQUIRED = "input_required"


class CodexRuntimeEventType(str, Enum):
    """Structured events emitted while driving the app-server."""

    PROCESS_STARTED = "process_started"
    INITIALIZED = "initialized"
    THREAD_STARTED = "thread_started"
    TURN_STARTED = "turn_started"
    NOTIFICATION = "notification"
    APPROVAL_REQUIRED = "approval_required"
    INPUT_REQUIRED = "input_required"
    AUTO_RESPONSE_SENT = "auto_response_sent"
    TURN_COMPLETED = "turn_completed"
    TURN_FAILED = "turn_failed"
    TURN_CANCELLED = "turn_cancelled"
    TIMED_OUT = "timed_out"
    PROCESS_EXITED = "process_exited"
    ERROR = "error"


@dataclass(frozen=True)
class CodexRuntimeEvent:
    """A harness-level event derived from app-server JSON-RPC traffic."""

    type: CodexRuntimeEventType
    method: Optional[str] = None
    message: Optional[str] = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    thread_id: Optional[str] = None
    turn_id: Optional[str] = None
    elapsed_seconds: Optional[float] = None


@dataclass(frozen=True)
class CodexSessionMetadata:
    """Final session details suitable for status messages and logs."""

    command: str
    cwd: Path
    approval_policy: str
    sandbox_mode: str
    user_agent: Optional[str] = None
    codex_home: Optional[str] = None
    thread_id: Optional[str] = None
    turn_id: Optional[str] = None
    model: Optional[str] = None
    model_provider: Optional[str] = None


@dataclass(frozen=True)
class CodexRunResult:
    """Terminal result for one app-server driven Codex turn."""

    status: CodexRunStatus
    metadata: CodexSessionMetadata
    events: Tuple[CodexRuntimeEvent, ...]
    error: Optional[str] = None
    elapsed_seconds: Optional[float] = None
    assistant_response: Optional[str] = None
    pending_prompt: Optional[str] = None


@dataclass(frozen=True)
class CodexPendingRequest:
    """A pending server request that can be answered by the next chat message."""

    status: CodexRunStatus
    method: str
    request_id: Any
    prompt: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    thread_id: Optional[str] = None
    turn_id: Optional[str] = None


class CodexAppServerError(RuntimeError):
    """Raised for adapter/protocol failures before a result can be returned."""


ProcessFactory = Callable[[Sequence[str], Path], subprocess.Popen]
EventCallback = Callable[[CodexRuntimeEvent], None]


class CodexRuntimePlanner:
    """Builds Codex runtime plans without performing side effects."""

    def __init__(self, config: HarnessConfig) -> None:
        self._config = config

    def plan(self, workspace: Workspace, prompt: str) -> CodexInvocation:
        workspace_path = _validated_workspace_path(self._config.workspace_root, workspace.path)
        return CodexInvocation(
            command=self._config.codex_app_server_command,
            workspace_path=workspace_path,
            prompt=prompt,
            max_turns=self._config.max_turns,
            turn_timeout_seconds=self._config.turn_timeout_seconds,
            run_timeout_seconds=self._config.run_timeout_seconds,
            approval_policy=self._config.approval_policy,
            sandbox_mode=self._config.sandbox_mode,
            repo_clone_command=self._config.repo_clone_command,
            repo_bootstrap_command=self._config.repo_bootstrap_command,
        )


class CodexAppServerRuntime:
    """Launch and drive Codex app-server over newline-delimited JSON-RPC."""

    def __init__(
        self,
        config: HarnessConfig,
        process_factory: Optional[ProcessFactory] = None,
    ) -> None:
        self._config = config
        self._resolve_process_command = process_factory is None
        self._process_factory = process_factory or _default_process_factory

    def run_turn(
        self,
        invocation: CodexInvocation,
        on_event: Optional[EventCallback] = None,
    ) -> CodexRunResult:
        """Run one configured Codex turn and return the terminal outcome."""

        workspace_path = _validated_workspace_path(
            self._config.workspace_root,
            invocation.workspace_path,
        )
        if not workspace_path.is_dir():
            raise CodexAppServerError(
                "workspace does not exist: {}".format(workspace_path)
            )
        invocation = dataclass_replace(invocation, workspace_path=workspace_path)

        started_at = time.monotonic()
        events: List[CodexRuntimeEvent] = []
        metadata = _MutableSessionMetadata(
            command=invocation.display_command,
            cwd=invocation.workspace_path,
            approval_policy=invocation.approval_policy,
            sandbox_mode=invocation.sandbox_mode,
        )

        def emit(event: CodexRuntimeEvent) -> None:
            events.append(event)
            if on_event is not None:
                on_event(event)

        try:
            command_argv = self._process_command_argv(invocation)
        except ConfigError as exc:
            error = "failed to launch Codex app-server: {}".format(exc)
            emit(
                CodexRuntimeEvent(
                    type=CodexRuntimeEventType.ERROR,
                    message=error,
                    elapsed_seconds=time.monotonic() - started_at,
                )
            )
            return self._result(
                _TerminalState(CodexRunStatus.FAILED, error=error),
                metadata,
                events,
                started_at,
            )

        try:
            process = self._process_factory(command_argv, invocation.workspace_path)
        except OSError as exc:
            emit(
                CodexRuntimeEvent(
                    type=CodexRuntimeEventType.ERROR,
                    message="failed to launch Codex app-server: {}".format(exc),
                    elapsed_seconds=time.monotonic() - started_at,
                )
            )
            return self._result(
                _TerminalState(
                    CodexRunStatus.FAILED,
                    error="failed to launch Codex app-server: {}".format(exc),
                ),
                metadata,
                events,
                started_at,
            )
        client = _JsonRpcStdioClient(process)
        closed = False

        def finish(state: "_TerminalState") -> CodexRunResult:
            nonlocal closed
            if not closed:
                client.close()
                closed = True
                emit(
                    CodexRuntimeEvent(
                        type=CodexRuntimeEventType.PROCESS_EXITED,
                        payload={"returncode": process.poll()},
                        thread_id=metadata.thread_id,
                        turn_id=metadata.turn_id,
                        elapsed_seconds=time.monotonic() - started_at,
                    )
                )
            return self._result(state, metadata, events, started_at)

        emit(
            CodexRuntimeEvent(
                type=CodexRuntimeEventType.PROCESS_STARTED,
                payload={"command": invocation.display_command},
                elapsed_seconds=0.0,
            )
        )

        try:
            initialize_result = client.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "vera-harness",
                        "version": __version__,
                    },
                    "capabilities": {"experimentalApi": True},
                },
                timeout_seconds=invocation.run_timeout_seconds,
                handle_message=lambda message: self._handle_message(
                    message, client, emit, metadata, started_at
                ),
            )
            metadata.user_agent = _optional_string(initialize_result.get("userAgent"))
            metadata.codex_home = _optional_string(initialize_result.get("codexHome"))
            emit(
                CodexRuntimeEvent(
                    type=CodexRuntimeEventType.INITIALIZED,
                    method="initialize",
                    payload=initialize_result,
                    elapsed_seconds=time.monotonic() - started_at,
                )
            )

            thread_result = client.request(
                "thread/start",
                _thread_start_params(invocation),
                timeout_seconds=invocation.run_timeout_seconds,
                handle_message=lambda message: self._handle_message(
                    message, client, emit, metadata, started_at
                ),
            )
            thread = _mapping(thread_result.get("thread"))
            metadata.thread_id = _optional_string(thread.get("id"))
            metadata.model = _optional_string(thread_result.get("model"))
            metadata.model_provider = _optional_string(thread_result.get("modelProvider"))
            emit(
                CodexRuntimeEvent(
                    type=CodexRuntimeEventType.THREAD_STARTED,
                    method="thread/start",
                    payload=thread_result,
                    thread_id=metadata.thread_id,
                    elapsed_seconds=time.monotonic() - started_at,
                )
            )

            if metadata.thread_id is None:
                raise CodexAppServerError("thread/start response did not include thread.id")

            turn_result = client.request(
                "turn/start",
                _turn_start_params(invocation, metadata.thread_id),
                timeout_seconds=invocation.run_timeout_seconds,
                handle_message=lambda message: self._handle_message(
                    message, client, emit, metadata, started_at
                ),
            )
            turn = _mapping(turn_result.get("turn"))
            metadata.turn_id = _optional_string(turn.get("id"))
            emit(
                CodexRuntimeEvent(
                    type=CodexRuntimeEventType.TURN_STARTED,
                    method="turn/start",
                    payload=turn_result,
                    thread_id=metadata.thread_id,
                    turn_id=metadata.turn_id,
                    elapsed_seconds=time.monotonic() - started_at,
                )
            )

            result = self._wait_for_turn(client, invocation, emit, metadata, started_at)
            return finish(result)
        except _TerminalState as state:
            return finish(state)
        except (CodexAppServerError, _JsonRpcError) as exc:
            emit(
                CodexRuntimeEvent(
                    type=CodexRuntimeEventType.ERROR,
                    message=str(exc),
                    thread_id=metadata.thread_id,
                    turn_id=metadata.turn_id,
                    elapsed_seconds=time.monotonic() - started_at,
                )
            )
            return finish(
                _TerminalState(CodexRunStatus.FAILED, error=str(exc)),
            )
        finally:
            if not closed:
                client.close()

    def _wait_for_turn(
        self,
        client: "_JsonRpcStdioClient",
        invocation: CodexInvocation,
        emit: EventCallback,
        metadata: "_MutableSessionMetadata",
        started_at: float,
    ) -> "_TerminalState":
        turn_deadline = time.monotonic() + invocation.turn_timeout_seconds
        run_deadline = started_at + invocation.run_timeout_seconds
        while True:
            now = time.monotonic()
            remaining = min(turn_deadline, run_deadline) - now
            if remaining <= 0:
                emit(
                    CodexRuntimeEvent(
                        type=CodexRuntimeEventType.TIMED_OUT,
                        message="Codex turn timed out",
                        thread_id=metadata.thread_id,
                        turn_id=metadata.turn_id,
                        elapsed_seconds=now - started_at,
                    )
                )
                return _TerminalState(CodexRunStatus.TIMED_OUT, error="Codex turn timed out")

            try:
                message = client.next_message(timeout_seconds=remaining)
            except _JsonRpcTimeout:
                emit(
                    CodexRuntimeEvent(
                        type=CodexRuntimeEventType.TIMED_OUT,
                        message="Codex turn timed out",
                        thread_id=metadata.thread_id,
                        turn_id=metadata.turn_id,
                        elapsed_seconds=time.monotonic() - started_at,
                    )
                )
                return _TerminalState(CodexRunStatus.TIMED_OUT, error="Codex turn timed out")

            self._handle_message(message, client, emit, metadata, started_at)

    def _handle_message(
        self,
        message: Mapping[str, Any],
        client: "_JsonRpcStdioClient",
        emit: EventCallback,
        metadata: "_MutableSessionMetadata",
        started_at: float,
    ) -> None:
        method = _optional_string(message.get("method"))
        params = _mapping(message.get("params"))
        request_id = message.get("id")
        thread_id = _optional_string(params.get("threadId")) or metadata.thread_id
        turn_id = _optional_string(params.get("turnId")) or metadata.turn_id

        if method in _APPROVAL_REQUEST_METHODS:
            emit(
                CodexRuntimeEvent(
                    type=CodexRuntimeEventType.APPROVAL_REQUIRED,
                    method=method,
                    payload=params,
                    thread_id=thread_id,
                    turn_id=turn_id,
                    elapsed_seconds=time.monotonic() - started_at,
                )
            )
            decision = self._config.codex_approval_decision
            if decision is None or not _can_auto_answer_approval(method):
                raise _TerminalState(
                    CodexRunStatus.APPROVAL_REQUIRED,
                    error="approval required: {}".format(method),
                )
            client.respond(request_id, {"decision": decision})
            emit(
                CodexRuntimeEvent(
                    type=CodexRuntimeEventType.AUTO_RESPONSE_SENT,
                    method=method,
                    payload={"decision": decision},
                    thread_id=thread_id,
                    turn_id=turn_id,
                    elapsed_seconds=time.monotonic() - started_at,
                )
            )
            return

        if method == "item/tool/requestUserInput":
            emit(
                CodexRuntimeEvent(
                    type=CodexRuntimeEventType.INPUT_REQUIRED,
                    method=method,
                    payload=params,
                    thread_id=thread_id,
                    turn_id=turn_id,
                    elapsed_seconds=time.monotonic() - started_at,
                )
            )
            response_text = self._config.codex_auto_input_response
            if response_text is None:
                raise _TerminalState(
                    CodexRunStatus.INPUT_REQUIRED,
                    error="input required: {}".format(method),
                )
            client.respond(request_id, _auto_input_response(params, response_text))
            emit(
                CodexRuntimeEvent(
                    type=CodexRuntimeEventType.AUTO_RESPONSE_SENT,
                    method=method,
                    payload={"response": response_text},
                    thread_id=thread_id,
                    turn_id=turn_id,
                    elapsed_seconds=time.monotonic() - started_at,
                )
            )
            return

        if method == "turn/completed":
            turn = _mapping(params.get("turn"))
            terminal = _turn_terminal_state(turn)
            event_type = {
                CodexRunStatus.COMPLETED: CodexRuntimeEventType.TURN_COMPLETED,
                CodexRunStatus.CANCELLED: CodexRuntimeEventType.TURN_CANCELLED,
            }.get(terminal.status, CodexRuntimeEventType.TURN_FAILED)
            emit(
                CodexRuntimeEvent(
                    type=event_type,
                    method=method,
                    payload=params,
                    thread_id=thread_id,
                    turn_id=_optional_string(turn.get("id")) or turn_id,
                    elapsed_seconds=time.monotonic() - started_at,
                )
            )
            raise terminal

        if method == "error":
            emit(
                CodexRuntimeEvent(
                    type=CodexRuntimeEventType.ERROR,
                    method=method,
                    payload=params,
                    message=_error_message(params),
                    thread_id=thread_id,
                    turn_id=turn_id,
                    elapsed_seconds=time.monotonic() - started_at,
                )
            )
            raise _TerminalState(CodexRunStatus.FAILED, error=_error_message(params))

        emit(
            CodexRuntimeEvent(
                type=CodexRuntimeEventType.NOTIFICATION,
                method=method,
                payload=dict(message),
                thread_id=thread_id,
                turn_id=turn_id,
                elapsed_seconds=time.monotonic() - started_at,
            )
        )

    def _result(
        self,
        state: "_TerminalState",
        metadata: "_MutableSessionMetadata",
        events: List[CodexRuntimeEvent],
        started_at: float,
    ) -> CodexRunResult:
        return CodexRunResult(
            status=state.status,
            metadata=metadata.freeze(),
            events=tuple(events),
            error=state.error,
            elapsed_seconds=time.monotonic() - started_at,
            assistant_response=extract_assistant_response(events),
        )

    def _process_command_argv(self, invocation: CodexInvocation) -> Tuple[str, ...]:
        if not self._resolve_process_command:
            return invocation.command.argv
        return invocation.command.resolve_executable("VERA_CODEX_APP_SERVER_COMMAND").argv


class CodexAppServerSession:
    """Long-lived Codex app-server session that reuses one process and thread."""

    def __init__(
        self,
        config: HarnessConfig,
        process_factory: Optional[ProcessFactory] = None,
        resume_thread_id: Optional[str] = None,
    ) -> None:
        self._config = config
        self._resolve_process_command = process_factory is None
        self._process_factory = process_factory or _default_process_factory
        self._resume_thread_id = resume_thread_id
        self._process: Optional[subprocess.Popen] = None
        self._client: Optional[_JsonRpcStdioClient] = None
        self._metadata: Optional[_MutableSessionMetadata] = None
        self._pending_request: Optional[CodexPendingRequest] = None
        self._closed = False

    @property
    def thread_id(self) -> Optional[str]:
        if self._metadata is None:
            return self._resume_thread_id
        return self._metadata.thread_id

    @property
    def turn_id(self) -> Optional[str]:
        if self._metadata is None:
            return None
        return self._metadata.turn_id

    @property
    def pending_request(self) -> Optional[CodexPendingRequest]:
        return self._pending_request

    def run_turn(
        self,
        invocation: CodexInvocation,
        on_event: Optional[EventCallback] = None,
    ) -> CodexRunResult:
        """Start or continue one turn in the persistent app-server session."""

        started_at = time.monotonic()
        events: List[CodexRuntimeEvent] = []

        def emit(event: CodexRuntimeEvent) -> None:
            events.append(event)
            if on_event is not None:
                on_event(event)

        try:
            invocation = dataclass_replace(
                invocation,
                workspace_path=_validated_workspace_path(
                    self._config.workspace_root,
                    invocation.workspace_path,
                ),
            )
            if not invocation.workspace_path.is_dir():
                raise CodexAppServerError(
                    "workspace does not exist: {}".format(invocation.workspace_path)
                )
            if self._client is None or self._metadata is None:
                self._start(invocation, emit, started_at)
            else:
                _validated_workspace_path(self._config.workspace_root, invocation.workspace_path)
                if self._metadata.cwd != invocation.workspace_path:
                    raise CodexAppServerError(
                        "persistent Codex session cwd mismatch: {} != {}".format(
                            self._metadata.cwd,
                            invocation.workspace_path,
                        )
                    )

            assert self._client is not None
            assert self._metadata is not None
            if self._pending_request is not None:
                self._answer_pending_request(invocation.prompt, self._client, emit, started_at)
            else:
                turn_result = self._client.request(
                    "turn/start",
                    _turn_start_params(invocation, self._metadata.thread_id or ""),
                    timeout_seconds=invocation.run_timeout_seconds,
                    handle_message=lambda message: self._handle_message(
                        message, self._client, emit, self._metadata, started_at
                    ),
                )
                turn = _mapping(turn_result.get("turn"))
                self._metadata.turn_id = _optional_string(turn.get("id"))
                emit(
                    CodexRuntimeEvent(
                        type=CodexRuntimeEventType.TURN_STARTED,
                        method="turn/start",
                        payload=turn_result,
                        thread_id=self._metadata.thread_id,
                        turn_id=self._metadata.turn_id,
                        elapsed_seconds=time.monotonic() - started_at,
                    )
                )

            terminal = self._wait_for_turn(
                self._client,
                invocation,
                emit,
                self._metadata,
                started_at,
            )
            return self._result(terminal, self._metadata, events, started_at)
        except _TerminalState as state:
            if state.status in {CodexRunStatus.FAILED, CodexRunStatus.TIMED_OUT, CodexRunStatus.CANCELLED}:
                self.close()
            metadata = self._metadata or _MutableSessionMetadata(
                command=invocation.display_command,
                cwd=invocation.workspace_path,
                approval_policy=invocation.approval_policy,
                sandbox_mode=invocation.sandbox_mode,
            )
            return self._result(state, metadata, events, started_at)
        except (CodexAppServerError, _JsonRpcError, ConfigError, OSError) as exc:
            error = "failed to launch Codex app-server: {}".format(exc) if isinstance(exc, (ConfigError, OSError)) else str(exc)
            metadata = self._metadata or _MutableSessionMetadata(
                command=invocation.display_command,
                cwd=invocation.workspace_path,
                approval_policy=invocation.approval_policy,
                sandbox_mode=invocation.sandbox_mode,
            )
            emit(
                CodexRuntimeEvent(
                    type=CodexRuntimeEventType.ERROR,
                    message=error,
                    thread_id=metadata.thread_id,
                    turn_id=metadata.turn_id,
                    elapsed_seconds=time.monotonic() - started_at,
                )
            )
            self.close()
            return self._result(
                _TerminalState(CodexRunStatus.FAILED, error=error),
                metadata,
                events,
                started_at,
            )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._client is not None:
            self._client.close()

    def _start(
        self,
        invocation: CodexInvocation,
        emit: EventCallback,
        started_at: float,
    ) -> None:
        command_argv = self._process_command_argv(invocation)
        process = self._process_factory(command_argv, invocation.workspace_path)
        self._process = process
        client = _JsonRpcStdioClient(process)
        self._client = client
        metadata = _MutableSessionMetadata(
            command=invocation.display_command,
            cwd=invocation.workspace_path,
            approval_policy=invocation.approval_policy,
            sandbox_mode=invocation.sandbox_mode,
        )
        self._metadata = metadata
        emit(
            CodexRuntimeEvent(
                type=CodexRuntimeEventType.PROCESS_STARTED,
                payload={"command": invocation.display_command},
                elapsed_seconds=0.0,
            )
        )

        initialize_result = client.request(
            "initialize",
            {
                "clientInfo": {"name": "vera-harness", "version": __version__},
                "capabilities": {"experimentalApi": True},
            },
            timeout_seconds=invocation.run_timeout_seconds,
            handle_message=lambda message: self._handle_message(
                message, client, emit, metadata, started_at
            ),
        )
        metadata.user_agent = _optional_string(initialize_result.get("userAgent"))
        metadata.codex_home = _optional_string(initialize_result.get("codexHome"))
        emit(
            CodexRuntimeEvent(
                type=CodexRuntimeEventType.INITIALIZED,
                method="initialize",
                payload=initialize_result,
                elapsed_seconds=time.monotonic() - started_at,
            )
        )

        if self._resume_thread_id:
            try:
                thread_result = client.request(
                    "thread/resume",
                    _thread_resume_params(invocation, self._resume_thread_id),
                    timeout_seconds=invocation.run_timeout_seconds,
                    handle_message=lambda message: self._handle_message(
                        message, client, emit, metadata, started_at
                    ),
                )
                self._apply_thread_result(thread_result, metadata, "thread/resume")
                emit(
                    CodexRuntimeEvent(
                        type=CodexRuntimeEventType.THREAD_STARTED,
                        method="thread/resume",
                        payload=thread_result,
                        thread_id=metadata.thread_id,
                        elapsed_seconds=time.monotonic() - started_at,
                    )
                )
                return
            except _JsonRpcError as exc:
                emit(
                    CodexRuntimeEvent(
                        type=CodexRuntimeEventType.ERROR,
                        method="thread/resume",
                        message="thread/resume failed; starting a new thread: {}".format(exc),
                        thread_id=self._resume_thread_id,
                        elapsed_seconds=time.monotonic() - started_at,
                    )
                )

        thread_result = client.request(
            "thread/start",
            _thread_start_params(invocation),
            timeout_seconds=invocation.run_timeout_seconds,
            handle_message=lambda message: self._handle_message(
                message, client, emit, metadata, started_at
            ),
        )
        self._apply_thread_result(thread_result, metadata, "thread/start")
        emit(
            CodexRuntimeEvent(
                type=CodexRuntimeEventType.THREAD_STARTED,
                method="thread/start",
                payload=thread_result,
                thread_id=metadata.thread_id,
                elapsed_seconds=time.monotonic() - started_at,
            )
        )

    def _apply_thread_result(
        self,
        thread_result: Mapping[str, Any],
        metadata: "_MutableSessionMetadata",
        method: str,
    ) -> None:
        thread = _mapping(thread_result.get("thread"))
        metadata.thread_id = _optional_string(thread.get("id"))
        metadata.model = _optional_string(thread_result.get("model"))
        metadata.model_provider = _optional_string(thread_result.get("modelProvider"))
        if metadata.thread_id is None:
            raise CodexAppServerError("{} response did not include thread.id".format(method))

    def _wait_for_turn(
        self,
        client: "_JsonRpcStdioClient",
        invocation: CodexInvocation,
        emit: EventCallback,
        metadata: "_MutableSessionMetadata",
        started_at: float,
    ) -> "_TerminalState":
        turn_deadline = time.monotonic() + invocation.turn_timeout_seconds
        run_deadline = started_at + invocation.run_timeout_seconds
        while True:
            now = time.monotonic()
            remaining = min(turn_deadline, run_deadline) - now
            if remaining <= 0:
                emit(
                    CodexRuntimeEvent(
                        type=CodexRuntimeEventType.TIMED_OUT,
                        message="Codex turn timed out",
                        thread_id=metadata.thread_id,
                        turn_id=metadata.turn_id,
                        elapsed_seconds=now - started_at,
                    )
                )
                return _TerminalState(CodexRunStatus.TIMED_OUT, error="Codex turn timed out")
            try:
                message = client.next_message(timeout_seconds=remaining)
            except _JsonRpcTimeout:
                emit(
                    CodexRuntimeEvent(
                        type=CodexRuntimeEventType.TIMED_OUT,
                        message="Codex turn timed out",
                        thread_id=metadata.thread_id,
                        turn_id=metadata.turn_id,
                        elapsed_seconds=time.monotonic() - started_at,
                    )
                )
                return _TerminalState(CodexRunStatus.TIMED_OUT, error="Codex turn timed out")
            self._handle_message(message, client, emit, metadata, started_at)

    def _handle_message(
        self,
        message: Mapping[str, Any],
        client: "_JsonRpcStdioClient",
        emit: EventCallback,
        metadata: "_MutableSessionMetadata",
        started_at: float,
    ) -> None:
        method = _optional_string(message.get("method"))
        params = _mapping(message.get("params"))
        request_id = message.get("id")
        thread_id = _optional_string(params.get("threadId")) or metadata.thread_id
        turn_id = _optional_string(params.get("turnId")) or metadata.turn_id

        if method in _APPROVAL_REQUEST_METHODS:
            emit(
                CodexRuntimeEvent(
                    type=CodexRuntimeEventType.APPROVAL_REQUIRED,
                    method=method,
                    payload=params,
                    thread_id=thread_id,
                    turn_id=turn_id,
                    elapsed_seconds=time.monotonic() - started_at,
                )
            )
            decision = self._config.codex_approval_decision
            if decision is None or not _can_auto_answer_approval(method):
                prompt = _approval_prompt(method, params)
                self._pending_request = CodexPendingRequest(
                    status=CodexRunStatus.APPROVAL_REQUIRED,
                    method=method,
                    request_id=request_id,
                    prompt=prompt,
                    payload=params,
                    thread_id=thread_id,
                    turn_id=turn_id,
                )
                raise _TerminalState(CodexRunStatus.APPROVAL_REQUIRED, error=prompt)
            client.respond(request_id, {"decision": decision})
            emit(
                CodexRuntimeEvent(
                    type=CodexRuntimeEventType.AUTO_RESPONSE_SENT,
                    method=method,
                    payload={"decision": decision},
                    thread_id=thread_id,
                    turn_id=turn_id,
                    elapsed_seconds=time.monotonic() - started_at,
                )
            )
            return

        if method == "item/tool/requestUserInput":
            emit(
                CodexRuntimeEvent(
                    type=CodexRuntimeEventType.INPUT_REQUIRED,
                    method=method,
                    payload=params,
                    thread_id=thread_id,
                    turn_id=turn_id,
                    elapsed_seconds=time.monotonic() - started_at,
                )
            )
            response_text = self._config.codex_auto_input_response
            if response_text is None:
                prompt = _input_prompt(params)
                self._pending_request = CodexPendingRequest(
                    status=CodexRunStatus.INPUT_REQUIRED,
                    method=method,
                    request_id=request_id,
                    prompt=prompt,
                    payload=params,
                    thread_id=thread_id,
                    turn_id=turn_id,
                )
                raise _TerminalState(CodexRunStatus.INPUT_REQUIRED, error=prompt)
            client.respond(request_id, _auto_input_response(params, response_text))
            emit(
                CodexRuntimeEvent(
                    type=CodexRuntimeEventType.AUTO_RESPONSE_SENT,
                    method=method,
                    payload={"response": response_text},
                    thread_id=thread_id,
                    turn_id=turn_id,
                    elapsed_seconds=time.monotonic() - started_at,
                )
            )
            return

        if method == "turn/completed":
            turn = _mapping(params.get("turn"))
            terminal = _turn_terminal_state(turn)
            event_type = {
                CodexRunStatus.COMPLETED: CodexRuntimeEventType.TURN_COMPLETED,
                CodexRunStatus.CANCELLED: CodexRuntimeEventType.TURN_CANCELLED,
            }.get(terminal.status, CodexRuntimeEventType.TURN_FAILED)
            emit(
                CodexRuntimeEvent(
                    type=event_type,
                    method=method,
                    payload=params,
                    thread_id=thread_id,
                    turn_id=_optional_string(turn.get("id")) or turn_id,
                    elapsed_seconds=time.monotonic() - started_at,
                )
            )
            raise terminal

        if method == "error":
            emit(
                CodexRuntimeEvent(
                    type=CodexRuntimeEventType.ERROR,
                    method=method,
                    payload=params,
                    message=_error_message(params),
                    thread_id=thread_id,
                    turn_id=turn_id,
                    elapsed_seconds=time.monotonic() - started_at,
                )
            )
            raise _TerminalState(CodexRunStatus.FAILED, error=_error_message(params))

        emit(
            CodexRuntimeEvent(
                type=CodexRuntimeEventType.NOTIFICATION,
                method=method,
                payload=dict(message),
                thread_id=thread_id,
                turn_id=turn_id,
                elapsed_seconds=time.monotonic() - started_at,
            )
        )

    def _answer_pending_request(
        self,
        response_text: str,
        client: "_JsonRpcStdioClient",
        emit: EventCallback,
        started_at: float,
    ) -> None:
        pending = self._pending_request
        if pending is None:
            return
        if pending.status == CodexRunStatus.APPROVAL_REQUIRED:
            result = {"decision": _approval_decision_from_text(response_text)}
        else:
            result = _auto_input_response(pending.payload, response_text)
        client.respond(pending.request_id, result)
        emit(
            CodexRuntimeEvent(
                type=CodexRuntimeEventType.AUTO_RESPONSE_SENT,
                method=pending.method,
                payload=result,
                thread_id=pending.thread_id,
                turn_id=pending.turn_id,
                elapsed_seconds=time.monotonic() - started_at,
            )
        )
        self._pending_request = None

    def _result(
        self,
        state: "_TerminalState",
        metadata: "_MutableSessionMetadata",
        events: List[CodexRuntimeEvent],
        started_at: float,
    ) -> CodexRunResult:
        pending = self._pending_request
        return CodexRunResult(
            status=state.status,
            metadata=metadata.freeze(),
            events=tuple(events),
            error=state.error,
            elapsed_seconds=time.monotonic() - started_at,
            assistant_response=extract_assistant_response(events),
            pending_prompt=pending.prompt if pending is not None else None,
        )

    def _process_command_argv(self, invocation: CodexInvocation) -> Tuple[str, ...]:
        if not self._resolve_process_command:
            return invocation.command.argv
        return invocation.command.resolve_executable("VERA_CODEX_APP_SERVER_COMMAND").argv


@dataclass
class _MutableSessionMetadata:
    command: str
    cwd: Path
    approval_policy: str
    sandbox_mode: str
    user_agent: Optional[str] = None
    codex_home: Optional[str] = None
    thread_id: Optional[str] = None
    turn_id: Optional[str] = None
    model: Optional[str] = None
    model_provider: Optional[str] = None

    def freeze(self) -> CodexSessionMetadata:
        return CodexSessionMetadata(
            command=self.command,
            cwd=self.cwd,
            approval_policy=self.approval_policy,
            sandbox_mode=self.sandbox_mode,
            user_agent=self.user_agent,
            codex_home=self.codex_home,
            thread_id=self.thread_id,
            turn_id=self.turn_id,
            model=self.model,
            model_provider=self.model_provider,
        )


class _TerminalState(Exception):
    def __init__(self, status: CodexRunStatus, error: Optional[str] = None) -> None:
        super().__init__(error or status.value)
        self.status = status
        self.error = error


class _JsonRpcError(RuntimeError):
    pass


class _JsonRpcTimeout(_JsonRpcError):
    pass


class _JsonRpcEof(_JsonRpcError):
    pass


class _JsonRpcStdioClient:
    def __init__(self, process: subprocess.Popen) -> None:
        self._process = process
        self._messages: "queue.Queue[Any]" = queue.Queue()
        self._next_id = 1
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()

    def request(
        self,
        method: str,
        params: Mapping[str, Any],
        timeout_seconds: float,
        handle_message: Callable[[Mapping[str, Any]], None],
    ) -> Dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)})
        deadline = time.monotonic() + timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _JsonRpcTimeout("{} timed out".format(method))
            message = self.next_message(timeout_seconds=remaining)
            if message.get("id") == request_id and "method" not in message:
                if "error" in message:
                    raise _JsonRpcError("{} failed: {}".format(method, _error_message(_mapping(message.get("error")))))
                return _mapping(message.get("result"))
            handle_message(message)

    def respond(self, request_id: Any, result: Mapping[str, Any]) -> None:
        if request_id is None:
            raise _JsonRpcError("server request did not include an id")
        self._write({"jsonrpc": "2.0", "id": request_id, "result": dict(result)})

    def next_message(self, timeout_seconds: float) -> Mapping[str, Any]:
        try:
            message = self._messages.get(timeout=timeout_seconds)
        except queue.Empty:
            raise _JsonRpcTimeout("timed out waiting for app-server message")
        if isinstance(message, Exception):
            raise message
        if message is _EOF:
            raise _JsonRpcEof("app-server stdout closed")
        return message

    def close(self) -> None:
        if self._process.poll() is not None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=2)
        except Exception:
            kill = getattr(self._process, "kill", None)
            if kill is not None:
                kill()
            try:
                self._process.wait(timeout=2)
            except Exception:
                pass

    def _write(self, message: Mapping[str, Any]) -> None:
        if self._process.stdin is None:
            raise _JsonRpcError("app-server stdin is unavailable")
        line = json.dumps(message, separators=(",", ":"))
        self._process.stdin.write(line + "\n")
        self._process.stdin.flush()

    def _read_stdout(self) -> None:
        try:
            stdout = self._process.stdout
            if stdout is None:
                return
            while True:
                line = stdout.readline()
                if line == "":
                    return
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    message = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    self._messages.put(_JsonRpcError("invalid JSON-RPC line: {}".format(exc)))
                    continue
                if not isinstance(message, dict):
                    self._messages.put(_JsonRpcError("JSON-RPC message is not an object"))
                    continue
                self._messages.put(message)
        except Exception as exc:
            self._messages.put(_JsonRpcError("failed reading app-server stdout: {}".format(exc)))
        finally:
            self._messages.put(_EOF)


_EOF = object()

_APPROVAL_REQUEST_METHODS = {
    "item/commandExecution/requestApproval",
    "item/fileChange/requestApproval",
    "item/permissions/requestApproval",
    "mcpServer/elicitation/request",
    "applyPatchApproval",
    "execCommandApproval",
}


def _default_process_factory(command: Sequence[str], cwd: Path) -> subprocess.Popen:
    return subprocess.Popen(
        tuple(command),
        cwd=str(cwd),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )


def _thread_start_params(invocation: CodexInvocation) -> Dict[str, Any]:
    return {
        "cwd": str(invocation.workspace_path),
        "approvalPolicy": invocation.approval_policy,
        "sandbox": invocation.sandbox_mode,
        "ephemeral": True,
    }


def _thread_resume_params(invocation: CodexInvocation, thread_id: str) -> Dict[str, Any]:
    return {
        "threadId": thread_id,
        "cwd": str(invocation.workspace_path),
        "approvalPolicy": invocation.approval_policy,
        "sandbox": invocation.sandbox_mode,
    }


def _turn_start_params(invocation: CodexInvocation, thread_id: str) -> Dict[str, Any]:
    return {
        "threadId": thread_id,
        "cwd": str(invocation.workspace_path),
        "approvalPolicy": invocation.approval_policy,
        "sandboxPolicy": _sandbox_policy(invocation.sandbox_mode, invocation.workspace_path),
        "input": [{"type": "text", "text": invocation.prompt}],
    }


def _sandbox_policy(sandbox_mode: str, workspace_path: Path) -> Dict[str, Any]:
    if sandbox_mode == "danger-full-access":
        return {"type": "dangerFullAccess"}
    if sandbox_mode == "workspace-write":
        return {
            "type": "workspaceWrite",
            "networkAccess": False,
            "writableRoots": [str(workspace_path)],
        }
    return {"type": "readOnly", "networkAccess": False}


def _validated_workspace_path(root: Path, workspace_path: Path) -> Path:
    resolved_root = root.expanduser().resolve()
    resolved_workspace = workspace_path.expanduser().resolve()
    try:
        resolved_workspace.relative_to(resolved_root)
    except ValueError:
        raise CodexAppServerError(
            "workspace cwd escapes configured root: {}".format(resolved_workspace)
        )
    return resolved_workspace


def _turn_terminal_state(turn: Mapping[str, Any]) -> _TerminalState:
    status = _optional_string(turn.get("status"))
    if status == "completed":
        return _TerminalState(CodexRunStatus.COMPLETED)
    if status == "interrupted":
        return _TerminalState(CodexRunStatus.CANCELLED, error="Codex turn was interrupted")
    return _TerminalState(CodexRunStatus.FAILED, error=_error_message(_mapping(turn.get("error"))))


def _can_auto_answer_approval(method: str) -> bool:
    return method in {
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
        "applyPatchApproval",
        "execCommandApproval",
    }


def _auto_input_response(params: Mapping[str, Any], response_text: str) -> Dict[str, Any]:
    answers = {}
    questions = params.get("questions")
    if isinstance(questions, list):
        for question in questions:
            if isinstance(question, dict) and isinstance(question.get("id"), str):
                answers[question["id"]] = {"answers": [response_text]}
    return {"answers": answers}


def extract_assistant_response(events: Sequence[CodexRuntimeEvent]) -> Optional[str]:
    """Return the last user-facing assistant text found in app-server events."""

    event_list = tuple(events)
    for event in reversed(event_list):
        text = _completed_agent_message_text(event)
        if text:
            return text

    for event in reversed(event_list):
        text = _assistant_text_from_value(event.payload)
        if text:
            return text
        if event.message:
            text = _clean_assistant_text(event.message)
            if text and "VERA_TASK_STATUS:" not in text:
                return text
    return _assistant_text_from_agent_message_deltas(event_list)


def _completed_agent_message_text(event: CodexRuntimeEvent) -> Optional[str]:
    method = _event_method(event)
    if method not in {"item/completed", "turn/completed"}:
        return None

    params = _event_params(event)
    if method == "item/completed":
        return _agent_message_item_text(_mapping(params.get("item")))

    turn = _mapping(params.get("turn"))
    items = turn.get("items")
    if not isinstance(items, list):
        return None
    for item in reversed(items):
        text = _agent_message_item_text(_mapping(item))
        if text:
            return text
    return None


def _assistant_text_from_agent_message_deltas(events: Sequence[CodexRuntimeEvent]) -> Optional[str]:
    chunks_by_item: Dict[Tuple[str, str], List[str]] = {}
    latest_key: Optional[Tuple[str, str]] = None
    for event in events:
        if _event_method(event) != "item/agentMessage/delta":
            continue
        params = _event_params(event)
        delta = params.get("delta")
        if isinstance(delta, str):
            if delta == "":
                continue
            text = delta
        else:
            text = _assistant_text_from_value(delta, assistant_context=True)
            if not text:
                continue
        key = (
            _optional_string(params.get("turnId")) or event.turn_id or "",
            _optional_string(params.get("itemId")) or "",
        )
        chunks_by_item.setdefault(key, []).append(text)
        latest_key = key
    if latest_key is None:
        return None
    return _clean_assistant_text("".join(chunks_by_item[latest_key]))


def _agent_message_item_text(item: Mapping[str, Any]) -> Optional[str]:
    if item.get("type") != "agentMessage":
        return None
    text = item.get("text")
    if isinstance(text, str):
        return _clean_assistant_text(text)
    return _assistant_text_from_value(item, assistant_context=True)


def _event_method(event: CodexRuntimeEvent) -> Optional[str]:
    if event.method:
        return event.method
    return _optional_string(_mapping(event.payload).get("method"))


def _event_params(event: CodexRuntimeEvent) -> Mapping[str, Any]:
    payload = _mapping(event.payload)
    params = payload.get("params")
    if isinstance(params, Mapping):
        return params
    return payload


def _assistant_text_from_value(value: Any, assistant_context: bool = False) -> Optional[str]:
    if isinstance(value, str):
        return _clean_assistant_text(value) if assistant_context else None
    if isinstance(value, list):
        texts = [
            text
            for item in value
            for text in (_assistant_text_from_value(item, assistant_context=assistant_context),)
            if text
        ]
        return _join_texts(texts)
    if not isinstance(value, Mapping):
        return None

    role = value.get("role")
    value_type = value.get("type")
    is_assistant = assistant_context or role == "assistant" or value_type in {
        "assistant",
        "assistant_message",
        "assistantMessage",
        "agentMessage",
        "message/assistant",
    }
    if value_type in {"output_text", "assistant_text"} or (
        value_type == "text" and is_assistant
    ):
        text = value.get("text")
        if isinstance(text, str):
            return _clean_assistant_text(text)

    if is_assistant:
        direct_texts = []
        for key in ("text", "content", "message", "markdown"):
            text = _assistant_text_from_value(value.get(key), assistant_context=True)
            if text:
                direct_texts.append(text)
        joined = _join_texts(direct_texts)
        if joined:
            return joined

    for key in ("params", "item", "message", "delta", "content", "items", "turn", "output"):
        text = _assistant_text_from_value(value.get(key), assistant_context=is_assistant)
        if text:
            return text
    return None


def _join_texts(texts: Sequence[str]) -> Optional[str]:
    compacted = [text for text in (_clean_assistant_text(item) for item in texts) if text]
    if not compacted:
        return None
    return "\n".join(compacted)


def _clean_assistant_text(text: str) -> Optional[str]:
    compact = text.strip()
    return compact or None


def _approval_prompt(method: str, params: Mapping[str, Any]) -> str:
    details = []
    command = params.get("command")
    if isinstance(command, str) and command:
        details.append("command `{}`".format(command))
    files = params.get("files")
    if isinstance(files, list) and files:
        details.append("files {}".format(", ".join(str(item) for item in files[:5])))
    suffix = " ({})".format("; ".join(details)) if details else ""
    return "Codex requests approval for `{}`{}. Reply `approve`, `deny`, or `cancel`.".format(method, suffix)


def _input_prompt(params: Mapping[str, Any]) -> str:
    questions = params.get("questions")
    if isinstance(questions, list) and questions:
        prompts = []
        for question in questions:
            if not isinstance(question, Mapping):
                continue
            text = question.get("question")
            header = question.get("header")
            if isinstance(text, str) and text:
                if isinstance(header, str) and header:
                    prompts.append("{}: {}".format(header, text))
                else:
                    prompts.append(text)
        if prompts:
            return "Codex needs input: {}".format(" ".join(prompts))
    return "Codex needs input before it can continue. Reply with the answer to send back to Codex."


def _approval_decision_from_text(text: str) -> str:
    normalized = text.strip().lower()
    if normalized in {"approve", "approved", "accept", "yes", "y"}:
        return "accept"
    if normalized in {"approve session", "accept session", "acceptforsession", "accept for session"}:
        return "acceptForSession"
    if normalized in {"cancel", "stop"}:
        return "cancel"
    return "decline"


def _error_message(payload: Mapping[str, Any]) -> str:
    message = payload.get("message")
    if isinstance(message, str) and message:
        return message
    code = payload.get("code")
    if code is not None:
        return "Codex app-server error {}".format(code)
    if payload:
        return json.dumps(dict(payload), sort_keys=True)
    return "Codex app-server turn failed"


def _mapping(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _optional_string(value: Any) -> Optional[str]:
    if isinstance(value, str) and value:
        return value
    return None
