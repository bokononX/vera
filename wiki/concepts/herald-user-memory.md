# Herald User Memory

The canonical schema design is [docs/herald-user-memory-wiki-schema.md](../../docs/herald-user-memory-wiki-schema.md).

This page records the durable wiki-level shape of Herald user memory without
duplicating the full schema.

## Concept

Herald user memory is an LLM-authored wiki that functions as Herald's structured
model of one user. It adapts the LLM wiki pattern to user representation:

- **Raw sources** preserve source evidence and consent/sensitivity metadata.
- **Synthesized wiki pages** contain durable claims about concepts, values,
  preferences, projects, people, organizations, decisions, corrections, open
  questions, and observations.
- **Schema, index, log, and review queues** guide maintenance, retrieval,
  correction, deletion, contradiction handling, and stale-memory demotion.

## Durable Constraints

- Herald must represent the user faithfully without pretending to be the user.
- Raw sources and synthesized wiki pages must remain separate.
- Prompt retrieval must obey task relevance, confidence, sensitivity, and
  prompt-visibility gates.
- Confirmed, inferred, observed-pattern, correction, retracted, and
  open-question memory states must be distinguishable.
- Corrections and deletion requests outrank normal wiki maintenance.
- Memory must preserve evidence and uncertainty rather than drifting toward
  flattering summaries.

## Implemented Ingest Boundary

The first implementation provides a deterministic local ingest path for
conversation transcripts and normalized Telegram JSON. It extracts candidate
concepts, values, preferences, projects, people, organizations, decisions,
corrections, open questions, and observations; classifies them as confirmed,
inferred, observed-pattern, open-question, or correction memory; and produces a
human-readable dry-run plan before any files are changed.

Apply mode writes a user-memory corpus under a configured `memory/users/<id>`-
style root. It creates or updates synthesized wiki pages, rebuilds `index.md`,
appends `log.md`, writes `raw/manifest.jsonl`, and records unresolved
correction/contradiction notes in `review/contradictions.md`.

The default source-retention policy is `hash_only`: raw conversation text is
not persisted, while source ids, hashes, locators, confidence, and claim
summaries remain available for provenance and review.

## Implemented Prompt Retrieval Boundary

The harness can now use a configured user-memory corpus during Telegram-to-Codex
task prompting. `VERA_USER_MEMORY_ROOT` or `owner.user_memory_root` names the
corpus for the owner. Prompt construction reads the index and synthesized wiki
pages, ranks pages against the Telegram task text and inferred task scope, and
selects only a bounded set of relevant pages.

Retrieval keeps prompt packets compact and provenance-bearing. Prompt facts and
caveats include page paths, source ids, confidence, and sensitivity markers.
Corrections, open questions, contested pages, and `confirm_first` pages are
rendered as caveats or confirmation constraints rather than ordinary facts.
Restricted and secret memory are excluded by default; private memory is only
used for the configured owner path and must still be task-relevant.

Each task run records the selected memory page ids/paths in JSON run state, so
debugging can inspect what memory influenced the prompt without reconstructing
the full wiki disclosure.

## Source

- [Herald user memory wiki schema](../../docs/herald-user-memory-wiki-schema.md)
- [Project concept document](../../docs/concept.md)
