# Vera Harness

This repository contains the Python scaffold for the Vera agent harness. It can
load configuration, synthesize the Herald/The Place/Vera policy prompt, resolve
managed workspaces, poll Telegram through the Bot API, queue authorized
Telegram messages, and pass live chat messages into a persistent Codex app-server
thread.

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
polls Telegram, queues authorized text messages, prepares or reuses a dedicated
workspace for each Telegram chat/user session, launches a long-lived Codex
app-server process, starts or resumes the Codex thread for that session, and
sends the assistant's final response back to Telegram.

```sh
mkdir -p .vera
cp config/telegram.example.json .vera/telegram_config.json
# Edit .vera/telegram_config.json with your allowed Telegram chat/user ids.
export VERA_TELEGRAM_BOT_TOKEN="..."
export VERA_CODEX_APP_SERVER_COMMAND="$(command -v codex) app-server"

PYTHONPATH=src python3 -m vera_harness --check-config
PYTHONPATH=src python3 -m vera_harness --monitor
```

`VERA_CODEX_APP_SERVER_COMMAND` defaults to `codex app-server`. For live local
runs, set it to the exact Codex executable that the monitor process can use.
An absolute path from `command -v codex` is preferred when launching Vera from a
venv, process manager, IDE, or another environment with a narrower `PATH`.
Relative and `~` executable paths are resolved during readiness checks before
the monitor changes into task workspaces.

`--monitor` runs the same headless loop used by the default TUI console and runs
until interrupted. Use `--max-poll-cycles N` to stop after a bounded number of
polling cycles, and `--poll-interval-seconds N` to control the sleep between
cycles. Each cycle prints an audit-friendly chat log that includes the persistent
session id, Telegram chat/update/message ids, workspace path, Codex thread/turn
ids when available, the response sent to Telegram, and final Codex status.

In chat mode the first accepted message receives a natural assistant response,
not a `Started`/`Completed` lifecycle reply. Follow-up messages from the same
Telegram chat/user pair reuse the same local session id, workspace, app-server
process, and Codex thread when the process is still active. On restart, Vera
loads `VERA_CHAT_SESSION_STATE_PATH` and asks the app-server to resume the last
known thread; if resume is unavailable, it safely starts a new thread while
preserving Telegram authorization and local session mapping state.

`--poll-once` remains available for intake-only diagnostics. It performs one
`getUpdates` call, queues accepted tasks, sends `Accepted: queued.`, and exits
without launching Codex.

## Vera Agent Console

The console has two local surfaces backed by the same observability provider:

```sh
PYTHONPATH=src python3 -m vera_harness --console-tui
PYTHONPATH=src python3 -m vera_harness --console-gui --console-port 8765
```

The TUI opens in the current terminal and, by default, starts the Telegram
chat monitor loop in the same process. Exiting the TUI requests the managed
monitor loop to stop. Startup/configuration failures are written into the
console event stream so the terminal shows a local error state instead of an
empty viewer.

Use view-only mode to attach to run state and events from an already-running
monitor without starting another poller:

```sh
PYTHONPATH=src python3 -m vera_harness --console-tui --console-view-only
```

The GUI serves a local web app and prints the listening URL. The console
surfaces read:

- `VERA_RUN_STATE_PATH` for active, completed, blocked, and failed runs;
- `VERA_CHAT_SESSION_STATE_PATH` for Telegram chat/user to workspace/thread
  mappings;
- `VERA_EVENT_LOG_PATH` for structured task, Codex, source-channel, and error
  events;
- optional budget telemetry from `VERA_BUDGET_SNAPSHOT_PATH` and budget
  threshold environment variables.

For local smoke checks without Telegram, Codex, or secrets:

```sh
PYTHONPATH=src python3 -m vera_harness --console-tui --console-fake-state --console-smoke
PYTHONPATH=src python3 -m vera_harness --console-gui --console-fake-state --console-smoke --console-port 0
```

The fake state includes active and completed agents, a current plan, redacted
Telegram/source data, redacted secret fixtures, and unavailable budget telemetry.

### Console Layout

The top budget bar shows rate-limit, usage, and configured threshold state.
Below it:

- **Available agents** lists task/run status, source channel, task id,
  workspace, current turn, age, active assistant identity name, redacted
  session identity label, and token/cost usage when events provide it.
- **Last turn and current plan** shows the focused agent's last decision or
  completed turn, objective, and plan entries marked as user-confirmed,
  agent-generated, or blocker-driven.
- **Agent log stream** shows structured status, Codex/runtime, source-channel,
  tool-like, and error events. Event payloads are redacted by default.

The TUI supports focus changes with up/down or `j`/`k`, pause/resume with `p`,
follow toggle with `f`, and page scrolling with page up/down. The GUI supports
click-to-focus agent selection, pause/follow controls, and event filtering.

### Budget States

Budget telemetry is intentionally explicit when data is absent:

- `available`: a local budget/rate-limit snapshot or threshold value is
  configured and readable.
- `unknown`: OpenAI API/admin credentials appear to be configured, but no local
  snapshot or response-header capture has been written yet.
- `unavailable`: credentials and snapshots are absent, so the console cannot
  know current rate-limit or usage state.

An optional budget snapshot is a local JSON file:

```json
{
  "rate_limits": {
    "remaining_requests": 100,
    "remaining_tokens": 50000,
    "reset_requests_at": "2026-05-20T18:00:00Z",
    "reset_tokens_at": "2026-05-20T18:05:00Z"
  },
  "usage": {
    "daily_usd": 1.25,
    "weekly_usd": 9.5,
    "monthly_usd": 31.0,
    "monthly_tokens": 10000
  }
}
```

No OpenAI or Telegram secret values belong in snapshots, event logs, or docs.

## Optional Live Smoke

Use the live smoke command only after `--check-config` succeeds and a local
Codex app-server command is available. It polls Telegram once, runs any accepted
messages through the configured persistent Codex chat runtime, sends final
Telegram chat responses, and then exits.

```sh
export VERA_TELEGRAM_BOT_TOKEN="..."
export VERA_CODEX_APP_SERVER_COMMAND="$(command -v codex) app-server"

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

Persistent chat session state is stored at `VERA_CHAT_SESSION_STATE_PATH`
(`./.vera/chat_sessions.json` by default). It records the Vera session id,
Telegram chat/user mapping, workspace path, Codex thread id, last turn id, last
known status, pending prompt, and last assistant response needed for local
restart/recovery. It does not store raw inbound Telegram message text.

## User Memory Ingest

The harness can turn a transcript or normalized Telegram JSON file into
reviewable Herald user-memory wiki proposals:

```sh
PYTHONPATH=src python3 -m vera_harness --ingest-user-memory \
  --conversation-file tests/fixtures/sample_conversation.txt \
  --memory-root ./.vera/sample-memory \
  --memory-user-id user-example \
  --captured-at 2026-05-21T00:00:00Z
```

Dry-run mode is the default. It prints the proposed page creates/updates,
classification, confidence, review queue changes, index rebuild, and log entry
without mutating files. Add `--apply-memory-ingest` to write the corpus.

The default source-retention policy is `hash_only`: the ingest writes
`raw/manifest.jsonl` plus non-raw redaction metadata and does not persist raw
conversation text. Use `--memory-source-retention store` only when the source
policy explicitly allows raw transcript storage.

## User Memory Prompt Retrieval

Set `VERA_USER_MEMORY_ROOT` or `owner.user_memory_root` in the local Telegram
config to point at one user-memory corpus. When a Telegram task is built for
Codex, Vera reads that corpus, retrieves a bounded set of task-relevant wiki
pages, filters private/restricted/secret pages through prompt-visibility gates,
and adds a compact `User Memory Context` block to the prompt. Ordinary Codex
prompts do not receive private, restricted, or secret pages by default; callers
must explicitly opt into those retrieval classes in code.

The memory block includes page paths, source ids, confidence, sensitivity, and
caveats for corrections, contradictions, open questions, and `confirm_first`
memory. It records the memory page ids/paths used in JSON run state so each task
run can be audited without dumping the full wiki into every prompt.

## User Memory Controls

Owner Telegram chat messages are checked for memory controls before normal
Codex chat turns. Supported controls are:

- `what do you remember about X?` lists matching wiki-memory claims with page
  path, memory state, confidence, sensitivity, prompt visibility, review status,
  and source metadata.
- `correct X to Y` records a correction page, updates the active claim summary
  used by retrieval, and links the older page to the correction for auditability.
- `forget X` tombstones the matching synthesized memory, redacts source
  references according to retention policy, rebuilds `index.md`, and appends a
  deletion audit entry without restating private claim text.
- `mark X as private`, `mark X as restricted`, or `mark this as sensitive`
  changes sensitivity and prompt visibility. `this` targets the most recent
  memory-control result in the same Telegram chat session.
- `show recent memory updates` returns recent `log.md` audit entries.

Use `/memory help`, `/memory show X`, `/memory search X`, `/memory correct X to
Y`, `/memory forget X`, and `/memory recent` as command-style aliases.

Assistant identity is handled before owner identity and before Codex in
persistent chat mode. The active assistant has a first-class profile with a
name, short self-description, mission, values, communication principles,
boundaries, transparency rules, owner relationship, proactivity guidance, and
owner-specific treatment rules. That profile is injected into initial and
follow-up Codex prompts so the assistant introduces itself as Vera or the
configured local name rather than as Codex.

The default assistant identity is Vera, a personal assistant/minime focused on
memory, values-aware conversation, thoughtful coordination, and helping the
owner think clearly. It is not the same thing as the human owner profile.
Assistant identity describes the user-facing assistant; owner identity records
the human owner's preferences and memory. The prompt always preserves product
truth: the assistant must not claim to be human, sentient, or independent, and
can explain that Codex/OpenAI tooling is the runtime layer when asked or when
operationally relevant.

The owner can ask `who are you?` to receive a concise assistant introduction,
or `are you Codex?` to receive the same identity plus runtime transparency. The
owner can inspect the current assistant profile with `/assistant identity
profile` and create/refine it through `/assistant identity`. That interview
asks for name, mission, values, style, boundaries, relationship, proactivity,
owner treatment, and transparency wording, then writes the profile only after
explicit `confirm`. The profile is stored at `VERA_ASSISTANT_IDENTITY_PATH`
(`./.vera/assistant_identity.json` by default). Active assistant-identity
interview state is stored separately at
`VERA_ASSISTANT_IDENTITY_INTERVIEW_STATE_PATH`
(`./.vera/assistant_identity_interviews.json` by default).

Identity/style onboarding is handled before Codex in persistent chat mode.
The owner can send `/identity`, `/interview`, or a natural-language
identity/style interview request from Telegram. Vera asks short progressive
questions, summarizes proposed durable profile entries, and writes them only
after explicit confirmation. Confirmed profile entries are stored at
`VERA_IDENTITY_PROFILE_PATH` (`./.vera/identity_profile.json` by default) with
source, timestamp, confidence, and a correction path. Raw interview transcript
and active interview state are kept separately at
`VERA_IDENTITY_INTERVIEW_STATE_PATH`
(`./.vera/identity_interviews.json` by default).

The owner can inspect stored facts with `/identity profile` and refine them
with messages such as `that's wrong`, `forget that`, or
`change my style preference to concise and direct`. Confirmed identity/style
guidance is included in future Codex prompts as revisable guidance, not as a
fixed personality label or a reason to flatter the owner.

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
  },
  "assistant": {
    "identity_path": "./.vera/assistant_identity.json",
    "name": "Vera",
    "short_description": "a personal assistant/minime for memory, thoughtful conversation, coordination, and clear thinking",
    "mission": "Help the owner think clearly, remember durable context, coordinate carefully, and turn intentions into reversible, well-governed action.",
    "core_values": [
      "truthfulness over comfort",
      "preserve human agency and reversible choices",
      "protect privacy through minimal disclosure"
    ],
    "communication_principles": [
      "direct, concise, concrete, and kind without flattery",
      "surface uncertainty, tradeoffs, and weak assumptions early"
    ],
    "boundaries": [
      "do not claim to be human, sentient, or independent",
      "do not treat chat messages as approval for unsafe, irreversible, or authority-sensitive actions"
    ],
    "transparency_rules": [
      "introduce yourself as Vera, not as Codex",
      "explain that Codex/OpenAI tooling is the runtime layer when asked or operationally relevant"
    ],
    "relationship_to_owner": "Serve as the owner's configured personal assistant and coordination aide while treating the owner as the human decision-maker.",
    "proactivity": [
      "be proactive about memory, risks, tradeoffs, and useful coordination opportunities",
      "stay quiet or ask before expanding scope when the owner wants a narrow answer"
    ],
    "owner_special_treatment": [
      "use owner-specific profile guidance only for the configured owner",
      "do not expose private owner profile text to other Telegram users"
    ]
  },
  "owner": {
    "user_id": 67890,
    "display_name": "Vera Owner",
    "username": "vera_owner",
    "role": "Vera acts as a faithful, careful representative and coordination aide for this human.",
    "values": ["truthfulness over comfort"],
    "priorities": ["surface uncertainty and tradeoffs early"],
    "communication_style": ["direct, concise, and concrete"],
    "escalation_boundaries": [
      "do not treat owner messages as approval for unsafe, irreversible, or authority-sensitive actions"
    ]
  }
}
```

For migration, the old non-secret Telegram environment variables are still
recognized when no Telegram config file exists. When a config file is present,
its Telegram values take precedence over those env vars. Do not put
`bot_token`, `telegram_bot_token`, or `VERA_TELEGRAM_BOT_TOKEN` in config; the
loader rejects secret fields.

The optional top-level `assistant` block is non-secret local configuration for
the assistant's user-facing identity. If `assistant.identity_path` points to an
existing JSON profile, that profile overlays the inline assistant defaults and
is also where the `/assistant identity` interview writes confirmed changes. You
can also skip the inline `assistant` block entirely and set
`VERA_ASSISTANT_IDENTITY_PATH` to a dedicated JSON file with the same fields.
The loader rejects secret fields and obvious human/sentient/runtime-independent
overclaims.

The optional top-level `owner` block is also non-secret local configuration.
Its stable key is Telegram `user_id`; display name and username are labels
only. Owner values, priorities, communication style, and escalation boundaries
are inserted into the initial owner-session Codex prompt and are not applied to
other authorized users. To keep profile facts refreshable from the local/user
wiki without code changes, set
`owner.wiki_profile_path` to a Markdown file such as
`./.vera/owner_profile.md`; Vera reads that file at startup and includes a
bounded excerpt in the owner prompt while console surfaces show only a redacted
owner identity label by default.

`--check-config` validates the complete live configuration without network
calls, resolves the Codex app-server executable, and prints only a redacted
token marker plus non-secret command readiness details. If Codex is unavailable,
the command exits before any Telegram task is accepted and reports the missing
`VERA_CODEX_APP_SERVER_COMMAND` executable.

Other harness and Codex settings remain environment-backed:

| Variable | Required for dry run | Description |
| --- | --- | --- |
| `VERA_TELEGRAM_BOT_TOKEN` | No | Telegram bot token. Required for `--monitor`, `--live-smoke`, `--poll-once`, and `--check-config`. |
| `VERA_TELEGRAM_CONFIG_PATH` | No | Optional path to Telegram non-secret JSON config. Equivalent to `--telegram-config`. |
| `VERA_ASSISTANT_IDENTITY_PATH` | No | Local JSON file for the active assistant identity profile. Defaults to `./.vera/assistant_identity.json`. |
| `VERA_ASSISTANT_IDENTITY_INTERVIEW_STATE_PATH` | No | Local JSON file for assistant identity interview state and transcript. Defaults to `./.vera/assistant_identity_interviews.json`. |
| `VERA_RUN_STATE_PATH` | No | Local JSON file for minimal orchestration run state. Defaults to `./.vera/run_state.json`. |
| `VERA_CHAT_SESSION_STATE_PATH` | No | Local JSON file for persistent Telegram chat sessions and Codex thread ids. Defaults to `./.vera/chat_sessions.json`. |
| `VERA_IDENTITY_PROFILE_PATH` | No | Local JSON file for confirmed owner identity/style profile entries. Defaults to `./.vera/identity_profile.json`. |
| `VERA_IDENTITY_INTERVIEW_STATE_PATH` | No | Local JSON file for identity interview state and raw interview transcript. Defaults to `./.vera/identity_interviews.json`. |
| `VERA_EVENT_LOG_PATH` | No | Local JSONL file for structured console events. Defaults to `./.vera/events.jsonl`. |
| `VERA_BUDGET_SNAPSHOT_PATH` | No | Optional local JSON file with rate-limit and usage snapshots for the console budget bar. |
| `VERA_MONTHLY_BUDGET_USD` | No | Optional monthly budget threshold shown in the console. |
| `VERA_PROJECT_BUDGET_USD` | No | Optional project budget threshold shown in the console. |
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
- Codex readiness failure: `VERA_CODEX_APP_SERVER_COMMAND executable not found
  on PATH: codex` means Codex is not available to the current Vera process.
  Install Codex, start Vera from a shell with the right `PATH`, or set
  `VERA_CODEX_APP_SERVER_COMMAND` to an absolute executable path such as
  `/path/to/codex app-server`.
- Codex startup failure: the task log reports `final_status: failed` with a
  reason such as `failed to launch Codex app-server`. Re-run `--check-config`
  and check the configured Codex command plus local installation.
- Approval required: the loop reports `final_status: approval_required` and
  Telegram receives a blocked status. Set a deliberate
  `VERA_CODEX_APPROVAL_DECISION` only when unattended approval is safe for the
  configured environment.
- Timeout: the loop reports `final_status: failed` after configured retries if a
  Codex turn times out. Tune `VERA_TURN_TIMEOUT_SECONDS`,
  `VERA_RUN_TIMEOUT_SECONDS`, or investigate the Codex app-server logs.
- Empty console: confirm `VERA_RUN_STATE_PATH` points to the same run-state file
  used by the managed `--console-tui` loop or a separate `--monitor`. Use
  `--console-tui --console-view-only` when attaching to an existing monitor, or
  run a fake-state smoke command to validate the local surface.
- Missing console events: confirm `VERA_EVENT_LOG_PATH` is writable by the
  monitor process. The console can still show run state without events, but the
  log stream and last-turn summaries will be sparse.
- Budget shows `unknown` or `unavailable`: configure a local
  `VERA_BUDGET_SNAPSHOT_PATH` or threshold variables, or accept the fallback
  state when API/admin telemetry is intentionally absent.

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
- first-class assistant identity defaults, config/profile loading, Telegram
  self-introduction, assistant identity interview, prompt injection, and
  redacted console assistant-name display;
- domain models for Telegram tasks, harness runs, workspaces, workspace reuse
  policy, bootstrap diagnostics, persistent run state, task events, and Codex
  turn results;
- module boundaries for config, Telegram intake, Telegram state persistence,
  workspace management, Codex runtime planning/execution, prompt/policy,
  user-memory ingest/retrieval, and orchestration;
- Telegram Bot API long polling with injectable transport for tests;
- authorization by configured chat and/or user ids;
- duplicate update suppression across restarts through local offset
  persistence;
- concise Telegram status replies for legacy task mode, plus persistent chat
  responses for live monitor/TUI operation;
- deterministic isolated workspace lifecycle with explicit reuse/fresh/existing
  policies, metadata recording, root escape protection, bounded bootstrap
  command execution, and guarded cleanup hooks;
- dry-run CLI output that runs prompt construction, workspace selection, fake
  Codex runtime execution, final decision mapping, and event emission locally;
- Codex app-server launch over stdio JSON-RPC;
- `initialize`, `thread/start` or `thread/resume`, and `turn/start` request
  flow;
- structured runtime events for server notifications, approval-required,
  input-required, completion, failure, cancellation, timeout, and process exit;
- fail-closed unattended behavior unless explicit auto-response config is set;
- orchestration loop over normalized tasks with workspace preparation, policy
  prompt synthesis, up-to-max-turn Codex execution, continuation/completion/
  retry/block/failure decisions, structured task events, and minimal JSON run
  state that prevents duplicate active task runs across restarts.
- a production Telegram monitor loop that drains accepted messages into
  persistent chat sessions and reports assistant responses back to Telegram;
- a fake end-to-end smoke command that covers Telegram update -> task ->
  workspace -> Codex runtime -> Telegram status response without live services;
- an optional one-cycle live smoke command for configured Telegram and local
  Codex app-server environments.
- shared console observability projection, structured JSONL event log, terminal
  console, local web console, redaction safeguards, and budget fallback states.
- deterministic conversation/Telegram JSON to user-memory wiki ingest with
  dry-run review plans, hash-only source retention, page update/create,
  duplicate avoidance, contradiction review notes, index rebuilds, and log
  entries.
- bounded user-memory retrieval for Codex/Herald prompts with provenance,
  confidence, privacy filtering, caveats, confirmation constraints, and run-state
  audit refs.

Not implemented in this ticket:

- Telegram webhook handling;
- concurrent multi-worker scheduling for multiple long-running tasks.
