# Vera Harness

This repository contains the Python scaffold for the Vera agent harness. It can
load configuration, synthesize the Herald/The Place/Vera policy prompt, resolve
a per-task workspace, poll Telegram through the Bot API, queue authorized
Telegram tasks, run accepted tasks through a fake or live Codex runtime, and
send concise Telegram status replies for the task lifecycle.

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
- the fake-runtime final decision and structured event sequence;
- confirmation that Telegram and Codex network/runtime calls were skipped.

Dry runs default to `./.vera/workspaces` for local task workspaces. Workspace
paths are derived from stable Telegram task ids, sanitized to a single safe path
segment, and validated after resolution so symlinks cannot move Codex outside
the configured workspace root. That path is ignored by git.

## Fake End-to-End Smoke

The fake smoke path exercises the Telegram intake, task queue, workspace
lifecycle, policy prompt, fake Codex runtime, final supervisor decision, and
Telegram status responses without live Telegram or real Codex.

```sh
PYTHONPATH=src python3 -m vera_harness --fake-smoke \
  --message "Summarize the current project state" \
  --chat-id 100 \
  --user-id 200 \
  --message-id 300 \
  --update-id 700 \
  --workspace-root ./.vera/fake-smoke-workspaces
```

The command prints an operational log with the task id, Telegram chat/update/
message ids, workspace path, Codex thread/turn ids when available, Telegram
status texts, event sequence, and final outcome. It does not require
`VERA_TELEGRAM_BOT_TOKEN`, does not contact Telegram, does not launch Codex, and
does not print the raw Telegram task text.

## Operational Monitor

Live Telegram intake uses Bot API long polling. The production monitor command
polls Telegram, queues authorized text messages, prepares an isolated workspace,
runs Codex through the configured app-server command, and sends Telegram status
replies for accepted, started, blocked, failed, and completed outcomes.

```sh
mkdir -p .vera
cp config/telegram.example.json .vera/telegram_config.json
# Edit .vera/telegram_config.json with your allowed Telegram chat/user ids.
export VERA_TELEGRAM_BOT_TOKEN="..."

PYTHONPATH=src python3 -m vera_harness --check-config
PYTHONPATH=src python3 -m vera_harness --monitor
```

`--monitor` runs until interrupted. Use `--max-poll-cycles N` to stop after a
bounded number of polling cycles, and `--poll-interval-seconds N` to control the
sleep between cycles. Each cycle prints an audit-friendly log that includes the
task id, Telegram chat/update/message ids, workspace path, Codex session/turn
ids when available, status messages sent to Telegram, and final outcome.

`--poll-once` remains available for intake-only diagnostics. It performs one
`getUpdates` call, queues accepted tasks, sends `Accepted: queued.`, and exits
without launching Codex.

## Optional Live Smoke

Use the live smoke command only after `--check-config` succeeds and a local
Codex app-server command is available. It polls Telegram once, runs any accepted
tasks through the configured Codex runtime, sends final Telegram statuses, and
then exits.

```sh
export VERA_TELEGRAM_BOT_TOKEN="..."
export VERA_CODEX_APP_SERVER_COMMAND="codex app-server"

PYTHONPATH=src python3 -m vera_harness --live-smoke
```

No secret values belong in the repository. Keep bot tokens in the environment
or another local secret manager, and keep `.vera/telegram_config.json` limited
to non-secret allow-list and polling settings.

Unauthorized chats/users are ignored by default. Set
`telegram.unauthorized_response` in the local Telegram config file to send a
short rejection response instead.

Telegram offset and task lifecycle state are persisted locally at
`telegram.state_path`. The state file stores update ids and task metadata such
as chat id, user id, message id, and lifecycle status. It does not persist raw
Telegram message text or usernames.

## Configuration

Telegram non-secret connectivity settings are read from a JSON config file.
The default local path is `./.vera/telegram_config.json`, which is ignored by
git. Use `--telegram-config /path/to/telegram.json` or
`VERA_TELEGRAM_CONFIG_PATH=/path/to/telegram.json` to override it. The
committed `config/telegram.example.json` file is a template only and must not
contain a bot token.

Only the bot token remains secret-backed:

```sh
export VERA_TELEGRAM_BOT_TOKEN="..."
```

Dry-run mode does not require secrets. Telegram polling validates the bot token
and at least one configured allow-list.

Recommended Telegram config:

```json
{
  "telegram": {
    "allowed_chat_ids": [12345],
    "allowed_user_ids": [67890],
    "api_base_url": "https://api.telegram.org",
    "poll_timeout_seconds": 30,
    "request_timeout_seconds": 35,
    "state_path": "./.vera/telegram_state.json",
    "unauthorized_response": null
  }
}
```

For migration, the old non-secret Telegram environment variables are still
recognized when no Telegram config file exists. When a config file is present,
its Telegram values take precedence over those env vars. Do not put
`bot_token`, `telegram_bot_token`, or `VERA_TELEGRAM_BOT_TOKEN` in config; the
loader rejects secret fields.

`--check-config` validates the complete live configuration without network
calls and prints only a redacted token marker.

Other harness and Codex settings remain environment-backed:

| Variable | Required for dry run | Description |
| --- | --- | --- |
| `VERA_TELEGRAM_BOT_TOKEN` | No | Telegram bot token. Required for `--monitor`, `--live-smoke`, `--poll-once`, and `--check-config`. |
| `VERA_TELEGRAM_CONFIG_PATH` | No | Optional path to Telegram non-secret JSON config. Equivalent to `--telegram-config`. |
| `VERA_RUN_STATE_PATH` | No | Local JSON file for minimal orchestration run state. Defaults to `./.vera/run_state.json`. |
| `VERA_WORKSPACE_ROOT` | No | Root directory for per-task workspaces. Defaults to `./.vera/workspaces`. |
| `VERA_WORKSPACE_BOOTSTRAP_TIMEOUT_SECONDS` | No | Timeout for each configured workspace clone/bootstrap command. Defaults to `300`. |
| `VERA_WORKSPACE_RETENTION_POLICY` | No | Retention policy recorded in workspace metadata: `retain`, `cleanup_on_success`, or `cleanup_on_completion`. Defaults to `retain`. |
| `VERA_CODEX_APP_SERVER_COMMAND` | No | Shell-style command used to launch the Codex app server. Defaults to `codex app-server`. |
| `VERA_MAX_TURNS` | No | Maximum Codex turns per harness run. Defaults to `20`. |
| `VERA_MAX_RETRIES` | No | Retry budget for failed, cancelled, or timed-out Codex turns. Defaults to `1`. |
| `VERA_TURN_TIMEOUT_SECONDS` | No | Timeout for one Codex turn. Defaults to `300`. |
| `VERA_RUN_TIMEOUT_SECONDS` | No | Timeout for the whole harness run. Defaults to `1800`. |
| `VERA_APPROVAL_POLICY` | No | Planned Codex approval policy: `untrusted`, `on-request`, `on-failure`, or `never`. Defaults to `on-request`. |
| `VERA_SANDBOX_MODE` | No | Planned Codex sandbox mode: `read-only`, `workspace-write`, or `danger-full-access`. Defaults to `read-only`. |
| `VERA_CODEX_APPROVAL_DECISION` | No | Optional unattended response for command/file approval prompts: `accept`, `acceptForSession`, `decline`, or `cancel`. Empty by default, which returns an explicit blocked outcome. |
| `VERA_CODEX_AUTO_INPUT_RESPONSE` | No | Optional unattended text answer for app-server `request_user_input` prompts. Empty by default, which returns an explicit blocked outcome. |
| `VERA_REPO_CLONE_COMMAND` | No | Optional shell-style command executed in a newly prepared workspace before the bootstrap command. Not executed in dry run. |
| `VERA_REPO_BOOTSTRAP_COMMAND` | No | Optional shell-style command executed in a newly prepared workspace after the clone command. Not executed in dry run. |

Do not commit actual secret values. Documentation should name variables only.

## Troubleshooting

- Missing Telegram auth: `VERA_TELEGRAM_BOT_TOKEN is required for live runs`
  means `--monitor`, `--poll-once`, `--check-config`, or `--live-smoke` was run
  without a bot token in the environment.
- Missing allowed chat config:
  `telegram.allowed_chat_ids or telegram.allowed_user_ids is required for live runs`
  means the local Telegram config or environment lacks an allow-list. Add the
  authorized chat and/or user ids to `.vera/telegram_config.json`.
- Workspace bootstrap failure: the loop reports `final_status: failed` and the
  workspace metadata records `bootstrap_status`, command output, return code,
  and error text. Fix `VERA_REPO_CLONE_COMMAND`, `VERA_REPO_BOOTSTRAP_COMMAND`,
  or the workspace contents, then send a new Telegram task.
- Codex startup failure: the task log reports `final_status: failed` with a
  reason such as `failed to launch Codex app-server`. Check
  `VERA_CODEX_APP_SERVER_COMMAND`, local Codex installation, and PATH.
- Approval required: the loop reports `final_status: approval_required` and
  Telegram receives a blocked status. Set a deliberate
  `VERA_CODEX_APPROVAL_DECISION` only when unattended approval is safe for the
  configured environment.
- Timeout: the loop reports `final_status: failed` after configured retries if a
  Codex turn times out. Tune `VERA_TURN_TIMEOUT_SECONDS`,
  `VERA_RUN_TIMEOUT_SECONDS`, or investigate the Codex app-server logs.

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
  policy, bootstrap diagnostics, persistent run state, task events, and Codex
  turn results;
- module boundaries for config, Telegram intake, Telegram state persistence,
  workspace management, Codex runtime planning/execution, prompt/policy, and
  orchestration;
- Telegram Bot API long polling with injectable transport for tests;
- authorization by configured chat and/or user ids;
- duplicate update suppression across restarts through local offset
  persistence;
- concise Telegram status replies for accepted, rejected, started, completed,
  blocked, and failed task states;
- deterministic isolated workspace lifecycle with explicit reuse/fresh/existing
  policies, metadata recording, root escape protection, bounded bootstrap
  command execution, and guarded cleanup hooks;
- dry-run CLI output that runs prompt construction, workspace selection, fake
  Codex runtime execution, final decision mapping, and event emission locally;
- Codex app-server launch over stdio JSON-RPC;
- `initialize`, `thread/start`, and `turn/start` request flow;
- structured runtime events for server notifications, approval-required,
  input-required, completion, failure, cancellation, timeout, and process exit;
- fail-closed unattended behavior unless explicit auto-response config is set;
- orchestration loop over normalized tasks with workspace preparation, policy
  prompt synthesis, up-to-max-turn Codex execution, continuation/completion/
  retry/block/failure decisions, structured task events, and minimal JSON run
  state that prevents duplicate active task runs across restarts.
- a production Telegram monitor loop that drains accepted tasks into the Codex
  runtime and reports final status back to Telegram;
- a fake end-to-end smoke command that covers Telegram update -> task ->
  workspace -> Codex runtime -> Telegram status response without live services;
- an optional one-cycle live smoke command for configured Telegram and local
  Codex app-server environments.

Not implemented in this ticket:

- Telegram webhook handling;
- concurrent multi-worker scheduling for multiple long-running tasks.
