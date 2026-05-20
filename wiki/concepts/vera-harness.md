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
- **Policy prompt:** encodes Herald's role as a representative of the user,
  including evidence-based reasoning, minimal footprint, reversibility, and
  transparency about limits.
- **Workspace management:** resolves one local workspace per task so Codex work
  can be isolated and reversible by default.
- **Codex runtime execution:** launches the configured Codex app-server command
  inside the task workspace, initializes the JSON-RPC session, starts a thread
  with configured approval and sandbox policy, and starts task turns with the
  synthesized prompt.
- **Runtime event stream:** converts app-server notifications and server
  requests into harness-level events so the orchestrator and Telegram status
  layer can report completion, failure, cancellation, approval-required,
  input-required, and timeout outcomes.
- **Orchestration:** composes intake, policy, workspace, and runtime planning
  into a harness run.

## Durable Constraints

- Dry-run operation must remain available without live Telegram or Codex
  dependencies.
- Live modes should validate secrets and allow-list settings before accepting
  external tasks.
- Telegram transport details should stay isolated from Codex and workspace
  planning.
- The harness should collect and persist only the task context and lifecycle
  metadata needed for the run.
- Telegram replies should be concise and action-oriented: accepted, rejected,
  started, completed, and blocked states should be obvious without exposing
  more context than the chat already supplied.
- Risky or irreversible behavior belongs behind explicit approval and sandbox
  settings.
- The default runtime posture should prefer reversible behavior; broader
  workspace or approval access must be explicitly configured.
- Unanswered questions, blockers, and runtime limits should be surfaced rather
  than hidden.
- Unattended Codex runs should fail closed on approval or input requests unless
  an explicit auto-response policy is configured.

## Source

- [README](../../README.md)
- [Project concept document](../../docs/concept.md)
