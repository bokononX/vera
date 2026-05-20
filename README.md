# Vera Harness

This repository contains the Python scaffold for the Vera agent harness. It can
load configuration, synthesize the Herald policy prompt, resolve a per-task
workspace, poll Telegram through the Bot API, queue authorized Telegram tasks,
print dry-run Codex app-server invocation plans, and drive a Codex app-server
turn over newline-delimited JSON-RPC through a testable runtime adapter.

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

Dry runs default to `./.vera/workspaces` for local task workspaces. Workspace
paths are derived from stable Telegram task ids, sanitized to a single safe path
segment, and validated after resolution so symlinks cannot move Codex outside
the configured workspace root. That path is ignored by git.

## Telegram Polling

Live Telegram intake uses Bot API long polling. It currently queues accepted
tasks for orchestration and sends Telegram status replies, but it does not
launch Codex.

```sh
export VERA_TELEGRAM_BOT_TOKEN="..."
export VERA_ALLOWED_CHAT_IDS="12345"
export VERA_ALLOWED_USER_IDS="67890"

PYTHONPATH=src python3 -m vera_harness --poll-once
```

`--poll-once` performs one `getUpdates` call, suppresses updates already
recorded in the local state file, converts authorized text messages into
minimal `TelegramTask` objects, queues them in memory for the current process,
and sends concise Telegram replies such as `Accepted: queued.` or
`Blocked: I need your judgment before continuing.`

Unauthorized chats/users are ignored by default. Set
`VERA_TELEGRAM_UNAUTHORIZED_RESPONSE` to send a short rejection response
instead.

Telegram offset and task lifecycle state are persisted locally at
`VERA_TELEGRAM_STATE_PATH`. The state file stores update ids and task metadata
such as chat id, user id, message id, and lifecycle status. It does not persist
raw Telegram message text or usernames.

## Configuration

Configuration is read from environment variables. Dry-run mode does not require
secrets. Telegram polling validates live Bot API and allow-list settings.

| Variable | Required for dry run | Description |
| --- | --- | --- |
| `VERA_TELEGRAM_BOT_TOKEN` | No | Telegram bot token. Required for `--poll-once`. |
| `VERA_ALLOWED_CHAT_IDS` | No | Comma-separated Telegram chat ids allowed to submit tasks. Empty means unrestricted in dry run. |
| `VERA_ALLOWED_USER_IDS` | No | Comma-separated Telegram user ids allowed to submit tasks. Empty means unrestricted in dry run. |
| `VERA_TELEGRAM_API_BASE_URL` | No | Telegram API base URL. Defaults to `https://api.telegram.org`. |
| `VERA_TELEGRAM_POLL_TIMEOUT_SECONDS` | No | Telegram long-poll timeout. Defaults to `30`. |
| `VERA_TELEGRAM_REQUEST_TIMEOUT_SECONDS` | No | HTTP request timeout for Telegram API calls. Defaults to `35`. |
| `VERA_TELEGRAM_STATE_PATH` | No | Local JSON file for Telegram update offsets and task lifecycle state. Defaults to `./.vera/telegram_state.json`. |
| `VERA_TELEGRAM_UNAUTHORIZED_RESPONSE` | No | Optional concise response sent to unauthorized Telegram sources. Empty means ignore unauthorized updates after recording their offset. |
| `VERA_WORKSPACE_ROOT` | No | Root directory for per-task workspaces. Defaults to `./.vera/workspaces`. |
| `VERA_WORKSPACE_BOOTSTRAP_TIMEOUT_SECONDS` | No | Timeout for each configured workspace clone/bootstrap command. Defaults to `300`. |
| `VERA_WORKSPACE_RETENTION_POLICY` | No | Retention policy recorded in workspace metadata: `retain`, `cleanup_on_success`, or `cleanup_on_completion`. Defaults to `retain`. |
| `VERA_CODEX_APP_SERVER_COMMAND` | No | Shell-style command used to launch the Codex app server. Defaults to `codex app-server`. |
| `VERA_MAX_TURNS` | No | Maximum Codex turns per harness run. Defaults to `20`. |
| `VERA_TURN_TIMEOUT_SECONDS` | No | Timeout for one Codex turn. Defaults to `300`. |
| `VERA_RUN_TIMEOUT_SECONDS` | No | Timeout for the whole harness run. Defaults to `1800`. |
| `VERA_APPROVAL_POLICY` | No | Planned Codex approval policy: `untrusted`, `on-request`, `on-failure`, or `never`. Defaults to `on-request`. |
| `VERA_SANDBOX_MODE` | No | Planned Codex sandbox mode: `read-only`, `workspace-write`, or `danger-full-access`. Defaults to `read-only`. |
| `VERA_CODEX_APPROVAL_DECISION` | No | Optional unattended response for command/file approval prompts: `accept`, `acceptForSession`, `decline`, or `cancel`. Empty by default, which returns an explicit blocked outcome. |
| `VERA_CODEX_AUTO_INPUT_RESPONSE` | No | Optional unattended text answer for app-server `request_user_input` prompts. Empty by default, which returns an explicit blocked outcome. |
| `VERA_REPO_CLONE_COMMAND` | No | Optional shell-style command executed in a newly prepared workspace before the bootstrap command. Not executed in dry run. |
| `VERA_REPO_BOOTSTRAP_COMMAND` | No | Optional shell-style command executed in a newly prepared workspace after the clone command. Not executed in dry run. |

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
- domain models for Telegram tasks, harness runs, workspaces, workspace reuse
  policy, bootstrap diagnostics, and Codex turn results;
- module boundaries for config, Telegram intake, Telegram state persistence,
  workspace management, Codex runtime planning/execution, prompt/policy, and
  orchestration;
- Telegram Bot API long polling with injectable transport for tests;
- authorization by configured chat and/or user ids;
- duplicate update suppression across restarts through local offset
  persistence;
- concise Telegram status replies for accepted, rejected, started, completed,
  and blocked task states;
- deterministic isolated workspace lifecycle with explicit reuse/fresh/existing
  policies, metadata recording, root escape protection, bounded bootstrap
  command execution, and guarded cleanup hooks;
- dry-run CLI output for local validation;
- Codex app-server launch over stdio JSON-RPC;
- `initialize`, `thread/start`, and `turn/start` request flow;
- structured runtime events for server notifications, approval-required,
  input-required, completion, failure, cancellation, timeout, and process exit;
- fail-closed unattended behavior unless explicit auto-response config is set.

Not implemented in this ticket:

- Telegram webhook handling;
- continuous multi-task orchestration beyond the in-memory accepted-task queue.
