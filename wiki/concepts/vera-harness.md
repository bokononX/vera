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
- **Policy prompt:** encodes Herald's role as a representative of the user,
  including evidence-based reasoning, minimal footprint, reversibility, and
  transparency about limits.
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
- **Orchestration:** composes intake, policy, workspace, and runtime planning
  into a harness run.

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
