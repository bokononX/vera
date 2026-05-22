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

iMessage contact metadata ingest is a separate metadata-only source path. It
does not extract claims from message content. Instead, it stores discovered
handles as `person` pages marked as open questions needing owner review, with
prompt visibility set to `confirm_first` so Vera can ask who the person is
before treating the contact as relationship context.

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
Private, restricted, and secret memory are excluded from ordinary Codex prompts
by default. Code paths that need more disclosure must opt into those sensitivity
classes explicitly, and the selected memory must still be task-relevant.

Each task run records the selected memory page ids/paths in JSON run state, so
debugging can inspect what memory influenced the prompt without reconstructing
the full wiki disclosure.

## Implemented User Control Boundary

Owner Telegram chat now has first-class user-memory controls before normal
Codex turns. The owner can ask what is remembered about a topic, correct a
memory, forget a memory, mark a memory as more sensitive, and review recent
memory updates.

The control path works against synthesized wiki pages rather than raw source
dumps. Listing returns source ids, confidence, sensitivity, prompt visibility,
and review metadata. Corrections create linked correction pages and update the
active claim summary used by retrieval while preserving older wording for audit.
Forget requests tombstone the affected page, remove prompt eligibility, redact
claim text from source references, rebuild the index, and append a non-revealing
log entry. Sensitivity marks update prompt visibility so future retrieval obeys
the new classification.

High-sensitivity inferred memory is not written directly into wiki pages. It is
held in the confirmation review queue until the user explicitly confirms the
claim should be stored.

## Implemented Lint Boundary

The harness can scan a configured user-memory corpus and produce a reviewable
lint/consolidation report. The pass checks for duplicate candidates, orphan
pages, stale pages, missing provenance/confidence metadata, unresolved
contradictions, missing backlinks, generic relationship links that need
explicit typing, and concept-level mismatches between durable values,
tactical preferences, and low-level observations.

Dry-run mode is the default. Controlled apply mode is limited to mechanical
structure fixes: rebuilding the index, adding missing backlinks, demoting pages
that exceed their `stale_after` window, and appending a lint/consolidation log
entry. It does not merge duplicate identity claims, erase contradictions, or
promote observations into values without review.

## Source

- [Herald user memory wiki schema](../../docs/herald-user-memory-wiki-schema.md)
- [Project concept document](../../docs/concept.md)
