# Vera Harness

The Vera harness is the local agent runtime that turns an authorized Telegram
task into a regulated Codex run inside an isolated workspace.

## Concept

The harness keeps the boundary between user intake, policy, workspaces, and
runtime execution explicit:

- **Telegram intake:** long-polls authorized Telegram sources, rejects or
  ignores unauthorized sources according to configuration, and converts only
  the minimum task context into a domain model.
- **Telegram state:** persists processed update ids and compact task lifecycle
  metadata so restarts do not duplicate accepted work while avoiding raw chat
  history storage.
- **Telegram configuration:** keeps non-secret connectivity settings in a
  local JSON config file while leaving the bot token in an environment-backed
  secret path.
- **Policy prompt:** encodes Herald's role as a faithful representative,
  The Place's coordination protocols, and Vera's trust constraints, including
  onion peeling, interest surfacing, face-saving, minimal disclosure,
  non-sycophancy, reversibility, evidence, uncertainty, and explicit blockers.
- **Workspace management:** resolves one local workspace per task, validates
  that the path cannot escape the configured workspace root, records compact
  workspace metadata, and exposes explicit reuse, fresh-create, bootstrap, and
  cleanup behavior.
- **Codex runtime execution:** launches the configured Codex app-server command
  inside the task workspace, initializes the JSON-RPC session, starts a thread
  with configured approval and sandbox policy, and starts task turns with the
  synthesized prompt.
- **Runtime event stream:** converts app-server notifications and server
  requests into harness-level events so the orchestrator and Telegram status
  layer can report completion, failure, cancellation, approval-required,
  input-required, and timeout outcomes.
- **Orchestration:** accepts normalized Telegram or dry-run tasks, creates or
  reuses isolated workspaces, builds policy prompts, runs Codex up to the
  configured turn and retry budgets, maps each turn to continue/complete/retry/
  block/fail decisions, emits task lifecycle events, and persists minimal run
  state so active tasks are not duplicated after restart.
- **Operational loop:** drains accepted Telegram tasks into the orchestration
  loop, sends started and terminal Telegram status replies, and emits
  audit-suitable logs with task ids, Telegram ids, workspace paths, Codex
  session/turn ids when available, and final outcomes.
- **Console observability:** projects run state, structured events, focus
  selection, last-turn summaries, current plan, redacted log stream, and budget
  telemetry into a shared state provider used by both terminal and local web
  consoles. The terminal console is operational by default for live local use:
  it owns a managed Telegram monitor loop unless explicitly launched in
  view-only mode, and it reports monitor startup/configuration failures through
  the same event stream it renders.
- **Smoke modes:** provides a no-secret fake Telegram-to-Codex path for local
  validation and a one-cycle live smoke path for configured Telegram bot plus
  local Codex app-server environments.

## Durable Constraints

- Dry-run operation must remain available without live Telegram or Codex
  dependencies.
- Live modes should validate secrets and allow-list settings before accepting
  external tasks.
- Telegram bot tokens must not be written to committed config, local templates,
  logs, or config-check output.
- Non-secret Telegram connectivity settings should prefer the local config file
  interface over environment variables; env compatibility is only a migration
  fallback when no config file is present.
- Telegram transport details should stay isolated from Codex and workspace
  planning.
- The harness should collect and persist only the task context and lifecycle
  metadata needed for the run.
- Workspace identity should come from the stable Telegram task/run id and map
  to a deterministic safe path segment under the configured workspace root.
- Existing workspace reuse, fresh creation, and require-existing continuation
  should be explicit policy choices rather than implicit side effects.
- Bootstrap commands may prepare a workspace, but they must run inside that
  workspace, be timeout-bound, and capture stdout/stderr for diagnostics.
- Cleanup must be explicit and constrained to paths that remain inside the
  configured workspace root after resolution.
- Telegram replies should be concise and action-oriented: accepted, rejected,
  started, completed, blocked, and failed states should be obvious without
  exposing more context than the chat already supplied.
- Operational logs should preserve enough IDs to debug and later audit a run
  while avoiding raw Telegram message text and unnecessary user context.
- Console events should use a small structured schema rather than ad hoc log
  parsing, and should redact secrets plus raw private source-channel bodies by
  default.
- The default terminal console path should run against the same run-state and
  event-log files as the monitor loop it supervises; attaching to an existing
  monitor should require an explicit viewer-only choice.
- Budget telemetry should display available rate-limit, usage, and threshold
  data when configured while clearly distinguishing unknown and unavailable
  states when credentials or snapshots are absent.
- Orchestration run state should record task ids, run ids, workspace paths,
  turn counts, status, and compact diagnostics, but not raw chat history or
  broader user context.
- Risky or irreversible behavior belongs behind explicit approval and sandbox
  settings.
- The default runtime posture should prefer reversible behavior; broader
  workspace or approval access must be explicitly configured.
- Unanswered questions, blockers, and runtime limits should be surfaced rather
  than hidden.
- Unattended Codex runs should fail closed on approval or input requests unless
  an explicit auto-response policy is configured.
- Codex turns must produce an explicit Vera task status marker so the harness
  can distinguish completion from safe continuation, blockers, and failures.

## Source

- [README](../../README.md)
- [Project concept document](../../docs/concept.md)
