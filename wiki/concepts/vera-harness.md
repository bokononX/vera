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

## Durable Constraints

- Dry-run operation must remain available without live Telegram or Codex
  dependencies.
- Live modes should validate secrets and allow-list settings before accepting
  external tasks.
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
  started, completed, and blocked states should be obvious without exposing
  more context than the chat already supplied.
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
