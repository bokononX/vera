# Vera Harness

The Vera harness is the local agent runtime that turns authorized Telegram
messages into regulated Codex work inside managed local workspaces.

## Concept

The harness keeps the boundary between user intake, policy, workspaces, and
runtime execution explicit:

- **Telegram intake:** long-polls authorized Telegram sources, rejects or
  ignores unauthorized sources according to configuration, and converts only
  the minimum task context into a domain model.
- **Telegram state:** persists processed update ids and compact task lifecycle
  metadata so restarts do not duplicate accepted work while avoiding raw chat
  history storage.
- **Chat session state:** maps an authorized Telegram chat/user pair to a
  stable Vera session id, managed workspace, Codex thread id, last turn id, last
  known status, pending prompt, and last assistant response so monitor restarts
  can resume or safely recreate the conversational session without preserving
  raw inbound chat history.
- **Assistant identity profile:** defines the user-facing assistant separately
  from the human owner. The profile carries the assistant name, mission, values,
  communication principles, product-truth boundaries, transparency rules,
  owner relationship, proactivity guidance, and owner-specific treatment rules.
  It can be configured locally or refined through an owner-confirmed Telegram
  interview before Codex sees the chat turn.
- **Owner identity/style profile:** intercepts explicit identity interview,
  inspection, and correction messages in persistent Telegram chat mode before
  Codex. The interview asks short progressive questions, requires confirmation
  before durable writes, stores confirmed profile entries separately from raw
  interview transcript, and injects confirmed guidance into future prompts as
  revisable practical context rather than personality labeling.
- **Telegram configuration:** keeps non-secret connectivity settings in a
  local JSON config file while leaving the bot token in an environment-backed
  secret path.
- **Owner identity and profile:** optionally records one primary owner in the
  same non-secret local config, keyed by stable Telegram `user_id` with display
  labels, values, priorities, communication style, escalation boundaries, and
  an optional refreshable local/wiki profile file.
- **iMessage contact metadata ingest:** optionally reads local macOS Messages
  contact metadata in read-only mode to discover people the owner texts with.
  The path is disabled by default, requires explicit local configuration and
  macOS Full Disk Access, and records only contact/handle candidates for later
  owner clarification.
- **Policy prompt:** starts from the active assistant identity so the Telegram
  assistant introduces and conducts itself as Vera or the configured local
  name, not as Codex. It then encodes Herald's role as a faithful
  representative, The Place's coordination protocols, and Vera's trust
  constraints, including onion peeling, interest surfacing, face-saving,
  minimal disclosure, non-sycophancy, reversibility, evidence, uncertainty, and
  explicit blockers. Owner sessions receive an additional relationship block;
  authorized non-owner sessions do not.
- **Workspace management:** resolves local workspaces for either legacy tasks
  or persistent chat sessions, validates that paths cannot escape the configured
  workspace root, records compact workspace metadata, and exposes explicit
  reuse, fresh-create, bootstrap, and cleanup behavior.
- **Codex runtime execution:** launches the configured Codex app-server command
  inside the managed workspace after readiness resolves the executable path,
  initializes the JSON-RPC session, starts or resumes a thread with configured
  approval and sandbox policy, and starts turns with either the synthesized
  initial prompt or a follow-up Telegram message.
- **Runtime event stream:** converts app-server notifications and server
  requests into harness-level events so the orchestrator and Telegram status
  layer can report completion, failure, cancellation, approval-required,
  input-required, and timeout outcomes. User-facing Codex replies come from
  completed `agentMessage` thread items when available, with streamed
  `item/agentMessage/delta` text used only as a fallback.
- **Orchestration:** accepts normalized Telegram or dry-run tasks, creates or
  reuses isolated workspaces, builds policy prompts, runs Codex up to the
  configured turn and retry budgets, maps each turn to continue/complete/retry/
  block/fail decisions, emits task lifecycle events, and persists minimal run
  state so active tasks are not duplicated after restart.
- **Operational loop:** drains accepted Telegram messages into persistent chat
  sessions for live monitor/TUI operation, sends the final assistant response or
  an explicit blocked/failed prompt back to Telegram, and emits audit-suitable
  logs with session ids, Telegram ids, workspace paths, Codex thread/turn ids
  when available, and final outcomes. The legacy per-task loop remains
  available for dry-run, fake smoke, and intake diagnostics.
- **Console observability:** projects run state, structured events, focus
  selection, last-turn summaries, current plan, redacted log stream, and budget
  telemetry into a shared state provider used by both terminal and local web
  consoles. The terminal console is operational by default for live local use:
  it owns a managed Telegram monitor loop unless explicitly launched in
  view-only mode, and it reports monitor startup/configuration failures through
  the same event stream it renders. Console agent rows include the active
  assistant identity name and redacted session identity label while keeping raw
  owner profile content redacted by default.
- **Smoke modes:** provides a no-secret fake Telegram-to-Codex path for local
  validation and a one-cycle live smoke path for configured Telegram bot plus
  local Codex app-server environments.

## Durable Constraints

- Dry-run operation must remain available without live Telegram or Codex
  dependencies.
- Live modes should validate secrets and allow-list settings before accepting
  external tasks.
- Live modes should validate the configured Codex app-server executable before
  accepting external tasks, and readiness diagnostics should name the missing
  command/path without dumping secret-bearing environment details.
- Telegram bot tokens must not be written to committed config, local templates,
  logs, or config-check output.
- Non-secret Telegram connectivity settings should prefer the local config file
  interface over environment variables; env compatibility is only a migration
  fallback when no config file is present.
- Assistant identity is distinct from owner identity: it describes the
  configured assistant's user-facing name, mission, values, style, boundaries,
  and runtime-transparency language, while owner identity describes the human
  user's preferences and memory.
- Assistant identity must preserve product truth. It should not claim human,
  sentient, or independent status, and should explain Codex/OpenAI as the
  runtime/tooling layer when directly asked or operationally relevant.
- Initial and follow-up chat prompts should include the active assistant
  identity before user text so the default Codex self-description cannot become
  the normal Telegram identity.
- Owner identity is distinct from the Telegram allow-list: matching uses stable
  Telegram `user_id`, and owner-specific prompt behavior must not apply to
  other authorized users.
- Owner profile facts are non-secret but personal; they may be loaded from
  local config or a refreshable local/wiki file, should be bounded before
  prompt insertion, and should be redacted from console summaries by default.
- Owner authority is not an approval override. Unsafe, irreversible,
  authority-sensitive, or high-stakes actions still require the configured
  approval, sandbox, and escalation posture.
- Telegram transport details should stay isolated from Codex and workspace
  planning.
- iMessage contact ingest must stay metadata-only: it may read local Messages
  handle/chat identity tables in read-only mode, but must not read, log,
  summarize, embed, persist, or send message bodies.
- Discovered iMessage contacts are unresolved people candidates, not
  relationship facts. Vera must ask the owner who the person is before using
  the candidate as durable social context.
- The harness should collect and persist only the task or chat-session metadata
  needed for restart/recovery.
- Default local runtime state, event logs, Telegram config/state, identity
  files, and managed workspaces belong under `./runtime`; legacy `./.vera`
  state remains an explicit override/migration concern rather than an automatic
  fallback.
- Workspace identity should come from either the stable Telegram task/run id or
  stable Telegram chat-session id and map to a deterministic safe path segment
  under the configured workspace root.
- Existing workspace reuse, fresh creation, and require-existing continuation
  should be explicit policy choices rather than implicit side effects.
- Bootstrap commands may prepare a workspace, but they must run inside that
  workspace, be timeout-bound, and capture stdout/stderr for diagnostics.
- Cleanup must be explicit and constrained to paths that remain inside the
  configured workspace root after resolution.
- Telegram replies should be concise and action-oriented. Live chat mode should
  make the assistant response the primary reply and reserve blocked/failed
  prompts for cases where Codex cannot continue without user action.
- Operational logs should preserve enough IDs to debug and later audit a run
  while avoiding raw Telegram message text and unnecessary user context.
- Persistent chat-session state may record the last assistant response and
  pending prompt, but it should not record raw inbound Telegram message text.
- Identity/style profile entries should be confirmed before persistence and
  should carry source, timestamp, confidence, and an explicit correction path.
- Raw identity interview transcript belongs in a separate interview state file;
  durable profile entries should contain only the confirmed summary facts used
  for future prompt guidance.
- Owner profile guidance should remain calibrated and revisable: it must not be
  treated as fixed personality truth, and explicit corrections should override
  older profile entries.
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
- Legacy task turns must produce an explicit Vera task status marker so the
  harness can distinguish completion from safe continuation, blockers, and
  failures; live chat turns derive the Telegram reply from app-server assistant
  output and pending request events.

## Source

- [README](../../README.md)
- [Project concept document](../../docs/concept.md)
