# Boss Onboarding Manual

## Purpose

Vera and viBot should build a practical operating model of the owner in the
same spirit as a strong personal or executive assistant. The goal is not to
psychoanalyze the owner. The goal is to reduce friction, protect attention,
improve judgment, and help the assistant act in ways the owner would endorse.

The boss model must be explicit, owner-approved, source-backed,
confidence-scored, and privacy-aware. It should answer operational questions:

- What matters to the owner?
- Who matters to the owner?
- How does the owner communicate and decide?
- What drains, protects, or deserves the owner's attention?
- What can Vera handle autonomously?
- What must be drafted, confirmed, or left alone?
- What topics require special consent?
- What assumptions have been corrected?
- What information is stale and needs reconfirmation?

This manual governs owner onboarding, owner-question generation, heartbeat
selection, question queue producers, and owner-memory updates. It is a product
and implementation spec, not a social graph inference spec.

## Research Basis

This manual is informed by executive-assistant, chief-of-staff, and user-manual
patterns without copying their text:

- Harvard Business Review, "What Executive Assistants Know About Managing Up":
  https://hbr.org/2014/12/what-executive-assistants-know-about-managing-up
- Executive Assistant Institute, executive-assistant interview questions:
  https://executiveassistantinstitute.com/questions-to-ask-interviewer-executive-assistant/
- The EA Campus, managing up as an executive assistant:
  https://theeacampus.com/blog/managing-up-as-an-executive-assistant/
- Atlassian My User Manual:
  https://www.atlassian.com/team-playbook/plays/my-user-manual
- Workshop manager README template:
  https://useworkshop.com/resources/manager-readme-template-example/
- Teal executive-assistant interview guide:
  https://www.tealhq.com/career-paths/executive-assistant-interview-questions/
- VantaStaff virtual-assistant onboarding checklist:
  https://www.vantastaff.com/blog/virtual-assistant-onboarding-checklist
- Calendar.com executive-assistant calendar guide:
  https://www.calendar.com/blog/executive-assistant-calendar-management-tips-your-boss-love-you/
- Peter Brack chief-of-staff onboarding playbook:
  https://pbbcoaching.com/content/chief-of-staff-hiring-onboarding-playbook
- McChrystal Group chief-of-staff playbook:
  https://www.mcchrystalgroup.com/docs/default-source/playbooks/chief-of-staff-playbook.pdf

The durable pattern across these sources is simple: effective support depends
on explicit alignment around priorities, communication style, decision rights,
operating rhythm, boundaries, and trust. Vera should learn those things through
owner-approved context and careful review, not covert inference.

## Core Rule

Never silently turn observation into fact.

Observation can create a question. Only the owner's answer creates confirmed
owner context.

Example:

- Observed: the owner texts Alice often.
- Do not infer: Alice is family, a partner, a client, or a close friend.
- Correct behavior: queue a question such as "Who is Alice, and how should I
  understand your relationship with them?"

Frequency is not intimacy. Metadata is not permission. A pattern is not a
relationship fact. Private message content must not be used to infer
relationships, sensitivities, feelings, or personal circumstances.

## Boss Model Domains

The boss model is a set of practical operating pages or records. Each durable
claim should carry provenance, confidence, sensitivity, review state, and a
staleness policy compatible with the Herald user-memory schema.

### Priorities

Track:

- Current goals.
- Active projects.
- Important deadlines.
- What should be protected.
- What can be dropped.
- What is urgent vs merely noisy.

Useful questions:

- "What are the top things you want me to protect your attention for?"
- "If these two commitments conflict, which one should win?"
- "What should I drop or defer if today gets overloaded?"

### People Map

Track only what the owner confirms:

- Name, handle, or contact label.
- Relationship to owner.
- Importance.
- Preferred tone.
- Preferred communication channel.
- Sensitivity level.
- Boundaries.
- Open loops.
- Whether proactive follow-up is welcome.

Useful questions:

- "Who is <person>, and how should I understand your relationship with them?"
- "What tone should I use when helping you communicate with <person>?"
- "Is there anything I should avoid remembering or suggesting about <person>?"

Do not infer relationship type from message frequency, chat recency, display
name, group membership, contact photo, or message body.

### Projects and Domains

Track:

- Project or topic name.
- Owner's role.
- Current phase.
- Importance.
- Key people.
- Known risks.
- What good help looks like.
- Whether Vera should track the project proactively.

Useful questions:

- "What is <project> in your world?"
- "What matters most about <project> right now?"
- "Should I track open loops for <project>, or wait until you ask?"

### Communication Style

Track:

- Short vs detailed updates.
- Direct vs gentle phrasing.
- Recommendation-first vs options-first.
- Preferred channels.
- When to interrupt.
- When to batch.
- How many reminders are useful before annoying.

Useful questions:

- "How do you prefer updates: short bullets, detailed notes, or
  recommendation-first?"
- "What should interrupt you immediately?"
- "What should I batch for later?"

### Decision Style

Track:

- Whether the owner wants options, a recommendation, raw facts, or a draft.
- Acceptable risk level.
- Whether reversibility matters.
- Which decisions Vera may make, draft, prepare, or never touch.
- Safe default when the owner does not respond.

Useful questions:

- "When I bring a decision to you, should I lead with options, trade-offs, or
  my recommendation?"
- "For this kind of task, should I act, draft for approval, or ask first?"
- "What is the safe default if you do not respond?"

### Attention and Energy

Track:

- Focus hours.
- Low-energy periods.
- Meeting tolerance.
- Recovery needs.
- Context-switching cost.
- Quiet hours.
- Good moments for reflective questions.

Useful questions:

- "When is it okay for me to ask small context-building questions?"
- "Are there hours I should treat as quiet by default?"
- "Would you rather answer one question at a time or review a small batch?"

### Delegation and Autonomy

Track:

- Allowed autonomous actions.
- Draft-only actions.
- Approval-required actions.
- No-go actions.
- Escalation thresholds.

Useful questions:

- "What can I handle without asking?"
- "What should I never do without approval?"
- "If something is reversible and low-risk, may I handle it directly?"

### Taste and Voice

Track:

- Writing style.
- Tone by audience.
- Formality preferences.
- Phrases, formats, or styles the owner dislikes.
- What feels "not me" to the owner.

Useful questions:

- "Should this sound warm, formal, brief, careful, or direct?"
- "Should I remember this as a general writing preference?"
- "What did tools or assistants usually get wrong about your voice?"

### Boundaries and Sensitive Zones

Treat these topics as sensitive unless the owner explicitly says otherwise:

- Family.
- Health.
- Money and finance.
- Legal matters.
- Identity, location, and safety.
- Work politics.
- Conflict.
- Intimate relationships.
- Any topic marked temporary, private, or not-for-memory.

Useful questions:

- "Do you want me to remember this, or treat it as temporary?"
- "Is this topic okay for me to use in future suggestions?"
- "Are there boundaries I should observe here?"

### Routines and Operating Rhythm

Track:

- Daily check-ins.
- Weekly review.
- Planning cadence.
- How open loops are reviewed.
- How stale assumptions are refreshed.
- Whether onboarding questions are one-at-a-time, batched, or review-only.

Useful questions:

- "Would you prefer daily, weekly, or only opportunistic check-ins?"
- "Should I batch context questions into a review instead of asking one-off?"
- "Is this a good time of day for small context questions?"

### Corrections and Lessons

Every correction is high-signal. Store the immediate fix separately from any
reusable rule, and confirm whether the reusable rule should be remembered.

Useful questions:

- "Should I remember this as a general rule?"
- "Was this correction specific to this case, or should I apply it going
  forward?"
- "What should I do differently next time?"

## Evidence and Confidence States

Every stored owner fact must have an explicit evidence state.

| State | Meaning | Allowed use |
| --- | --- | --- |
| `confirmed` | The owner explicitly said, approved, or corrected it. | May drive behavior when sensitivity and prompt visibility allow it. |
| `observed` | Repeated behavior or metadata suggests a pattern, but the owner has not confirmed it. | May create a question or low-risk operational caveat. Must not become a sensitive fact. |
| `inferred` | A model or subsystem hypothesis. | Must be labeled as uncertainty. Must not drive sensitive actions without confirmation. |
| `stale` | The fact may have changed. | Use cautiously and prefer refresh questions. |
| `contested` | Contradicted by the owner or later evidence. | Do not use as guidance except to explain uncertainty or prevent repeating an error. |
| `forbidden` | The owner said not to store or use it. | Do not use unless the owner explicitly re-authorizes it. |

Question generation should prefer observed, inferred, or stale gaps only when
an answer would materially improve future behavior.

## Onboarding Phases

### Phase 0: Safety and Boundaries

Before asking many personal questions, establish memory and interruption rules:

- What Vera may remember.
- What should stay temporary.
- What domains require explicit confirmation.
- How often Vera may ask context-building questions.
- Whether proactive questions are welcome during heartbeat.
- Whether Vera should ask one question at a time or batch occasionally.

Initial questions:

- "What kinds of personal context are useful for me to remember?"
- "What should I avoid remembering unless you explicitly say so?"
- "When is it okay for me to ask context-building questions?"
- "Should I ask one question at a time, or batch them occasionally?"

### Phase 1: First 10 High-Signal Questions

Ask only a few foundational questions early. Do not run a long interview unless
the owner asks for one.

Suggested first-pass questions:

1. "What are the top things you want me to protect your attention for?"
2. "What kinds of things should interrupt you immediately?"
3. "What kinds of things should I batch for later?"
4. "How do you prefer updates: short bullets, detailed notes, or
   recommendation-first?"
5. "When I bring a decision to you, should I lead with options, trade-offs, or
   my recommendation?"
6. "Who are the people I should recognize as especially important?"
7. "Are there people or topics where I should be extra careful?"
8. "What can I handle without asking?"
9. "What should I never do without approval?"
10. "What do assistants or tools usually get wrong with you?"

### Phase 2: Observation to Question

After foundation questions, Vera should mostly learn by observing metadata,
task failures, corrections, and explicit owner mentions, then queuing precise
questions.

Good observation inputs include:

- A new person, contact, or handle appears.
- A project name recurs.
- The owner asks for help drafting to a person whose relationship is unknown.
- The owner corrects tone, priority, or scope.
- The owner defers or ignores a category of interruption.
- A task fails because Vera lacked context.

Each observation should produce one of three outcomes:

- No action because the signal is weak, irrelevant, already known, or too
  sensitive.
- A queued question for a later humane asking moment.
- A blocking clarification only when the missing answer is needed for safe or
  useful current work.

### Phase 3: Opportunistic Asking

Queued questions should be asked only at good moments:

- During heartbeat or check-in.
- At the end of a related task.
- When already discussing the same person, project, or topic.
- During explicit review or onboarding sessions.
- Immediately only when the answer blocks safe or useful action.

Do not ask during:

- Active unrelated instructions.
- High-urgency execution.
- Emotional conversations unless the question directly helps.
- Focus or quiet hours.
- Contexts where the owner is clearly trying to finish something.
- Moments when another context question was recently ignored, deferred, or
  dismissed.

### Phase 4: Periodic Review

On a weekly or periodic cadence, Vera should review:

- Newly answered questions.
- Pending questions with high value.
- Dismissed questions that should stay dismissed.
- Stale assumptions.
- People or project pages without confirmed context.
- Corrections that may update reusable rules.

The review should produce a small number of high-value questions, not a long
interrogation.

## Question Trigger Taxonomy

Question producers should use this taxonomy to decide whether a question
candidate should be created. Producers create candidates. The central question
queue or arbiter merges, rejects, cools down, or stores them.

### Trigger A: New Person

Use when a person, contact, or handle appears and no confirmed person context
exists.

Example sources:

- iMessage contact metadata.
- Telegram sender or user metadata.
- Calendar attendee metadata.
- Email/contact metadata, if implemented later.
- Owner mentions a person by name.

Candidate questions:

- "Who is <person>, and how should I understand your relationship with them?"
- "Is <person> family, friend, work contact, client, or something else?"
- "Is there anything I should remember about how to handle topics involving
  <person>?"

Admission rules:

- Do not ask for every one-off person immediately.
- Enqueue if recurring, task-relevant, important, or likely to affect tone or
  privacy.
- Ask immediately only if relationship context blocks the current task.

### Trigger B: Relationship or Tone Gap

Use when Vera may need to write, summarize, remind, or advise about a person
but does not know the tone boundary.

Candidate questions:

- "What tone should I use when helping you communicate with <person>?"
- "Are there boundaries I should observe with <person>?"
- "Should I be warm, formal, brief, careful, or direct with <person>?"

### Trigger C: New Project or Topic

Use when a project, topic, or entity recurs and no project map exists.

Candidate questions:

- "What is <project> in your world?"
- "What matters most about <project> right now?"
- "Should I track <project> proactively?"

### Trigger D: Priority Ambiguity

Use when Vera cannot rank tasks, reminders, or interruptions.

Candidate questions:

- "Is <item> urgent, important, both, or just something to keep an eye on?"
- "If <A> and <B> conflict, which should I protect?"
- "What should I drop if today gets overloaded?"

### Trigger E: Repeated Correction

Use when the owner corrects Vera once in a way that may generalize, or
repeatedly in the same area.

Candidate questions:

- "Should I remember this as a general rule?"
- "Was this correction specific to this case, or should I apply it going
  forward?"
- "What should I do differently next time?"

### Trigger F: Sensitive Boundary

Use when context involves family, health, money, legal, conflict, location,
identity, safety, or intimate relationships.

Candidate questions:

- "Do you want me to remember this, or treat it as temporary?"
- "Is this topic okay for me to use in future suggestions?"
- "Are there boundaries I should observe here?"

Admission rules:

- Prefer not to ask unless the answer is operationally needed.
- Never reveal an inferred sensitive hypothesis in the question.
- If memory consent is unclear, ask about memory permission before asking for
  more detail.

### Trigger G: Proactivity Permission

Use when Vera notices a recurring open loop but does not know whether proactive
follow-up is welcome.

Candidate questions:

- "Do you want me to proactively remind you about <topic>?"
- "How often should I check in about <topic>?"
- "Should I leave this alone unless you ask?"

### Trigger H: Decision Rights Gap

Use when Vera sees a task category repeatedly but does not know whether to act,
draft, ask, or ignore.

Candidate questions:

- "For this kind of thing, should I act directly, draft for approval, or ask
  first?"
- "What is the safe default if you do not respond?"

### Trigger I: Operating Rhythm Gap

Use when heartbeat, check-in, or review cadence is unclear or mismatched.

Candidate questions:

- "Is this a good time of day for me to ask small context questions?"
- "Would you prefer daily, weekly, or only opportunistic check-ins?"
- "Should I batch context questions into a review instead of asking one-off?"

## Admission Policy

Before enqueueing, a producer or central arbiter must pass this checklist:

1. Future usefulness: will the answer change how Vera helps later?
2. Owner-source requirement: is the owner the right source, rather than
   inference or public data?
3. Stability: is the answer likely to remain useful beyond the current moment?
4. Not already known: is there no confirmed, current memory covering it?
5. Not already queued or resolved: is there no pending, asked, answered,
   dismissed, or recently expired equivalent question for the same subject?
6. Privacy fit: is the question allowed by memory and privacy policy?
7. Askability: is there a plausible humane moment to ask later?
8. Specificity: is the question specific enough to answer quickly?

If any check fails, do not enqueue. If the signal is weak but potentially
useful, enqueue only at low priority with a cooldown or wait for another
supporting observation.

## Priority Policy

Suggested priorities:

| Priority | Meaning |
| --- | --- |
| 10 | Blocking or high-risk. Needed before safe action. |
| 8-9 | High-value context likely to matter soon, such as a key person or project. |
| 5-7 | Useful recurring context, not urgent. |
| 2-4 | Nice-to-have preference that can wait. |
| 0-1 | Background curiosity. Usually do not ask unless batched in review. |

Increase priority when:

- The subject recurs.
- The subject is attached to active tasks.
- The answer would prevent privacy or tone mistakes.
- The owner recently mentioned the subject.
- The subject appears in multiple channels.

Decrease priority when:

- The subject appears once.
- The answer is merely interesting.
- The owner dismissed similar questions.
- The topic is sensitive and not operationally needed.

## Ask Timing Policy

Separate question creation from asking.

Question creation is cheap. Asking costs attention.

Ask now only if:

- The answer blocks current work.
- The current conversation is already about the subject.
- The owner explicitly invited onboarding or context questions.

Ask later if:

- The question is useful but not blocking.
- The owner is in an unrelated task.
- The question came from background ingestion.
- The question is reflective or personal.

Do not ask if:

- Quiet hours apply.
- The owner is actively issuing unrelated instructions.
- Another question was asked recently.
- The owner has deferred context questions.
- The question is sensitive and timing is poor.
- The prompt would expose an inference about a sensitive area.

## Heartbeat Selection Rules

Heartbeat is an asking surface, not a generator of unlimited curiosity.

Default heartbeat behavior:

- Ask at most one context-building question per heartbeat.
- Prefer questions related to recent or active topics.
- Prefer pending questions with a clear source, subject, and operational
  benefit.
- Respect `do_not_ask_before`, quiet hours, daily caps, repeat-topic cooldowns,
  and owner-specific heartbeat opt-in.
- Use soft permission framing.
- If the owner ignores, defers, or dismisses the question, set a cooldown or
  lifecycle status instead of repeating it.

Recommended phrasing:

- "Quick context question if now's okay: who is <person>, and how should I
  understand your relationship with them?"
- "Tiny preference check for future help: should I be proactive about
  <topic>, or leave it alone unless you ask?"
- "If now is not a good time, I can hold this for a later review."

Heartbeat should not ask context questions when the best action is a normal
lightweight check-in, when recent messages indicate urgency, or when the queue
contains only low-value background curiosity.

## Wording Rules

Good questions are:

- Short.
- Specific.
- Clearly motivated.
- Easy to answer partially.
- Non-accusatory.
- Non-invasive by default.
- Framed as improving support, not satisfying curiosity.

Use:

- "Who is <person>, and how should I understand your relationship with them?"
- "Is there anything I should remember when helping with <person/topic>?"
- "Should I remember this as a general preference?"
- "Should I be proactive about <topic>, or leave it alone unless you ask?"

Avoid:

- "Why do you text <person> so much?"
- "Are you close with <person>?"
- "Tell me everything about <person>."
- "I inferred <sensitive thing>; is that right?"
- "I noticed emotional pattern X."
- "Your behavior suggests <relationship or diagnosis>."

## Producer Pattern

Every question producer should follow this pattern:

1. Observe event or metadata.
2. Normalize the subject.
3. Look up existing confirmed memory.
4. Look up existing queue entries.
5. Apply trigger-specific admission rules.
6. Create a question candidate with provenance.
7. Let the central question queue or arbiter enqueue, merge, cool down, or
   reject it.
8. Never ask immediately unless explicit blocking policy permits it.

The producer should describe why the question exists, not what the system
secretly thinks is true.

## Queue Data Model Guidance

Each queued question should include or map to:

- `question_id`.
- `question_text`.
- `source` or reason.
- `subject_ref`.
- `priority`.
- `status`.
- `created_at`.
- `updated_at`.
- `do_not_ask_before`.
- `sensitivity`.
- `ask_context`: for example `heartbeat`, `related_conversation`,
  `review_session`, or `blocking_only`.
- `expected_memory_domain`: for example `person`, `project`, `preference`,
  `boundary`, `routine`, `decision_right`, or `voice`.
- `confidence_impact`: what uncertainty this question resolves.
- `provenance`: what observation created it.
- `expires_at` or `stale_after` where applicable.

The current CAT-173 owner-question queue already covers stable ids, question
text, source, subject refs, priority, status, timestamps, cooldowns, dedupe,
answer hashes, answer memory refs, dismissal reason, and generic metadata.

Minimal follow-up recommendation: if multiple producers begin depending on
`sensitivity`, `ask_context`, `expected_memory_domain`, `confidence_impact`,
`provenance`, or expiry semantics, add those as typed optional schema fields in
a small queue schema migration. Until then, producers may use metadata for
non-critical annotations, but they should not overload metadata for behavior
that affects privacy, asking cadence, or memory writes.

## Answer Handling

When the owner answers:

1. Mark the question answered.
2. Store the answer as explicit owner-provided context.
3. Attach provenance linking back to the queue item.
4. Update the relevant memory domain: person, project, preference, boundary,
   routine, decision right, voice, or correction.
5. Do not store more than the owner gave.
6. If the answer is ambiguous, ask at most one follow-up and only if needed.
7. If the answer includes sensitive information, honor memory and privacy
   policy before writing anything durable.
8. If the owner says not to remember it, mark it forbidden or do not persist it.

Secret-like answers must not be written to user memory. Sensitive answers should
use the existing memory sensitivity and prompt-visibility gates.

## Integration Guidance

### CAT-171: iMessage Contact Ingestion

iMessage contact ingestion must remain metadata-only. It may observe normalized
handles, optional display labels, service names, chat membership metadata, and
recurrence indicators. It must not inspect, summarize, embed, or infer from
message bodies.

Producer behavior:

- Observe normalized handle plus optional display label.
- Normalize subject as:
  - `subject_ref.kind`: `imessage_contact`
  - `subject_ref.subject_id`: `imessage:<normalized_handle>`
  - `subject_ref.label`: display label when available
- If no confirmed person memory exists and no equivalent queue entry is
  pending, asked, answered, dismissed, or recently expired, create a candidate:
  - `source`: `imessage_contact_discovery`
  - `priority`: 8 for recurring one-on-one contact or task-relevant contact,
    lower for one-off or group-only appearances
  - `ask_context`: `heartbeat` or `related_conversation`
  - `expected_memory_domain`: `person`
  - `question_text`: "Who is <label>, and how should I understand your
    relationship with them?"
- Ask immediately only if relationship or tone context blocks a current owner
  task.

The answer creates confirmed person context. The contact metadata alone never
does.

### CAT-172: Heartbeat

Heartbeat should select from the owner-question queue only after normal
heartbeat guardrails pass. It should ask at most one context-building question,
prefer high-value questions tied to recent or active topics, and use soft
permission framing.

Heartbeat should not generate new questions from scratch unless it is also
acting as a producer with the same admission, dedupe, and provenance rules.
Selection and phrasing should respect quiet hours, daily initiation caps,
repeat-topic cooldowns, question cooldowns, owner opt-in, and recent deferrals.

If the owner answers, heartbeat or the chat handling path should mark the
question answered and route the answer through owner-memory persistence. If the
owner ignores or defers, the queue should record a cooldown rather than repeat
the same question.

### CAT-173: Owner Question Queue

The queue is the durable handoff between context producers and asking surfaces.
It should remain non-interrupting by default:

- Producers enqueue candidates.
- The queue merges equivalents for the same source and subject.
- Asking surfaces select one eligible question later.
- Lifecycle methods record asked, deferred, answered, dismissed, and expired
  states.
- Owner answers become confirmed memory with provenance back to
  `owner_question:<question_id>`.

Current queue fields are sufficient for the first producer and heartbeat
selection pass. The minimal schema extension described above should be added
only when typed behavior needs to outgrow generic metadata.

## Anti-Patterns

Do not build:

- A secret psychological profile.
- A relationship inference engine from private message content.
- A question spammer.
- A system that asks every possible onboarding question immediately.
- A system that treats frequency as intimacy.
- A system that stores sensitive context without consent.
- A system that interrupts unrelated work with background curiosity.
- A system that asks vague questions such as "tell me about yourself" without
  operational purpose.
- A system that uses observed or inferred context as if it were
  owner-confirmed.

## Success Criteria

Vera should feel like a sharp assistant with a notebook:

- Notices missing context.
- Converts it into a specific question.
- Waits for a good moment.
- Asks one useful question.
- Remembers the owner's answer with provenance.
- Uses the answer to act better later.
- Accepts correction without defensiveness.
- Keeps owner agency intact.
