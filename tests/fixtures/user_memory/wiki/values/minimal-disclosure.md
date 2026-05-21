---
id: mem-value-minimal-disclosure
title: Minimal Disclosure
page_type: value
owner_user: user-test
status: active
memory_state: confirmed
confidence:
  level: high
  score: 0.91
sensitivity: private
prompt_visibility: task_only
review_status: user_confirmed
created_at: 2026-05-21T00:00:00Z
updated_at: 2026-05-21T00:00:00Z
last_observed_at: 2026-05-21T00:00:00Z
last_confirmed_at: 2026-05-21T00:00:00Z
stale_after: P90D
source_refs:
  - source_id: src-value-minimal-disclosure
    path: raw/redactions/src-value-minimal-disclosure.json
    locator: message:10
    claim: User values minimal disclosure.
    support: explicit
    excerpt_hash: sha256:value
related: []
supersedes: []
superseded_by: []
contradictions: []
corrections: []
tags: [memory, privacy, disclosure]
---

# Minimal Disclosure

User values minimal disclosure when Herald uses memory for task prompts.

## Prompt Rule

Use only when a task asks about memory retrieval, prompt disclosure, or privacy.
