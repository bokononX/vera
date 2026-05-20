"""Command line entrypoint for the Vera harness."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import Optional, Sequence

from .config import ConfigError, HarnessConfig
from .orchestrator import VeraHarness, format_dry_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Vera harness scaffold.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan a Telegram-originated Codex run without network calls or Codex launch.",
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
        "--no-create-workspace",
        action="store_true",
        help="Resolve the dry-run workspace path without creating directories.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.dry_run:
        parser.error("live Telegram/Codex runtime is not implemented; use --dry-run")

    try:
        config = HarnessConfig.from_env(require_secrets=False)
        if args.workspace_root is not None:
            config = replace(
                config,
                workspace_root=Path(args.workspace_root).expanduser().resolve(),
            )
        harness = VeraHarness(config)
        result = harness.dry_run_task(
            text=args.message,
            chat_id=args.chat_id,
            user_id=args.user_id,
            message_id=args.message_id,
            username=args.username,
            create_workspace=not args.no_create_workspace,
        )
    except (ConfigError, PermissionError, ValueError) as exc:
        print("vera-harness: {}".format(exc), file=sys.stderr)
        return 2

    print(format_dry_run(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
