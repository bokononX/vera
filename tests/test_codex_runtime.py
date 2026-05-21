import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from vera_harness.codex import (
    CodexAppServerError,
    CodexAppServerSession,
    CodexAppServerRuntime,
    CodexRunStatus,
    CodexRuntimeEvent,
    CodexRuntimeEventType,
    CodexRuntimePlanner,
    extract_assistant_response,
)
from vera_harness.config import HarnessConfig
from vera_harness.models import Workspace


class FakeStdin:
    def __init__(self):
        self.lines = []

    def write(self, value):
        self.lines.append(value)

    def flush(self):
        pass


class ScriptedStdout:
    def __init__(self, messages):
        self._lines = [json.dumps(message) + "\n" for message in messages]

    def readline(self):
        if not self._lines:
            return ""
        return self._lines.pop(0)


class BlockingStdout:
    def __init__(self, messages=None):
        self._lines = [json.dumps(message) + "\n" for message in (messages or [])]
        self._closed = threading.Event()

    def readline(self):
        if self._lines:
            return self._lines.pop(0)
        self._closed.wait(10)
        return ""

    def close(self):
        self._closed.set()


class FakeProcess:
    def __init__(self, stdout):
        self.stdin = FakeStdin()
        self.stdout = stdout
        self.returncode = None
        self.command = None
        self.cwd = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15
        close = getattr(self.stdout, "close", None)
        if close is not None:
            close()

    def kill(self):
        self.returncode = -9
        close = getattr(self.stdout, "close", None)
        if close is not None:
            close()

    def wait(self, timeout=None):
        started_at = time.monotonic()
        while self.returncode is None:
            if timeout is not None and time.monotonic() - started_at > timeout:
                raise TimeoutError("fake process wait timed out")
            time.sleep(0.01)
        return self.returncode


class ProcessFactory:
    def __init__(self, messages=None, stdout=None):
        self.messages = messages or []
        self.stdout = stdout
        self.processes = []

    def __call__(self, command, cwd):
        stdout = self.stdout if self.stdout is not None else ScriptedStdout(self.messages)
        process = FakeProcess(stdout)
        process.command = tuple(command)
        process.cwd = cwd
        self.processes.append(process)
        return process


class CodexAppServerRuntimeTests(unittest.TestCase):
    def test_launch_failure_returns_failed_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            def failing_factory(command, cwd):
                raise FileNotFoundError("missing codex")

            runtime = CodexAppServerRuntime(_config(temp_dir), process_factory=failing_factory)

            result = runtime.run_turn(_invocation(temp_dir, "Launch."))

            self.assertEqual(result.status, CodexRunStatus.FAILED)
            self.assertIn("failed to launch Codex app-server", result.error)

    def test_default_runtime_reports_missing_executable_without_popen(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = CodexAppServerRuntime(
                _config(
                    temp_dir,
                    {"VERA_CODEX_APP_SERVER_COMMAND": "definitely-missing-codex app-server"},
                )
            )

            result = runtime.run_turn(
                _invocation(
                    temp_dir,
                    "Launch.",
                    {"VERA_CODEX_APP_SERVER_COMMAND": "definitely-missing-codex app-server"},
                )
            )

            self.assertEqual(result.status, CodexRunStatus.FAILED)
            self.assertIn("failed to launch Codex app-server", result.error)
            self.assertIn("VERA_CODEX_APP_SERVER_COMMAND executable not found on PATH", result.error)

    def test_planner_rejects_workspace_outside_configured_root(self):
        with tempfile.TemporaryDirectory() as root_dir, tempfile.TemporaryDirectory() as outside_dir:
            config = _config(root_dir)
            workspace = Workspace(
                workspace_id="escape",
                task_id="escape",
                root=Path(root_dir),
                path=Path(outside_dir),
                created=True,
            )

            with self.assertRaises(CodexAppServerError) as raised:
                CodexRuntimePlanner(config).plan(workspace, "Do work.")

            self.assertIn("workspace cwd escapes configured root", str(raised.exception))

    def test_run_turn_completes_and_sends_configured_json_rpc_requests(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            factory = ProcessFactory(_successful_messages(workspace))
            runtime = CodexAppServerRuntime(_config(temp_dir), process_factory=factory)
            invocation = _invocation(temp_dir, "Ship the runtime adapter.")

            result = runtime.run_turn(invocation)

            self.assertEqual(result.status, CodexRunStatus.COMPLETED)
            self.assertEqual(result.metadata.thread_id, "thread-1")
            self.assertEqual(result.metadata.turn_id, "turn-1")
            self.assertEqual(result.metadata.model, "gpt-test")
            self.assertTrue(factory.processes[0].terminated)
            sent = _sent_messages(factory.processes[0])
            self.assertEqual([message["method"] for message in sent[:3]], ["initialize", "thread/start", "turn/start"])
            self.assertEqual(sent[1]["params"]["cwd"], str(workspace.resolve()))
            self.assertEqual(sent[1]["params"]["approvalPolicy"], "on-request")
            self.assertEqual(sent[1]["params"]["sandbox"], "read-only")
            self.assertEqual(sent[2]["params"]["input"], [{"type": "text", "text": "Ship the runtime adapter."}])
            self.assertEqual(sent[2]["params"]["sandboxPolicy"], {"type": "readOnly", "networkAccess": False})

    def test_persistent_session_reuses_thread_and_extracts_assistant_response(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            factory = ProcessFactory(_persistent_success_messages(workspace))
            session = CodexAppServerSession(_config(temp_dir), process_factory=factory)

            first = session.run_turn(_invocation(temp_dir, "hello"))
            second = session.run_turn(_invocation(temp_dir, "follow up"))
            session.close()

            self.assertEqual(first.status, CodexRunStatus.COMPLETED)
            self.assertEqual(first.assistant_response, "Hello from Codex.")
            self.assertEqual(second.status, CodexRunStatus.COMPLETED)
            self.assertEqual(second.assistant_response, "Still the same thread.")
            self.assertEqual(first.metadata.thread_id, "thread-1")
            self.assertEqual(second.metadata.thread_id, "thread-1")
            self.assertTrue(factory.processes[0].terminated)
            sent = _sent_messages(factory.processes[0])
            self.assertEqual(
                [message.get("method") for message in sent],
                ["initialize", "thread/start", "turn/start", "turn/start"],
            )
            self.assertEqual(sent[2]["params"]["threadId"], "thread-1")
            self.assertEqual(sent[3]["params"]["threadId"], "thread-1")
            self.assertEqual(sent[3]["params"]["input"], [{"type": "text", "text": "follow up"}])

    def test_persistent_session_launch_failure_returns_failed_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            def failing_factory(command, cwd):
                raise FileNotFoundError("missing codex")

            session = CodexAppServerSession(_config(temp_dir), process_factory=failing_factory)

            result = session.run_turn(_invocation(temp_dir, "hello"))

            self.assertEqual(result.status, CodexRunStatus.FAILED)
            self.assertIn("failed to launch Codex app-server", result.error)

    def test_persistent_session_resumes_existing_thread_when_available(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            messages = [
                _base_messages(workspace)[0],
                {
                    "id": 2,
                    "result": {
                        "thread": {"id": "thread-existing"},
                        "model": "gpt-test",
                        "modelProvider": "openai",
                    },
                },
                {"id": 3, "result": {"turn": {"id": "turn-1", "status": "inProgress", "items": []}}},
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "thread-existing",
                        "turn": {"id": "turn-1", "status": "completed", "items": []},
                    },
                },
            ]
            factory = ProcessFactory(messages)
            session = CodexAppServerSession(
                _config(temp_dir),
                process_factory=factory,
                resume_thread_id="thread-existing",
            )

            result = session.run_turn(_invocation(temp_dir, "resume"))
            session.close()

            self.assertEqual(result.status, CodexRunStatus.COMPLETED)
            self.assertEqual(result.metadata.thread_id, "thread-existing")
            self.assertEqual(
                [message.get("method") for message in _sent_messages(factory.processes[0])],
                ["initialize", "thread/resume", "turn/start"],
            )

    def test_extract_assistant_response_prefers_turn_items(self):
        event = _event_from_payload(
            {
                "turn": {
                    "items": [
                        {"role": "user", "content": [{"type": "text", "text": "hello"}]},
                        {"role": "assistant", "content": [{"type": "output_text", "text": "Natural response."}]},
                    ]
                }
            }
        )

        self.assertEqual(extract_assistant_response((event,)), "Natural response.")

    def test_run_turn_maps_failed_turn_to_failed_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            messages = _base_messages(Path(temp_dir)) + [
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "thread-1",
                        "turn": {
                            "id": "turn-1",
                            "status": "failed",
                            "items": [],
                            "error": {"message": "model failed"},
                        },
                    },
                }
            ]
            factory = ProcessFactory(messages)
            runtime = CodexAppServerRuntime(_config(temp_dir), process_factory=factory)

            result = runtime.run_turn(_invocation(temp_dir, "Fail clearly."))

            self.assertEqual(result.status, CodexRunStatus.FAILED)
            self.assertEqual(result.error, "model failed")

    def test_run_turn_maps_interrupted_turn_to_cancelled_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            messages = _base_messages(Path(temp_dir)) + [
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "thread-1",
                        "turn": {"id": "turn-1", "status": "interrupted", "items": []},
                    },
                }
            ]
            factory = ProcessFactory(messages)
            runtime = CodexAppServerRuntime(_config(temp_dir), process_factory=factory)

            result = runtime.run_turn(_invocation(temp_dir, "Cancel clearly."))

            self.assertEqual(result.status, CodexRunStatus.CANCELLED)
            self.assertEqual(result.error, "Codex turn was interrupted")

    def test_run_turn_times_out_waiting_for_terminal_notification(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stdout = BlockingStdout(_base_messages(Path(temp_dir)))
            factory = ProcessFactory(stdout=stdout)
            runtime = CodexAppServerRuntime(
                _config(temp_dir, {"VERA_TURN_TIMEOUT_SECONDS": "1", "VERA_RUN_TIMEOUT_SECONDS": "5"}),
                process_factory=factory,
            )

            result = runtime.run_turn(
                _invocation(
                    temp_dir,
                    "Wait forever.",
                    {"VERA_TURN_TIMEOUT_SECONDS": "1", "VERA_RUN_TIMEOUT_SECONDS": "5"},
                )
            )

            self.assertEqual(result.status, CodexRunStatus.TIMED_OUT)
            self.assertTrue(factory.processes[0].terminated)

    def test_approval_request_blocks_by_default_without_auto_response(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            messages = _base_messages(Path(temp_dir)) + [
                {
                    "id": 99,
                    "method": "item/commandExecution/requestApproval",
                    "params": {"threadId": "thread-1", "turnId": "turn-1", "command": "rm -rf ."},
                }
            ]
            factory = ProcessFactory(messages)
            runtime = CodexAppServerRuntime(_config(temp_dir), process_factory=factory)

            result = runtime.run_turn(_invocation(temp_dir, "Need approval."))

            self.assertEqual(result.status, CodexRunStatus.APPROVAL_REQUIRED)
            self.assertIn("approval required", result.error)
            self.assertFalse(any(message.get("id") == 99 and "result" in message for message in _sent_messages(factory.processes[0])))

    def test_input_request_blocks_by_default_without_auto_response(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            messages = _base_messages(Path(temp_dir)) + [
                {
                    "id": 100,
                    "method": "item/tool/requestUserInput",
                    "params": {
                        "threadId": "thread-1",
                        "turnId": "turn-1",
                        "itemId": "item-1",
                        "questions": [{"id": "choice", "header": "Choice", "question": "Pick one"}],
                    },
                }
            ]
            factory = ProcessFactory(messages)
            runtime = CodexAppServerRuntime(_config(temp_dir), process_factory=factory)

            result = runtime.run_turn(_invocation(temp_dir, "Need input."))

            self.assertEqual(result.status, CodexRunStatus.INPUT_REQUIRED)
            self.assertIn("input required", result.error)
            self.assertFalse(any(message.get("id") == 100 and "result" in message for message in _sent_messages(factory.processes[0])))

    def test_explicit_auto_approval_response_is_sent_and_turn_continues(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            messages = _base_messages(Path(temp_dir)) + [
                {
                    "id": 99,
                    "method": "item/fileChange/requestApproval",
                    "params": {"threadId": "thread-1", "turnId": "turn-1", "files": ["a.py"]},
                },
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "thread-1",
                        "turn": {"id": "turn-1", "status": "completed", "items": []},
                    },
                },
            ]
            factory = ProcessFactory(messages)
            runtime = CodexAppServerRuntime(
                _config(temp_dir, {"VERA_CODEX_APPROVAL_DECISION": "decline"}),
                process_factory=factory,
            )

            result = runtime.run_turn(_invocation(temp_dir, "Decline safely."))

            self.assertEqual(result.status, CodexRunStatus.COMPLETED)
            response = [message for message in _sent_messages(factory.processes[0]) if message.get("id") == 99][0]
            self.assertEqual(response["result"], {"decision": "decline"})

    def test_explicit_auto_input_response_is_sent_and_turn_continues(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            messages = _base_messages(Path(temp_dir)) + [
                {
                    "id": 100,
                    "method": "item/tool/requestUserInput",
                    "params": {
                        "threadId": "thread-1",
                        "turnId": "turn-1",
                        "itemId": "item-1",
                        "questions": [{"id": "choice", "header": "Choice", "question": "Pick one"}],
                    },
                },
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "thread-1",
                        "turn": {"id": "turn-1", "status": "completed", "items": []},
                    },
                },
            ]
            factory = ProcessFactory(messages)
            runtime = CodexAppServerRuntime(
                _config(temp_dir, {"VERA_CODEX_AUTO_INPUT_RESPONSE": "default answer"}),
                process_factory=factory,
            )

            result = runtime.run_turn(_invocation(temp_dir, "Answer explicitly."))

            self.assertEqual(result.status, CodexRunStatus.COMPLETED)
            response = [message for message in _sent_messages(factory.processes[0]) if message.get("id") == 100][0]
            self.assertEqual(response["result"], {"answers": {"choice": {"answers": ["default answer"]}}})


def _config(temp_dir, extra_env=None):
    env = {
        "VERA_WORKSPACE_ROOT": temp_dir,
        "VERA_CODEX_APP_SERVER_COMMAND": "fake-codex app-server",
        "VERA_TURN_TIMEOUT_SECONDS": "5",
        "VERA_RUN_TIMEOUT_SECONDS": "10",
    }
    if extra_env:
        env.update(extra_env)
    return HarnessConfig.from_env(env, require_secrets=False)


def _invocation(temp_dir, prompt, extra_env=None):
    config = _config(temp_dir, extra_env)
    workspace = Workspace(
        workspace_id="task-1",
        task_id="task-1",
        root=Path(temp_dir),
        path=Path(temp_dir),
        created=True,
    )
    return CodexRuntimePlanner(config).plan(workspace, prompt)


def _successful_messages(workspace):
    return _base_messages(workspace) + [
        {
            "method": "turn/completed",
            "params": {
                "threadId": "thread-1",
                "turn": {"id": "turn-1", "status": "completed", "items": []},
            },
        }
    ]


def _persistent_success_messages(workspace):
    return _base_messages(workspace) + [
        {
            "method": "turn/completed",
            "params": {
                "threadId": "thread-1",
                "turn": {
                    "id": "turn-1",
                    "status": "completed",
                    "items": [
                        {
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "Hello from Codex."}],
                        }
                    ],
                },
            },
        },
        {"id": 4, "result": {"turn": {"id": "turn-2", "status": "inProgress", "items": []}}},
        {
            "method": "turn/completed",
            "params": {
                "threadId": "thread-1",
                "turn": {
                    "id": "turn-2",
                    "status": "completed",
                    "items": [
                        {
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "Still the same thread."}],
                        }
                    ],
                },
            },
        },
    ]


def _base_messages(workspace):
    return [
        {
            "id": 1,
            "result": {
                "userAgent": "fake-codex/1.0",
                "codexHome": "/tmp/fake-codex",
                "platformFamily": "unix",
                "platformOs": "test",
            },
        },
        {"method": "remoteControl/status/changed", "params": {"status": "disabled"}},
        {
            "id": 2,
            "result": {
                "thread": {"id": "thread-1"},
                "approvalPolicy": "on-request",
                "approvalsReviewer": "user",
                "cwd": str(workspace),
                "model": "gpt-test",
                "modelProvider": "openai",
                "sandbox": {"mode": "read-only"},
            },
        },
        {"id": 3, "result": {"turn": {"id": "turn-1", "status": "inProgress", "items": []}}},
    ]


def _event_from_payload(payload):
    return CodexRuntimeEvent(
        type=CodexRuntimeEventType.TURN_COMPLETED,
        method="turn/completed",
        payload=payload,
    )


def _sent_messages(process):
    return [json.loads(line) for line in process.stdin.lines]


if __name__ == "__main__":
    unittest.main()
