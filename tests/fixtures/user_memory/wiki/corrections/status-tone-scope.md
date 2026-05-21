---
id: mem-correction-status-tone-scope
title: Status Tone Scope
page_type: correction
owner_user: user-test
status: active
memory_state: correction
confidence:
  level: high
  score: 0.92
sensitivity: private
prompt_visibility: task_only
review_status: user_confirmed
created_at: 2026-05-21T00:00:00Z
updated_at: 2026-05-21T00:00:00Z
last_observed_at: 2026-05-21T00:00:00Z
last_confirmed_at: 2026-05-21T00:00:00Z
stale_after: P180D
source_refs:
  - source_id: src-correction-status-tone
    path: raw/redactions/src-correction-status-tone.json
    locator: message:50
    claim: User corrected concise status to engineering context only.
    support: correction
    excerpt_hash: sha256:correction
related:
  - wiki/preferences/direct-engineering-updates.md
supersedes: []
superseded_by: []
contradictions: []
corrections: []
tags: [correction, engineering, status]
---

# Status Tone Scope

User corrected that concise status preferences apply to engineering updates, not every conversation.

## Corrective Rule

Use this as a guardrail when the concise-update preference is selected.
