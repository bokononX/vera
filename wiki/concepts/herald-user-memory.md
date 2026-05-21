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

## Source

- [Herald user memory wiki schema](../../docs/herald-user-memory-wiki-schema.md)
- [Project concept document](../../docs/concept.md)
