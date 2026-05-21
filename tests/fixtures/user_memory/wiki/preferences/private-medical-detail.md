---
id: mem-preference-private-medical-detail
title: Private Medical Detail
page_type: preference
owner_user: user-test
status: active
memory_state: confirmed
confidence:
  level: high
  score: 0.90
sensitivity: restricted
prompt_visibility: confirm_first
review_status: user_confirmed
created_at: 2026-05-21T00:00:00Z
updated_at: 2026-05-21T00:00:00Z
last_observed_at: 2026-05-21T00:00:00Z
last_confirmed_at: 2026-05-21T00:00:00Z
stale_after: P30D
source_refs:
  - source_id: src-restricted-medical
    path: raw/redactions/src-restricted-medical.json
    locator: message:22
    claim: Restricted health-related preference exists.
    support: explicit
    excerpt_hash: sha256:restricted
related: []
supersedes: []
superseded_by: []
contradictions: []
corrections: []
tags: [medical, health]
---

# Private Medical Detail

Restricted health-related preference exists and must not be placed in prompts without confirmation.
