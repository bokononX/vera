"""Command line entrypoint for the Vera harness."""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple

from .codex import CodexAppServerError
from .config import ConfigError, HarnessConfig
from .orchestrator import FakeCodexRuntime, VeraHarness, format_dry_run, format_poll_once, format_telegram_loop
from .state import RunStateError
from .telegram import TelegramApiError, TelegramLongPollingIntake, TelegramUpdateStore
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
        help="Launch the local Vera terminal console.",
    )
    parser.add_argument(
        "--console-gui",
        action="store_true",
        help="Launch the local Vera web console.",
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
    ]
    if sum(1 for selected in selected_modes if selected) > 1:
        parser.error(
            "choose only one mode: --dry-run, --poll-once, --monitor, --fake-smoke, --live-smoke, --console-tui, --console-gui, or --check-config"
        )
    if not any(selected_modes):
        parser.error(
            "choose a mode: --dry-run, --poll-once, --monitor, --fake-smoke, --live-smoke, --console-tui, --console-gui, or --check-config"
        )
    if args.max_poll_cycles is not None and args.max_poll_cycles <= 0:
        parser.error("--max-poll-cycles must be greater than zero")
    if args.poll_interval_seconds < 0:
        parser.error("--poll-interval-seconds must be zero or greater")
    if args.console_port < 0:
        parser.error("--console-port must be zero or greater")

    try:
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
        ConfigError,
        PermissionError,
        RunStateError,
        TelegramApiError,
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


def _format_config_check(config: HarnessConfig) -> str:
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
            "event_log_path: {}".format(config.event_log_path),
            "budget_snapshot_path: {}".format(config.budget_snapshot_path or "<not configured>"),
            "monthly_budget_usd: {}".format(_display_optional_config(config.monthly_budget_usd)),
            "project_budget_usd: {}".format(_display_optional_config(config.project_budget_usd)),
            "workspace_root: {}".format(config.workspace_root),
        ]
    )


def _display_optional_config(value: object) -> str:
    if value is None:
        return "<not configured>"
    return str(value)


def _run_monitor(
    config: HarnessConfig,
    max_poll_cycles: Optional[int],
    poll_interval_seconds: float,
    title: str = "Vera Telegram-to-Codex loop",
) -> int:
    event_log = _console_event_log(config)
    harness = VeraHarness(config, on_event=event_log.append_task_event)
    cycles = 0
    while True:
        result = harness.run_telegram_poll_once()
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
        print(format_telegram_loop(result, title=title))
        cycles += 1
        if max_poll_cycles is not None and cycles >= max_poll_cycles:
            return 0
        time.sleep(poll_interval_seconds)


def _run_console_tui(config: HarnessConfig, args: argparse.Namespace) -> int:
    from .console_tui import run_tui

    return run_tui(
        _console_provider(config, args),
        focused_agent_id=args.console_focus,
        event_filter=args.console_filter,
        smoke=args.console_smoke,
    )


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
