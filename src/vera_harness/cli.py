"""Command line entrypoint for the Vera harness."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import Optional, Sequence

from .config import ConfigError, HarnessConfig
from .orchestrator import VeraHarness, format_dry_run, format_poll_once
from .telegram import TelegramApiError


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
        "--message",
        default="Draft a concise project status update.",
        help="Telegram message text to turn into a dry-run task.",
    )
    parser.add_argument("--chat-id", type=int, default=0, help="Telegram chat id.")
    parser.add_argument("--user-id", type=int, default=0, help="Telegram user id.")
    parser.add_argument("--message-id", type=int, default=1, help="Telegram message id.")
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
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    selected_modes = [args.dry_run, args.poll_once, args.check_config]
    if sum(1 for selected in selected_modes if selected) > 1:
        parser.error("choose only one mode: --dry-run, --poll-once, or --check-config")
    if not any(selected_modes):
        parser.error("choose a mode: --dry-run, --poll-once, or --check-config")

    try:
        config = HarnessConfig.load(
            require_secrets=args.poll_once or args.check_config,
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
        harness = VeraHarness(config)
        if args.poll_once:
            print(format_poll_once(harness.poll_telegram_once()))
            return 0

        result = harness.dry_run_task(
            text=args.message,
            chat_id=args.chat_id,
            user_id=args.user_id,
            message_id=args.message_id,
            username=args.username,
            create_workspace=not args.no_create_workspace,
        )
    except (ConfigError, PermissionError, TelegramApiError, ValueError) as exc:
        print("vera-harness: {}".format(exc), file=sys.stderr)
        return 2

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
            "workspace_root: {}".format(config.workspace_root),
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
