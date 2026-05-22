"""Command line entrypoint for the Vera harness."""

from __future__ import annotations

import argparse
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple

from .chat import ChatSessionStateError
from .codex import CodexAppServerError
from .config import CommandResolution, ConfigError, HarnessConfig
from .models import TelegramTask
from .orchestrator import (
    FakeCodexRuntime,
    VeraHarness,
    format_dry_run,
    format_poll_once,
    format_telegram_chat_loop,
    format_telegram_loop,
)
from .state import RunStateError
from .telegram import TelegramApiError, TelegramLongPollingIntake, TelegramUpdateStore
from .user_memory import (
    IngestOptions,
    SourceRetention,
    UserMemoryIngestError,
    UserMemoryLintError,
    WikiLintOptions,
    ingest_user_memory,
    lint_user_memory,
    load_messages_from_file,
    messages_from_telegram_tasks,
    parse_datetime,
)
from .workspace import WorkspaceError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Vera harness scaffold.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan a Telegram-originated Codex run without network calls or Codex launch.",
    )
    parser.add_argument(
        "--poll-once",
        action="store_true",
        help="Long-poll Telegram once, queue accepted tasks, and exit without launching Codex.",
    )
    parser.add_argument(
        "--monitor",
        action="store_true",
        help="Continuously poll Telegram, run accepted tasks through Codex, and send status replies.",
    )
    parser.add_argument(
        "--fake-smoke",
        action="store_true",
        help="Run a fake Telegram update through workspace, policy, fake Codex runtime, and status replies.",
    )
    parser.add_argument(
        "--live-smoke",
        action="store_true",
        help="Poll Telegram once and run accepted tasks through the configured local Codex app-server.",
    )
    parser.add_argument(
        "--console-tui",
        action="store_true",
        help="Launch the local Vera terminal console and managed monitor loop.",
    )
    parser.add_argument(
        "--console-view-only",
        action="store_true",
        help="Launch --console-tui as a viewer without starting a monitor loop.",
    )
    parser.add_argument(
        "--console-gui",
        action="store_true",
        help="Launch the local Vera web console.",
    )
    parser.add_argument(
        "--ingest-user-memory",
        action="store_true",
        help="Extract conversation memories and propose or apply user-memory wiki updates.",
    )
    parser.add_argument(
        "--lint-user-memory",
        action="store_true",
        help="Scan a user-memory wiki and produce a reviewable lint/consolidation report.",
    )
    parser.add_argument(
        "--console-fake-state",
        action="store_true",
        help="Use deterministic fake console state instead of local harness state.",
    )
    parser.add_argument(
        "--console-smoke",
        action="store_true",
        help="Run one non-interactive console smoke check and exit.",
    )
    parser.add_argument(
        "--console-focus",
        default=None,
        help="Initial console focus by agent id or task id.",
    )
    parser.add_argument(
        "--console-filter",
        default=None,
        help="Initial console event filter text.",
    )
    parser.add_argument(
        "--console-host",
        default="127.0.0.1",
        help="Host for --console-gui. Defaults to 127.0.0.1.",
    )
    parser.add_argument(
        "--console-port",
        type=int,
        default=8765,
        help="Port for --console-gui. Use 0 to choose a free port.",
    )
    parser.add_argument(
        "--message",
        default="Draft a concise project status update.",
        help="Telegram message text to turn into a dry-run task.",
    )
    parser.add_argument("--chat-id", type=int, default=0, help="Telegram chat id.")
    parser.add_argument("--user-id", type=int, default=0, help="Telegram user id.")
    parser.add_argument("--message-id", type=int, default=1, help="Telegram message id.")
    parser.add_argument("--update-id", type=int, default=9001, help="Telegram update id for fake smoke mode.")
    parser.add_argument("--username", default=None, help="Optional Telegram username.")
    parser.add_argument(
        "--workspace-root",
        default=None,
        help="Override VERA_WORKSPACE_ROOT for this invocation.",
    )
    parser.add_argument(
        "--telegram-config",
        default=None,
        help="Path to Telegram non-secret JSON config. Defaults to ./.vera/telegram_config.json.",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate configuration and print a non-secret summary without network calls.",
    )
    parser.add_argument(
        "--no-create-workspace",
        action="store_true",
        help="Resolve the dry-run workspace path without creating directories.",
    )
    parser.add_argument(
        "--max-poll-cycles",
        type=int,
        default=None,
        help="Stop --monitor after this many polling cycles. Defaults to unlimited.",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=2.0,
        help="Sleep between --monitor polling cycles. Defaults to 2 seconds.",
    )
    parser.add_argument(
        "--conversation-file",
        default=None,
        help="Transcript text or normalized Telegram JSON file to ingest into user memory.",
    )
    parser.add_argument(
        "--memory-root",
        default="./memory/users/default",
        help="User-memory corpus root. Defaults to ./memory/users/default.",
    )
    parser.add_argument(
        "--memory-user-id",
        default="default",
        help="Owner user id written to user-memory wiki frontmatter.",
    )
    parser.add_argument(
        "--memory-source-channel",
        default="codex",
        help="Source channel label for the ingest, for example codex or telegram.",
    )
    parser.add_argument(
        "--memory-source-id",
        default=None,
        help="Optional stable source id. Defaults to a deterministic date/channel/hash id.",
    )
    parser.add_argument(
        "--memory-source-retention",
        choices=[item.value for item in SourceRetention],
        default=SourceRetention.HASH_ONLY.value,
        help="Whether to store raw source text or retain only hashes/redaction metadata.",
    )
    parser.add_argument(
        "--apply-memory-ingest",
        action="store_true",
        help="Apply the proposed user-memory wiki edits. Omit for dry-run review mode.",
    )
    parser.add_argument(
        "--apply-memory-lint",
        action="store_true",
        help="Apply high-confidence mechanical lint fixes. Omit for dry-run report mode.",
    )
    parser.add_argument(
        "--memory-lint-as-of",
        default=None,
        help="ISO-8601 timestamp used for deterministic stale-memory checks.",
    )
    parser.add_argument(
        "--captured-at",
        default=None,
        help="ISO-8601 captured timestamp for deterministic ingest output.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    selected_modes = [
        args.dry_run,
        args.poll_once,
        args.check_config,
        args.monitor,
        args.fake_smoke,
        args.live_smoke,
        args.console_tui,
        args.console_gui,
        args.ingest_user_memory,
        args.lint_user_memory,
    ]
    if sum(1 for selected in selected_modes if selected) > 1:
        parser.error(
            "choose only one mode: --dry-run, --poll-once, --monitor, --fake-smoke, --live-smoke, --console-tui, --console-gui, --ingest-user-memory, --lint-user-memory, or --check-config"
        )
    if not any(selected_modes):
        parser.error(
            "choose a mode: --dry-run, --poll-once, --monitor, --fake-smoke, --live-smoke, --console-tui, --console-gui, --ingest-user-memory, --lint-user-memory, or --check-config"
        )
    if args.max_poll_cycles is not None and args.max_poll_cycles <= 0:
        parser.error("--max-poll-cycles must be greater than zero")
    if args.poll_interval_seconds < 0:
        parser.error("--poll-interval-seconds must be zero or greater")
    if args.console_port < 0:
        parser.error("--console-port must be zero or greater")
    if args.console_view_only and not args.console_tui:
        parser.error("--console-view-only requires --console-tui")
    if args.apply_memory_ingest and not args.ingest_user_memory:
        parser.error("--apply-memory-ingest requires --ingest-user-memory")
    if args.apply_memory_lint and not args.lint_user_memory:
        parser.error("--apply-memory-lint requires --lint-user-memory")

    try:
        if args.ingest_user_memory:
            return _run_user_memory_ingest(args)
        if args.lint_user_memory:
            return _run_user_memory_lint(args)
        config = HarnessConfig.load(
            require_secrets=args.poll_once or args.check_config or args.monitor or args.live_smoke,
            telegram_config_path=args.telegram_config,
        )
        if args.workspace_root is not None:
            config = replace(
                config,
                workspace_root=Path(args.workspace_root).expanduser().resolve(),
            )
        if args.check_config:
            print(_format_config_check(config))
            return 0
        if args.console_tui:
            return _run_console_tui(config, args)
        if args.console_gui:
            return _run_console_gui(config, args)
        harness = VeraHarness(config)
        if args.poll_once:
            print(format_poll_once(harness.poll_telegram_once()))
            return 0
        if args.monitor:
            return _run_monitor(
                config,
                max_poll_cycles=args.max_poll_cycles,
                poll_interval_seconds=args.poll_interval_seconds,
            )
        if args.live_smoke:
            return _run_monitor(
                config,
                max_poll_cycles=args.max_poll_cycles or 1,
                poll_interval_seconds=args.poll_interval_seconds,
                title="Vera Telegram-to-Codex live smoke",
            )
        if args.fake_smoke:
            return _run_fake_smoke(config, args)

        result = harness.dry_run_task(
            text=args.message,
            chat_id=args.chat_id,
            user_id=args.user_id,
            message_id=args.message_id,
            username=args.username,
            create_workspace=not args.no_create_workspace,
        )
    except (
        CodexAppServerError,
        ChatSessionStateError,
        ConfigError,
        PermissionError,
        RunStateError,
        TelegramApiError,
        UserMemoryIngestError,
        UserMemoryLintError,
        ValueError,
        WorkspaceError,
    ) as exc:
        print("vera-harness: {}".format(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("vera-harness: stopped by interrupt", file=sys.stderr)
        return 130

    print(format_dry_run(result))
    return 0


def _run_user_memory_ingest(args: argparse.Namespace) -> int:
    captured_at = parse_datetime(args.captured_at) if args.captured_at else None
    source_retention = SourceRetention(args.memory_source_retention)
    if args.conversation_file is not None:
        conversation_path = Path(args.conversation_file).expanduser().resolve()
        messages, source_text = load_messages_from_file(
            conversation_path,
            channel=args.memory_source_channel,
        )
    else:
        task = TelegramTask.from_message(
            chat_id=args.chat_id,
            user_id=args.user_id,
            message_id=args.message_id,
            text=args.message,
            username=args.username,
            received_at=captured_at,
        )
        messages = messages_from_telegram_tasks((task,))
        source_text = args.message
    plan = ingest_user_memory(
        messages=messages,
        source_text=source_text,
        options=IngestOptions(
            root=Path(args.memory_root).expanduser().resolve(),
            owner_user=args.memory_user_id,
            channel=args.memory_source_channel,
            source_id=args.memory_source_id,
            captured_at=captured_at,
            source_retention=source_retention,
        ),
        apply=args.apply_memory_ingest,
    )
    print(plan.format_human_readable())
    return 0


def _run_user_memory_lint(args: argparse.Namespace) -> int:
    as_of = parse_datetime(args.memory_lint_as_of) if args.memory_lint_as_of else None
    report = lint_user_memory(
        WikiLintOptions(
            root=Path(args.memory_root).expanduser().resolve(),
            owner_user=args.memory_user_id,
            as_of=as_of,
            apply=args.apply_memory_lint,
        )
    )
    print(report.format_human_readable())
    return 0


def _format_config_check(config: HarnessConfig) -> str:
    codex_command = _validate_codex_app_server_command(config)
    unauthorized = config.telegram_unauthorized_response
    if unauthorized is None:
        unauthorized = "<disabled>"
    return "\n".join(
        [
            "Vera configuration OK",
            "telegram_bot_token: <secret-present>",
            "allowed_chat_ids: {}".format(",".join(str(item) for item in config.allowed_chat_ids)),
            "allowed_user_ids: {}".format(",".join(str(item) for item in config.allowed_user_ids)),
            "telegram_api_base_url: {}".format(config.telegram_api_base_url),
            "telegram_poll_timeout_seconds: {}".format(config.telegram_poll_timeout_seconds),
            "telegram_request_timeout_seconds: {}".format(config.telegram_request_timeout_seconds),
            "telegram_state_path: {}".format(config.telegram_state_path),
            "telegram_unauthorized_response: {}".format(unauthorized),
            "assistant_identity_name: {}".format(config.assistant_identity.safe_display_name),
            "assistant_identity_path: {}".format(config.assistant_identity_path),
            "assistant_identity_interview_state_path: {}".format(
                config.assistant_identity_interview_state_path
            ),
            "owner_identity: {}".format(_format_owner_identity(config)),
            "owner_profile_source: {}".format(_format_owner_profile_source(config)),
            "chat_session_state_path: {}".format(config.chat_session_state_path),
            "identity_profile_path: {}".format(config.identity_profile_path),
            "identity_interview_state_path: {}".format(config.identity_interview_state_path),
            "user_memory_root: {}".format(config.user_memory_root or "<not configured>"),
            "event_log_path: {}".format(config.event_log_path),
            "budget_snapshot_path: {}".format(config.budget_snapshot_path or "<not configured>"),
            "monthly_budget_usd: {}".format(_display_optional_config(config.monthly_budget_usd)),
            "project_budget_usd: {}".format(_display_optional_config(config.project_budget_usd)),
            "workspace_root: {}".format(config.workspace_root),
            "codex_app_server_command: {}".format(config.codex_app_server_command.display),
            "codex_app_server_executable: {}".format(codex_command.resolved_executable),
        ]
    )


def _display_optional_config(value: object) -> str:
    if value is None:
        return "<not configured>"
    return str(value)


def _format_owner_identity(config: HarnessConfig) -> str:
    if config.owner_profile is None:
        return "<not configured>"
    return config.owner_profile.redacted_identity_label()


def _format_owner_profile_source(config: HarnessConfig) -> str:
    if config.owner_profile is None:
        return "<not configured>"
    if config.owner_profile.wiki_profile_path is not None:
        return str(config.owner_profile.wiki_profile_path)
    if config.owner_profile.has_profile_content:
        return "local owner config"
    return "<empty>"


def _validate_codex_app_server_command(config: HarnessConfig) -> CommandResolution:
    return config.codex_app_server_command.resolve_executable(
        "VERA_CODEX_APP_SERVER_COMMAND",
        cwd=Path.cwd(),
    )


def _run_monitor(
    config: HarnessConfig,
    max_poll_cycles: Optional[int],
    poll_interval_seconds: float,
    title: str = "Vera Telegram-to-Codex loop",
) -> int:
    _validate_codex_app_server_command(config)
    event_log = _console_event_log(config)
    harness = VeraHarness(config, on_event=event_log.append_task_event)
    cycles = 0
    while True:
        result = harness.run_telegram_chat_poll_once()
        _append_telegram_chat_events(event_log, result)
        print(format_telegram_chat_loop(result, title=title))
        cycles += 1
        if max_poll_cycles is not None and cycles >= max_poll_cycles:
            return 0
        time.sleep(poll_interval_seconds)


def _run_console_tui(config: HarnessConfig, args: argparse.Namespace) -> int:
    from .console_tui import run_tui

    provider = _console_provider(config, args)
    supervisor = None
    if _console_should_manage_monitor(args):
        supervisor = _ConsoleMonitorSupervisor(
            config,
            poll_interval_seconds=args.poll_interval_seconds,
        )
        supervisor.start()
    try:
        return run_tui(
            provider,
            focused_agent_id=args.console_focus,
            event_filter=args.console_filter,
            smoke=args.console_smoke,
        )
    finally:
        if supervisor is not None:
            supervisor.stop()


def _console_should_manage_monitor(args: argparse.Namespace) -> bool:
    return bool(args.console_tui and not args.console_view_only and not args.console_fake_state)


class _ConsoleMonitorSupervisor:
    """Own the monitor loop lifecycle while the TUI owns terminal rendering."""

    def __init__(self, config: HarnessConfig, poll_interval_seconds: float) -> None:
        self._config = config
        self._poll_interval_seconds = poll_interval_seconds
        self._event_log = _console_event_log(config)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._harness: Optional[VeraHarness] = None

    def start(self) -> None:
        startup_error = _console_monitor_startup_error(self._config)
        if startup_error is not None:
            _append_console_monitor_error(
                self._event_log,
                event_type="console_monitor_startup_failed",
                summary="Console monitor did not start: {}".format(startup_error),
                config=self._config,
            )
            return

        self._harness = VeraHarness(self._config, on_event=self._event_log.append_task_event)
        self._event_log.append_source_event(
            source="console-tui",
            event_type="console_monitor_started",
            summary="Console monitor started.",
            details=_console_monitor_details(self._config),
        )
        self._thread = threading.Thread(
            target=self._run,
            name="vera-console-tui-monitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self._poll_interval_seconds + 1.0))

    def _run(self) -> None:
        assert self._harness is not None
        try:
            while not self._stop_event.is_set():
                result = self._harness.run_telegram_chat_poll_once()
                _append_telegram_chat_events(self._event_log, result)
                if self._stop_event.wait(self._poll_interval_seconds):
                    break
        except Exception as exc:  # noqa: BLE001 - surface background failures in the console.
            _append_console_monitor_error(
                self._event_log,
                event_type="console_monitor_failed",
                summary="Console monitor stopped after error: {}".format(exc),
                config=self._config,
            )
        finally:
            self._event_log.append_source_event(
                source="console-tui",
                event_type="console_monitor_stopped",
                summary="Console monitor stopped.",
                details=_console_monitor_details(self._config),
            )


def _console_monitor_startup_error(config: HarnessConfig) -> Optional[str]:
    failures = []
    if not config.telegram_bot_token:
        failures.append("VERA_TELEGRAM_BOT_TOKEN is required for live console monitoring")
    if not config.allowed_chat_ids and not config.allowed_user_ids:
        failures.append(
            "telegram.allowed_chat_ids or telegram.allowed_user_ids is required for live console monitoring"
        )
    try:
        config.codex_app_server_command.resolve_executable(
            "VERA_CODEX_APP_SERVER_COMMAND",
            cwd=Path.cwd(),
        )
    except ConfigError as exc:
        failures.append(str(exc))
    if failures:
        return "; ".join(failures)
    return None


def _append_telegram_status_events(event_log: Any, result: Any) -> None:
    for delivery in result.status_deliveries:
        event_log.append_source_event(
            source="telegram",
            event_type="telegram_status",
            summary=delivery.text,
            task_id=delivery.task_id,
            run_id=None,
            details={
                "chat_id": delivery.chat_id,
                "message_id": delivery.message_id,
                "update_id": delivery.update_id,
                "status": delivery.status.value,
            },
        )


def _append_telegram_chat_events(event_log: Any, result: Any) -> None:
    for delivery in result.response_deliveries:
        event_log.append_source_event(
            source="telegram",
            event_type="telegram_chat_response",
            summary=delivery.text,
            task_id=delivery.session_id,
            run_id=delivery.session_id,
            details={
                "chat_id": delivery.chat_id,
                "message_id": delivery.message_id,
                "update_id": delivery.update_id,
                "status": delivery.status.value,
            },
        )


def _append_console_monitor_error(
    event_log: Any,
    event_type: str,
    summary: str,
    config: HarnessConfig,
) -> None:
    from .observability import ConsoleEvent, ConsoleEventCategory

    event_log.append_console_event(
        ConsoleEvent(
            event_id="evt-{}".format(uuid.uuid4().hex),
            created_at=datetime.now(timezone.utc).isoformat(),
            category=ConsoleEventCategory.ERROR,
            event_type=event_type,
            source="console-tui",
            summary=summary,
            severity="error",
            details=_console_monitor_details(config),
        )
    )


def _console_monitor_details(config: HarnessConfig) -> Mapping[str, object]:
    return {
        "run_state_path": str(config.run_state_path),
        "event_log_path": str(config.event_log_path),
        "telegram_state_path": str(config.telegram_state_path),
        "chat_session_state_path": str(config.chat_session_state_path),
        "assistant_identity_name": config.assistant_identity.safe_display_name,
        "assistant_identity_path": str(config.assistant_identity_path),
        "assistant_identity_interview_state_path": str(
            config.assistant_identity_interview_state_path
        ),
        "identity_profile_path": str(config.identity_profile_path),
        "identity_interview_state_path": str(config.identity_interview_state_path),
        "codex_app_server_command": config.codex_app_server_command.display,
    }


def _run_console_gui(config: HarnessConfig, args: argparse.Namespace) -> int:
    from .console_gui import run_gui

    return run_gui(
        _console_provider(config, args),
        host=args.console_host,
        port=args.console_port,
        smoke=args.console_smoke,
    )


def _console_provider(config: HarnessConfig, args: argparse.Namespace):
    if args.console_fake_state:
        from .observability import fake_observability_provider

        return fake_observability_provider()
    from .observability import JsonObservabilityProvider

    return JsonObservabilityProvider.from_config(config)


def _console_event_log(config: HarnessConfig):
    from .observability import JsonConsoleEventLog

    return JsonConsoleEventLog(config.event_log_path)


def _run_fake_smoke(config: HarnessConfig, args: argparse.Namespace) -> int:
    update = _fake_update(
        update_id=args.update_id,
        chat_id=args.chat_id,
        user_id=args.user_id,
        message_id=args.message_id,
        text=args.message,
        username=args.username,
    )
    fake_api = _FakeTelegramApi((update,))
    with tempfile.TemporaryDirectory(prefix="vera-fake-smoke-") as temp_dir:
        smoke_config = replace(
            config,
            telegram_bot_token="fake-token",
            allowed_chat_ids=(args.chat_id,),
            allowed_user_ids=(args.user_id,),
            telegram_state_path=Path(temp_dir, "telegram-state.json").resolve(),
            run_state_path=Path(temp_dir, "run-state.json").resolve(),
        )
        intake = TelegramLongPollingIntake(
            smoke_config,
            api=fake_api,
            store=TelegramUpdateStore(smoke_config.telegram_state_path),
        )
        harness = VeraHarness(smoke_config, runtime=FakeCodexRuntime())
        result = harness.run_telegram_poll_once(
            polling_intake=intake,
            runtime=FakeCodexRuntime(),
            dry_run=True,
            run_bootstrap=False,
        )
    print(format_telegram_loop(result, title="Vera Telegram-to-Codex fake smoke"))
    return 0


class _FakeTelegramApi:
    def __init__(self, updates: Tuple[Mapping[str, Any], ...]) -> None:
        self._updates = updates
        self.sent_messages: list[Mapping[str, object]] = []

    def get_updates(self, offset: Optional[int], timeout: int) -> Tuple[Mapping[str, Any], ...]:
        return tuple(
            update
            for update in self._updates
            if offset is None or _update_id(update) >= offset
        )

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: Optional[int] = None,
    ) -> Mapping[str, object]:
        message = {
            "chat_id": chat_id,
            "text": text,
            "reply_to_message_id": reply_to_message_id,
        }
        self.sent_messages.append(message)
        return {"message_id": len(self.sent_messages)}


def _fake_update(
    update_id: int,
    chat_id: int,
    user_id: int,
    message_id: int,
    text: str,
    username: Optional[str],
) -> Mapping[str, object]:
    sender: dict[str, object] = {"id": user_id}
    if username is not None:
        sender["username"] = username
    return {
        "update_id": update_id,
        "message": {
            "message_id": message_id,
            "chat": {"id": chat_id},
            "from": sender,
            "text": text,
        },
    }


def _update_id(update: Mapping[str, Any]) -> int:
    value = update.get("update_id")
    return value if isinstance(value, int) else -1


if __name__ == "__main__":
    raise SystemExit(main())
