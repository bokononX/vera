# Vera Harness

This repository contains the Python scaffold for the Vera agent harness. It can
load configuration, synthesize the Herald policy prompt, resolve a per-task
workspace, print dry-run Codex app-server invocation plans, and drive a Codex
app-server turn over newline-delimited JSON-RPC through a testable runtime
adapter.

## Local Dry Run

From a clean checkout:

```sh
PYTHONPATH=src python3 -m vera_harness --dry-run \
  --message "Summarize the current project state" \
  --chat-id 12345 \
  --user-id 67890
```

The command prints:

- the Telegram-originated task id;
- the local workspace path;
- the synthesized prompt and policy summary;
- the planned Codex app-server launch settings;
- confirmation that Telegram and Codex network/runtime calls were skipped.

Dry runs default to `./.vera/workspaces` for local task workspaces. That path is
ignored by git.

## Configuration

Configuration is read from environment variables. Dry-run mode does not require
secrets. Future live Telegram/Codex runtime modes should call the same loader
with secret validation enabled.

| Variable | Required for dry run | Description |
| --- | --- | --- |
| `VERA_TELEGRAM_BOT_TOKEN` | No | Telegram bot token. Required only for future live Telegram intake. |
| `VERA_ALLOWED_CHAT_IDS` | No | Comma-separated Telegram chat ids allowed to submit tasks. Empty means unrestricted in dry run. |
| `VERA_ALLOWED_USER_IDS` | No | Comma-separated Telegram user ids allowed to submit tasks. Empty means unrestricted in dry run. |
| `VERA_WORKSPACE_ROOT` | No | Root directory for per-task workspaces. Defaults to `./.vera/workspaces`. |
| `VERA_CODEX_APP_SERVER_COMMAND` | No | Shell-style command used to launch the Codex app server. Defaults to `codex app-server`. |
| `VERA_MAX_TURNS` | No | Maximum Codex turns per harness run. Defaults to `20`. |
| `VERA_TURN_TIMEOUT_SECONDS` | No | Timeout for one Codex turn. Defaults to `300`. |
| `VERA_RUN_TIMEOUT_SECONDS` | No | Timeout for the whole harness run. Defaults to `1800`. |
| `VERA_APPROVAL_POLICY` | No | Planned Codex approval policy: `untrusted`, `on-request`, `on-failure`, or `never`. Defaults to `on-request`. |
| `VERA_SANDBOX_MODE` | No | Planned Codex sandbox mode: `read-only`, `workspace-write`, or `danger-full-access`. Defaults to `read-only`. |
| `VERA_CODEX_APPROVAL_DECISION` | No | Optional unattended response for command/file approval prompts: `accept`, `acceptForSession`, `decline`, or `cancel`. Empty by default, which returns an explicit blocked outcome. |
| `VERA_CODEX_AUTO_INPUT_RESPONSE` | No | Optional unattended text answer for app-server `request_user_input` prompts. Empty by default, which returns an explicit blocked outcome. |
| `VERA_REPO_CLONE_COMMAND` | No | Optional shell-style command for future workspace repository cloning. Not executed in dry run. |
| `VERA_REPO_BOOTSTRAP_COMMAND` | No | Optional shell-style command for future workspace bootstrap. Not executed in dry run. |

Do not commit actual secret values. Documentation should name variables only.

## Development

Run the focused test suite:

```sh
python3 -m pytest
```

The tests use a fake JSON-RPC subprocess for runtime paths and do not require
live Telegram or Codex access.

## Current Runtime Boundary

Implemented now:

- configuration parsing and validation;
- domain models for Telegram tasks, harness runs, workspaces, and Codex turn
  results;
- module boundaries for config, Telegram intake, workspace management, Codex
  runtime planning, prompt/policy, and orchestration;
- dry-run CLI output for local validation;
- Codex app-server launch over stdio JSON-RPC;
- `initialize`, `thread/start`, and `turn/start` request flow;
- structured runtime events for server notifications, approval-required,
  input-required, completion, failure, cancellation, timeout, and process exit;
- fail-closed unattended behavior unless explicit auto-response config is set.

Not implemented in this ticket:

- live Telegram polling or webhook handling;
- repository cloning or bootstrap execution.
