# Herald User Memory Wiki Schema

## Purpose

Herald uses a user-memory wiki as its first-class representation of the user.
The wiki is not a side cache or a pile of recalled chat snippets. It is the
structured memory Herald consults before representing the user in Codex work,
coordination with other Heralds, or future Vera workflows.

This design adapts the Karpathy LLM wiki pattern to user memory:

- Raw sources are immutable source records unless a user deletion request
  requires privacy-preserving removal.
- Wiki pages are the LLM-authored synthesis layer.
- A schema document governs page types, metadata, ingest, query, lint, review,
  correction, deletion, and prompt retrieval.

The schema must encode the CAT-131 principles from [the project concept
document](concept.md): Herald represents the user faithfully without pretending
to be the user, discloses minimally, preserves corrections and evidence, marks
inferences transparently, and lets the user inspect, correct, and delete memory.

## Non-goals

- This document does not implement storage, ingestion, retrieval, linting, or
  prompt assembly code.
- This document does not create real user memory files or raw private sources.
- This document does not require secrets, credentials, or external data access.
- The examples below are fictitious schema examples, not facts about a real
  user.

## Repository Shape

A future implementation should create one memory corpus per user or per
explicitly scoped persona. The root name is intentionally generic so the
storage location can move behind configuration later.

```text
memory/
  users/
    <user-id>/
      README.md
      schema.md
      index.md
      log.md
      raw/
        manifest.jsonl
        conversations/
          telegram/
          codex/
          herald/
        notes/
        documents/
        external/
        assets/
        redactions/
      wiki/
        concepts/
        values/
        preferences/
        projects/
        people/
        orgs/
        decisions/
        corrections/
        questions/
        observations/
      review/
        pending.md
        contradictions.md
        stale.md
        deleted.md
```

### Layer Responsibilities

| Layer | Path | Owner | Rules |
| --- | --- | --- | --- |
| Raw sources | `raw/**` | Ingest workflow | Append-only by default. Preserve original evidence, source metadata, hashes, consent scope, and sensitivity. Do not rewrite raw text during synthesis. |
| Source manifest | `raw/manifest.jsonl` | Ingest workflow | One line per source object with stable `source_id`, path, hash, channel, timestamp, sensitivity, deletion state, and retention policy. |
| Synthesized wiki | `wiki/**` | LLM maintainer with schema constraints | Derived memory pages. Every durable claim needs source references, memory state, confidence, sensitivity, and review status. |
| User index | `index.md` | LLM maintainer | Navigation catalog of wiki pages grouped by page type, sensitivity band, review state, and recency. Read first during query. |
| User log | `log.md` | Ingest/query/lint workflows | Chronological audit of ingests, query filings, corrections, deletions, contradiction decisions, stale demotions, and consolidation passes. |
| Schema | `schema.md` | Human plus LLM maintainer | The operating contract copied or generated from this design. Changing the schema is a reviewable event. |
| Review queues | `review/**` | Lint/consolidation workflows | Human-reviewable queues for unresolved contradictions, stale claims, deletion tombstones, and pages awaiting confirmation. |

## Source Records

Each raw source is immutable evidence unless deletion is required. The manifest
is the durable catalog.

Required `raw/manifest.jsonl` fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `source_id` | yes | Stable id such as `src-2026-05-21-telegram-0001`. |
| `path` | yes | Path under `raw/` or a deletion tombstone path under `raw/redactions/`. |
| `source_type` | yes | `conversation`, `note`, `document`, `external`, `asset`, `system_event`, or `correction`. |
| `channel` | yes | Origin channel such as `telegram`, `codex`, `herald`, `manual_note`, `drive`, or `web`. |
| `captured_at` | yes | ISO-8601 timestamp when the source entered memory. |
| `source_event_at` | optional | ISO-8601 timestamp of the original event if different from capture time. |
| `sha256` | yes | Hash of stored raw content or tombstone payload. |
| `sensitivity` | yes | Highest sensitivity present in the source. |
| `consent_scope` | yes | `store`, `store_and_prompt`, `private_only`, `ephemeral`, or `delete_requested`. |
| `retention` | yes | `indefinite`, `review_after:<duration>`, `expire_after:<duration>`, or `deleted`. |
| `redaction_state` | yes | `none`, `redacted`, `tombstoned`, or `pending_delete`. |
| `notes` | optional | Non-secret operational notes, never raw private excerpts. |

Source locators used by wiki pages should point to a source id plus a stable
locator such as a line range, message id, heading, byte range, or paragraph id.
If a source is deleted, wiki pages must remove private claim text and retain
only non-revealing tombstone references.

## Wiki Page Types

All synthesized pages live under `wiki/**` and use YAML frontmatter followed by
short, evidence-linked sections. The page type determines the path and the
allowed claims.

| Type | Path | Use | Prompt default |
| --- | --- | --- | --- |
| `concept` | `wiki/concepts/<slug>.md` | Concepts Herald should understand when representing the user or the Vera system. | Include only when task-relevant and not private. |
| `value` | `wiki/values/<slug>.md` | Durable user values, standards, agency boundaries, and long-term priorities. | Include confirmed values when task-relevant; inferred values require uncertainty text. |
| `preference` | `wiki/preferences/<slug>.md` | Operational preferences, communication style, tooling choices, formats, and workflow habits. | Include task-relevant confirmed or high-confidence observed patterns. |
| `project` | `wiki/projects/<slug>.md` | User projects, goals, constraints, active decisions, and open loops. | Include active project context only for the current task. |
| `person` | `wiki/people/<slug>.md` | People the user refers to, role, relationship context, and consent limits. | Private by default; require relevance and sensitivity review. |
| `org` | `wiki/orgs/<slug>.md` | Organizations, teams, institutions, and relationship context. | Private by default unless public or task-authorized. |
| `decision` | `wiki/decisions/<slug>.md` | Stable decisions the user or Herald made, including rationale and reversibility. | Include when the task depends on prior decisions. |
| `correction` | `wiki/corrections/<slug>.md` | Explicit corrections, reversals, deletions, or contradiction resolutions. | Include as guardrail when it prevents stale or wrong representation. |
| `open_question` | `wiki/questions/<slug>.md` | Important unresolved questions that should block confident representation. | Include as uncertainty or escalation note, not as fact. |
| `observation` | `wiki/observations/<slug>.md` | Low-level repeated observations not yet consolidated into a value or preference. | Do not include directly unless no synthesized page exists and relevance is high. |

## Required Frontmatter

Every synthesized page must include these fields.

```yaml
---
id: mem-<stable-slug>
title: Human-readable page title
page_type: concept | value | preference | project | person | org | decision | correction | open_question | observation
owner_user: <user-id>
status: active | draft | contested | stale | archived | deleted
memory_state: confirmed | inferred | observed_pattern | open_question | correction | retracted
confidence:
  level: high | medium | low
  score: 0.0
sensitivity: public | internal | private | restricted | secret
prompt_visibility: safe | task_only | confirm_first | never
review_status: unreviewed | llm_reviewed | user_confirmed | needs_user_review | disputed | deletion_pending
created_at: 2026-05-21T00:00:00Z
updated_at: 2026-05-21T00:00:00Z
last_observed_at: 2026-05-21T00:00:00Z
last_confirmed_at: null
stale_after: P90D
source_refs:
  - source_id: src-2026-05-21-example-0001
    path: raw/conversations/telegram/2026-05-21-example.md
    locator: message:42
    claim: short non-secret claim summary
    support: explicit | indirect | negative | correction
    excerpt_hash: sha256:<hash>
related:
  - wiki/preferences/example.md
supersedes: []
superseded_by: []
contradictions: []
corrections: []
tags: []
---
```

### Field Rules

- `id` must remain stable across file renames.
- `status: deleted` is allowed only for tombstone pages that contain no private
  claim content.
- `memory_state` identifies how the page should be treated epistemically. It is
  not the same as `review_status`.
- `confidence.score` is advisory and must match `confidence.level`; use `high`
  for explicit confirmed facts, `medium` for stable but indirect evidence, and
  `low` for tentative patterns or old observations.
- `sensitivity` describes the page content, not just the source. Use the
  highest sensitivity of any included claim.
- `prompt_visibility` is the retrieval gate. It may be stricter than
  `sensitivity`.
- `source_refs` must cite raw sources, correction pages, or deletion tombstones.
  A wiki page cannot cite only another wiki page as proof.
- `last_confirmed_at` is required for `memory_state: confirmed` unless the
  source itself is an explicit correction captured at `created_at`.
- `stale_after` is an ISO-8601 duration or `never`. High-risk user
  representation pages should avoid `never`.

## Memory State Rules

### Confirmed

Use `memory_state: confirmed` when the user explicitly states, approves, or
corrects a memory. Confirmed memory can still go stale.

Rules:

- Require at least one explicit source reference or user-confirmed correction.
- Set `review_status: user_confirmed` or `llm_reviewed` only when the raw source
  is explicit enough to need no extra interpretation.
- Prompt inclusion is allowed only if `prompt_visibility` permits it and the
  task needs it.
- Do not convert observed behavior into confirmed preference without user
  confirmation.

### Inferred

Use `memory_state: inferred` when Herald reasons from indirect evidence.

Rules:

- Use `confidence.level: medium` or `low`, never `high`.
- Include a "Why this is an inference" section in the body.
- Prompt inclusion must state uncertainty, for example "likely" or "appears
  to", and must not impersonate the user's intent.
- Inferred values, medical/legal/financial facts, private relationships, and
  sensitive identity claims require `prompt_visibility: confirm_first` or
  `never`.

### Observed Pattern

Use `memory_state: observed_pattern` for repeated behavior across multiple
sources, such as edits, approvals, rejections, deferrals, or preferred output
formats.

Rules:

- Require at least two independent source references or one source plus a
  direct user confirmation.
- Keep the claim behavioral: "The user often asks for concise engineering
  summaries" rather than "The user values brevity above all else."
- Demote to `stale` if a newer correction contradicts the pattern.
- Prompt inclusion is limited to task mechanics unless user-confirmed.

### Open Question

Use `memory_state: open_question` when representing the user would benefit from
a fact that is not yet known.

Rules:

- State the question, why it matters, and what would answer it.
- Do not answer the question by inference in the same page.
- Use `prompt_visibility: task_only` or `confirm_first`.
- Query workflows should surface open questions as blockers or uncertainty,
  not as memory.

### Correction and Retraction

Use `memory_state: correction` for explicit corrections and
`memory_state: retracted` for claims that must no longer be used.

Rules:

- Correction pages are guardrails. They should be short, prominent, and linked
  from the corrected pages.
- Corrected pages must add `corrections` and `superseded_by` references.
- Retractions must remove or neutralize the old claim body. Keep only enough
  tombstone metadata to prevent reintroduction.

## Sensitivity and Prompt Visibility

Sensitivity answers "how private is this memory?" Prompt visibility answers
"may it be placed into an agent prompt?"

| Sensitivity | Examples | Default prompt visibility |
| --- | --- | --- |
| `public` | Public project names, published docs, public commitments. | `safe` if relevant. |
| `internal` | Work-in-progress plans, repo-local decisions, non-public project context. | `task_only`. |
| `private` | Personal preferences, relationship context, private goals, non-public communications. | `task_only` or `confirm_first`. |
| `restricted` | Health, finances, legal, identity, location, safety, credentials-adjacent details. | `confirm_first` or `never`. |
| `secret` | Tokens, passwords, private keys, payment data, raw addresses, authentication data. | `never`. |

Prompt visibility values:

- `safe`: may be included when directly relevant.
- `task_only`: may be included only in the smallest useful form for the current
  task.
- `confirm_first`: must be summarized as an uncertainty or ask for user
  confirmation before inclusion.
- `never`: must not be included in Herald/Codex prompts. Use only a
  non-revealing note that relevant private memory exists if necessary.

## Prompt Retrieval Rules

Herald and Codex prompts must be assembled from the wiki, not from broad raw
source dumps, except when a task explicitly asks to inspect a raw source and
the source is allowed for that use.

Retrieval workflow:

1. Read `schema.md` and `index.md`.
2. Identify the task scope: user representation, project execution, social
   coordination, correction handling, or memory maintenance.
3. Select candidate pages by page type, tags, related links, recency, and
   source relevance.
4. Drop pages with `status: deleted`, `review_status: deletion_pending`, or
   `prompt_visibility: never`.
5. Drop or ask before pages with `prompt_visibility: confirm_first`.
6. Prefer confirmed memory over inferred or observed memory.
7. Include corrections and retractions that affect selected pages.
8. Include open questions only as uncertainty, not as facts.
9. Compress selected memory into a prompt packet with source ids, confidence,
   and sensitivity labels.
10. Use the minimum detail needed for the task. Do not include raw excerpts
    when a short claim summary is enough.

Safe prompt packet format:

```md
## User Memory Context

- Confirmed: <task-relevant memory> [source: src-..., confidence: high]
- Observed pattern: <behavioral pattern, not value claim> [confidence: medium]
- Inferred: <tentative claim with uncertainty language> [confidence: low]
- Correction: <do not use stale/incorrect claim> [source: correction page]
- Open question: <unknown that affects this task>

Omitted: <count> private/restricted memories were not included because they
were not task-relevant or require confirmation.
```

## Correction, Deletion, Contradiction, and Staleness

### Corrections

When the user corrects a memory:

1. Capture the correction as a raw source with `source_type: correction`.
2. Create or update a `wiki/corrections/<slug>.md` page.
3. Update the corrected page with `corrections`, `superseded_by`, and a short
   "Correction" section.
4. Remove stale wording from prompt-eligible summaries.
5. Append a `log.md` entry.
6. Add a review queue item if the correction affects multiple pages.

Corrections outrank earlier inferred and observed-pattern memory. They also
outrank older confirmed memory unless the correction is ambiguous, in which
case the affected pages become `status: contested`.

### Deletions

User deletion requests override ordinary raw-source immutability.

Deletion workflow:

1. Mark affected manifest records `pending_delete`.
2. Identify all wiki pages and review queues that cite the source.
3. Remove private claim text from synthesized pages.
4. Replace raw source content with a non-revealing tombstone only when retention
   of the original is not allowed.
5. Record a deletion tombstone with `source_id`, deletion timestamp, requester,
   and hash of the tombstone payload, not the deleted content.
6. Set affected pages to `status: deleted` or revise them to remove the claim.
7. Append a `log.md` deletion entry that does not restate deleted private data.

Deletion tombstones exist to prevent re-ingestion and to explain why a claim
vanished. They are not a back door for preserving deleted content.

### Contradictions

Contradictions must not be silently averaged away.

Contradiction workflow:

1. Mark affected pages `status: contested`.
2. Add reciprocal `contradictions` references.
3. Create or update `review/contradictions.md` with the conflicting claim
   summaries, source ids, sensitivity, and proposed resolution paths.
4. If one source is a user correction, prefer the correction and update the old
   claim unless the correction itself is ambiguous.
5. If neither side dominates, preserve both claims as unresolved and surface
   the uncertainty during prompt retrieval.

### Stale-Memory Demotion

Staleness is expected. Preferences, projects, relationships, and goals age.

Demotion triggers:

- `stale_after` elapsed since `last_observed_at` or `last_confirmed_at`.
- A newer correction or decision supersedes the page.
- A project moved from active to inactive.
- An observed pattern has no supporting source in the current review window.
- The page cites deleted or redacted sources.

Demotion rules:

- Change `status` to `stale`, reduce confidence, and set
  `review_status: needs_user_review` when the memory may still matter.
- Do not delete stale pages automatically.
- Prompt retrieval may include stale memory only as historical context and only
  when the task explicitly requires history.

## Ingestion Workflow

1. Capture the raw source under `raw/**` and append a manifest record.
2. Classify source sensitivity and consent scope before synthesis.
3. Extract candidate memories with candidate `page_type`, `memory_state`,
   confidence, sensitivity, and source refs.
4. Reject secrets and restricted data from prompt-eligible synthesis unless the
   user explicitly confirms a safe summary.
5. Compare candidates against `index.md` and existing related pages.
6. Update or create wiki pages. Every new claim must cite raw source refs.
7. Update corrections, contradictions, and open questions before ordinary
   preference/value consolidation.
8. Update `index.md`.
9. Append an `ingest` entry to `log.md` naming source ids, pages touched, review
   queues touched, and withheld private categories.
10. Leave review items for low-confidence inferences, sensitive claims,
    contradictions, or deletion-sensitive updates.

## Query Workflow

1. Read `schema.md` and `index.md`.
2. Search wiki pages by page type, tag, title, related links, and source refs.
3. Read selected pages plus linked corrections, contradictions, and open
   questions.
4. Apply prompt retrieval rules and sensitivity gates.
5. Answer with confidence and source ids.
6. If the answer produces a durable synthesis, create or update a wiki page and
   append a `query-filed` log entry.
7. If the query exposes a gap, create or update an open-question page.

## Lint and Consolidation Workflow

Run a lint/consolidation pass periodically and after large ingests.

Required checks:

- Required frontmatter fields are present and typed correctly.
- `source_refs` resolve to `raw/manifest.jsonl` records or valid tombstones.
- Prompt-eligible pages do not cite `secret` sources.
- Inferred pages contain explicit uncertainty language.
- Observed-pattern pages cite enough independent evidence.
- Corrections are linked from corrected pages.
- Deleted sources are not restated in wiki bodies.
- Contradictions are represented in `review/contradictions.md`.
- Stale pages are demoted according to `stale_after`.
- Index entries exist for every active page.
- Orphan pages are either linked, archived, or listed for review.
- Duplicate pages are merged or explicitly distinguished.

Consolidation rules:

- Consolidate low-level observations into preferences or values only when the
  evidence supports the stronger claim.
- Keep corrections as separate pages even after consolidation.
- Preserve source refs through merges.
- Prefer narrower pages over broad personality summaries.
- Do not create flattering global traits from local task behavior.

## Example Pages

The examples are fictitious and demonstrate schema mechanics only.

### Concept Page: Minimal Disclosure

```md
---
id: mem-concept-minimal-disclosure
title: Minimal Disclosure
page_type: concept
owner_user: user-example
status: active
memory_state: confirmed
confidence:
  level: high
  score: 0.95
sensitivity: public
prompt_visibility: safe
review_status: user_confirmed
created_at: 2026-05-21T00:00:00Z
updated_at: 2026-05-21T00:00:00Z
last_observed_at: 2026-05-21T00:00:00Z
last_confirmed_at: 2026-05-21T00:00:00Z
stale_after: never
source_refs:
  - source_id: src-2026-05-21-concept-0001
    path: raw/documents/cat-131-concept.md
    locator: heading:Herald's Values
    claim: Herald should acquire and disclose only task-relevant context.
    support: explicit
    excerpt_hash: sha256:example
related:
  - wiki/values/privacy-by-default.md
supersedes: []
superseded_by: []
contradictions: []
corrections: []
tags: [cat-131, prompt-policy]
---

# Minimal Disclosure

Herald should store, retrieve, and disclose only the user context needed for the
current task. The memory system should prefer small prompt packets over broad
profile dumps.

## Prompt Rule

Include this concept when a task requires user memory retrieval, external
coordination, or cross-channel representation.
```

### User Preference/Value Page: Direct Engineering Updates

```md
---
id: mem-preference-direct-engineering-updates
title: Direct Engineering Updates
page_type: preference
owner_user: user-example
status: active
memory_state: observed_pattern
confidence:
  level: medium
  score: 0.72
sensitivity: private
prompt_visibility: task_only
review_status: llm_reviewed
created_at: 2026-05-21T00:00:00Z
updated_at: 2026-05-21T00:00:00Z
last_observed_at: 2026-05-21T00:00:00Z
last_confirmed_at: null
stale_after: P60D
source_refs:
  - source_id: src-2026-05-21-codex-0002
    path: raw/conversations/codex/2026-05-21-session.md
    locator: turn:8
    claim: User asked for concise completed actions and blockers only.
    support: explicit
    excerpt_hash: sha256:example
  - source_id: src-2026-05-21-telegram-0003
    path: raw/conversations/telegram/2026-05-21-session.md
    locator: message:17
    claim: User provided workflow instructions favoring concise progress records.
    support: indirect
    excerpt_hash: sha256:example
related:
  - wiki/concepts/minimal-disclosure.md
supersedes: []
superseded_by: []
contradictions: []
corrections: []
tags: [communication, engineering-workflow]
---

# Direct Engineering Updates

The user appears to prefer concise engineering status updates that emphasize
completed actions, validation, and blockers.

## Why This Is An Observed Pattern

This is based on repeated workflow instructions and edit preferences. It is not
yet a confirmed global communication value.

## Prompt Rule

For engineering tasks, use this as a task-only style hint. Do not generalize it
to emotionally sensitive conversations or non-engineering contexts without
confirmation.
```

### Project Page: Herald User Memory

```md
---
id: mem-project-herald-user-memory
title: Herald User Memory
page_type: project
owner_user: user-example
status: active
memory_state: inferred
confidence:
  level: medium
  score: 0.66
sensitivity: internal
prompt_visibility: task_only
review_status: needs_user_review
created_at: 2026-05-21T00:00:00Z
updated_at: 2026-05-21T00:00:00Z
last_observed_at: 2026-05-21T00:00:00Z
last_confirmed_at: null
stale_after: P30D
source_refs:
  - source_id: src-2026-05-21-linear-0140
    path: raw/external/linear/cat-140.md
    locator: section:Context
    claim: User memory is Herald's structured model before representing the user.
    support: explicit
    excerpt_hash: sha256:example
related:
  - wiki/concepts/minimal-disclosure.md
  - wiki/questions/q-memory-review-cadence.md
supersedes: []
superseded_by: []
contradictions: []
corrections: []
tags: [vera, herald, memory]
---

# Herald User Memory

The current project is to design Herald's user-memory wiki as the structured
model Herald consults before representing the user.

## Why This Is An Inference

The source confirms the project scope. The inferred part is priority: the
memory subsystem appears to be foundational for future Herald behavior, but the
exact execution order after the design remains a planning question.

## Prompt Rule

Include this page for user-memory implementation, retrieval, privacy, and
correction-control tasks. Present the priority claim as tentative unless the
user confirms it.
```

### Correction Page: Do Not Overstate Directness

```md
---
id: mem-correction-directness-overstatement
title: Do Not Overstate Directness
page_type: correction
owner_user: user-example
status: active
memory_state: correction
confidence:
  level: high
  score: 0.9
sensitivity: private
prompt_visibility: task_only
review_status: user_confirmed
created_at: 2026-05-21T00:00:00Z
updated_at: 2026-05-21T00:00:00Z
last_observed_at: 2026-05-21T00:00:00Z
last_confirmed_at: 2026-05-21T00:00:00Z
stale_after: P180D
source_refs:
  - source_id: src-2026-05-21-correction-0004
    path: raw/conversations/herald/2026-05-21-correction.md
    locator: message:3
    claim: User corrected Herald not to interpret concise status as blanket bluntness.
    support: correction
    excerpt_hash: sha256:example
related:
  - wiki/preferences/direct-engineering-updates.md
supersedes:
  - wiki/observations/bluntness-preference.md
superseded_by: []
contradictions: []
corrections: []
tags: [communication, correction]
---

# Do Not Overstate Directness

The user's preference for concise engineering updates must not be generalized
into a blanket preference for bluntness.

## Corrective Rule

When using `wiki/preferences/direct-engineering-updates.md`, keep the claim
scoped to engineering status and validation unless the user confirms a broader
communication preference.
```

### Open Question Page: Review Cadence

```md
---
id: mem-question-memory-review-cadence
title: Memory Review Cadence
page_type: open_question
owner_user: user-example
status: active
memory_state: open_question
confidence:
  level: low
  score: 0.2
sensitivity: internal
prompt_visibility: confirm_first
review_status: needs_user_review
created_at: 2026-05-21T00:00:00Z
updated_at: 2026-05-21T00:00:00Z
last_observed_at: 2026-05-21T00:00:00Z
last_confirmed_at: null
stale_after: P30D
source_refs:
  - source_id: src-2026-05-21-linear-0140
    path: raw/external/linear/cat-140.md
    locator: section:Scope
    claim: Schema needs review status and stale-memory demotion rules.
    support: explicit
    excerpt_hash: sha256:example
related:
  - wiki/projects/herald-user-memory.md
supersedes: []
superseded_by: []
contradictions: []
corrections: []
tags: [review, open-question]
---

# Memory Review Cadence

What cadence should Herald use to ask the user to review stale preferences,
values, projects, and corrections?

## Why It Matters

Too frequent review creates annoyance and over-collection. Too little review
lets stale memory shape representation.

## What Would Answer This

A user-approved policy such as "review stale private preferences monthly and
project pages when they are used again."
```

## Validation Matrix

| Requirement | Schema response |
| --- | --- |
| Raw sources separated from synthesized wiki pages | `raw/**` and `wiki/**` have separate owners, rules, and source refs. |
| Page types defined | Concept, value, preference, project, person, org, decision, correction, open question, and observation pages are defined. |
| Metadata fields defined | Required frontmatter covers provenance, confidence, sensitivity, recency, source refs, review status, prompt visibility, and staleness. |
| Confirmed vs inferred vs observed-pattern memory | Separate memory-state rules define evidence, confidence, prompt behavior, and review requirements. |
| Correction/deletion/contradiction handling | Dedicated workflows preserve corrections, support user deletion, expose contradictions, and prevent silent averaging. |
| Stale-memory demotion | `stale_after`, recency fields, and demotion triggers reduce confidence and prompt eligibility over time. |
| Prompt retrieval rules | Retrieval workflow enforces task relevance, prompt visibility, sensitivity gates, corrections, and minimal disclosure. |
| CAT-131 faithful representation | Herald stores evidence-linked memory, marks uncertainty, avoids impersonation, and asks before value-sensitive use. |
| CAT-131 minimal disclosure | Prompt packets include only task-relevant summaries and count omitted private memory without exposing it. |
| CAT-131 no sycophancy drift | Corrections, contradictions, source refs, and adversarial review queues prevent flattering drift. |
| CAT-131 transparency | `memory_state`, `confidence`, `review_status`, and source refs distinguish confirmed facts from inferences. |
| CAT-131 autonomy preservation | User correction, deletion, review, and stale demotion are first-class workflows. |
| Karpathy LLM wiki pattern | The design preserves raw sources as source of truth, LLM-authored interlinked wiki pages, schema-guided maintenance, index, log, ingest, query, and lint. |

## Source References For This Design

- [Project concept document](concept.md)
- [Project wiki concept page](../wiki/concepts/herald-the-place-vera.md)
- [Karpathy LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
