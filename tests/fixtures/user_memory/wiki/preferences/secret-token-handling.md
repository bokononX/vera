---
id: mem-preference-secret-token-handling
title: Secret Token Handling
page_type: preference
owner_user: user-test
status: active
memory_state: confirmed
confidence:
  level: high
  score: 0.95
sensitivity: secret
prompt_visibility: never
review_status: user_confirmed
created_at: 2026-05-21T00:00:00Z
updated_at: 2026-05-21T00:00:00Z
last_observed_at: 2026-05-21T00:00:00Z
last_confirmed_at: 2026-05-21T00:00:00Z
stale_after: never
source_refs:
  - source_id: src-secret-token
    path: raw/redactions/src-secret-token.json
    locator: message:30
    claim: Secret token detail exists.
    support: explicit
    excerpt_hash: sha256:secret
related: []
supersedes: []
superseded_by: []
contradictions: []
corrections: []
tags: [token, secret]
---

# Secret Token Handling

Secret token detail exists and must never appear in Codex prompts.
