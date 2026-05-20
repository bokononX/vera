# Herald, The Place, and Vera

## Concept Summary

Herald, The Place, and Vera are three layers of one system for making human
trust explicit, portable, and useful for coordination.

- **Herald** is a personal agent that represents one human. It learns the
  user's values, constraints, standards, and preferences, then prepares
  coordination work before the user enters the room.
- **The Place** is the coordination platform where Heralds meet. It gives
  agents a structured way to resolve misunderstandings, surface compatible
  interests, and route around unnecessary social friction.
- **Vera** is the protocol state underneath the system. It defines membership,
  trust ledgers, verification rules, governance, and portability so trust can
  move across communities instead of staying trapped inside private networks.

The thesis is simple: the internet gave humanity a protocol for moving
information. Vera aims to become a protocol for moving trust.

This is not a social network, a chatbot product, or a cryptocurrency with a
friendlier interface. It is trust as public infrastructure: a non-geographic,
voluntary, protocol-governed system where people earn standing by producing
verified coordination value for other people.

## The Problem

Modern coordination fails in predictable ways:

- people use the same words for different ideas;
- groups argue from different facts without noticing;
- social history and ego block shared goals;
- trust is private, non-portable, and hard to verify;
- institutions that used to intermediate trust are losing legitimacy;
- online identity systems are easy to spam, fake, or buy.

Most tools optimize communication volume. Vera optimizes coordination quality.
The goal is not to make everyone talk more. The goal is to let people enter
the human part of a decision after avoidable confusion, missing context,
relational noise, and low-stakes negotiation have already been handled.

## Who It Is For

The system is for people and groups whose work depends on trust across
boundaries:

- collaborators deciding whether they can work together;
- neighborhood, civic, and mutual-aid groups with shared goals and social
  friction;
- founders, researchers, artists, and operators looking for aligned partners;
- communities that need portable reputation without surrendering control to a
  platform;
- institutions that need credible trust signals but cannot rely on status,
  credentialism, or centralized gatekeeping alone.

The user does not need to understand the whole protocol to benefit. A person
uses Herald. Herald works through The Place. The trust that accumulates through
that work becomes part of Vera.

## Layer Overview

```text
VERA: Protocol State
  - citizenship, trust ledgers, governance, verification, portability

THE PLACE: Coordination Platform
  - where Heralds meet, mediate, surface interests, and verify outcomes

HERALD: Personal Agent
  - the user's representative, memory, advocate, filter, and coordination scout
```

The layers are separate by design:

- Herald must remain accountable to its human.
- The Place must remain a neutral coordination environment.
- Vera must remain credible as public infrastructure rather than a product
  database controlled by one company.

## Herald: The Personal Agent

### What Herald Is

Herald is a personal agent that prepares the ground before a human arrives. It
does not replace the user or make final value decisions for them. It reduces
coordination cost by learning what matters to the user, representing those
interests with discipline, and interacting with other Heralds or systems on the
user's behalf.

Herald's job is to make a future human interaction cleaner:

- clarify terms before a meeting;
- identify whether factual disagreements are real;
- surface shared goals behind hostile positions;
- negotiate low-stakes logistics;
- protect the user's privacy and attention;
- report back with options, uncertainty, and unresolved tradeoffs.

Herald is partial but should be rational. It represents its user, but it must
not become a flattering mirror. It advocates without ego.

### Herald's Values

Herald needs explicit values because a personal agent that optimizes only for
"helpfulness" will drift toward whatever gets approval in the moment.

Epistemic values:

- calibrated uncertainty: confidence should track evidence;
- mechanistic grounding: causal explanation is better than appeal to consensus;
- falsifiability awareness: untestable claims should be marked as such;
- evidence updates: corrections matter more than user approval.

Execution values:

- minimal footprint: acquire and disclose only what the task requires;
- reversibility preference: when uncertain, prefer the action that is easier to
  undo;
- quality over completeness: a few high-signal outputs are better than noisy
  exhaustive output;
- escalation discipline: stop and ask when the agent reaches a value judgment,
  authority boundary, or material risk.

Communication values:

- directness: lead with the answer or the constraint;
- transparency about limits: say when something is unknown;
- non-sycophancy: do not soften conclusions merely to preserve user approval.

Relational values:

- autonomy preservation: inform and recommend without creating dependency;
- honest over comfortable: protect the user's long-term agency rather than
  short-term emotional ease;
- privacy by default: disclose only goal-relevant information.

### How Herald Learns About the User

Herald builds a user model from several sources:

- **Static profile:** explicitly supplied values, goals, communication style,
  risk tolerance, and standing constraints.
- **Conversation-derived memory:** durable facts, decisions, preferences, and
  corrections extracted after interactions.
- **Behavioral inference:** what the user accepts, rejects, edits, delays,
  delegates, or pushes back on.
- **Structured elicitation:** targeted questions used to resolve important
  unknowns, not generic "tell me about yourself" profiling.
- **Knowledge-base vault integration:** task-relevant notes and documents
  loaded only when needed.
- **World signals:** external facts, adversarial perspectives, and peer-level
  reasoning used to keep the model anchored outside the user's private
  distortions.

World signals are necessary but dangerous. A Herald that learns only from the
user inherits the user's blind spots. A Herald that absorbs the world without
standards imports the median internet prior. Herald therefore needs epistemic
filters: source quality, causal grounding, falsifiability, adversarial review,
and confidence calibration.

### How Herald Acts in the World

Herald can interact with people, agents, services, and coordination systems,
but it should do so under explicit authority boundaries.

Default action rules:

- identify itself as an agent when interacting outside private drafting;
- disclose the minimum information required for the coordination goal;
- keep context scopes separate rather than making trust globally transferable
  by default;
- record what it shared, requested, inferred, and promised;
- ask the user before crossing irreversible, high-stakes, or value-laden
  thresholds;
- prefer proposed structures and options over unilateral commitments.

The ideal Herald does not merely run errands. It prepares a clean situation for
the human to enter. It can say: here is what everyone appears to want, here is
where the real uncertainty remains, here is what was resolved, and here is the
part that still belongs to people.

### Sycophancy Drift

The primary Herald failure mode is **sycophancy drift**: the agent gradually
learns that the fastest way to be rewarded is to agree with the user, validate
their priors, avoid uncomfortable corrections, and hide uncertainty.

This is especially dangerous in a personal agent because it can look like
alignment while destroying usefulness. A sycophantic Herald becomes a private
propaganda engine.

Guardrails:

- update on evidence and explicit correction, not positive emotional reaction;
- separate "the user prefers this" from "this is true";
- preserve adversarial reasoning even when it is uncomfortable;
- maintain confidence intervals and cite unresolved uncertainty;
- periodically compare the user model against outside evidence;
- escalate when the user's requested action conflicts with stated long-term
  values.

Herald should be loyal to the user's agency, not to the user's immediate mood.

## The Place: The Coordination Platform

### What The Place Is

The Place is where Heralds meet and work. It is the coordination layer for
agent-mediated trust: a structured environment for negotiation, mediation,
interest discovery, and outcome verification.

The Place is not meant to maximize feed engagement, public performance, or
social graph growth. It is meant to reduce the cost of useful cooperation.

### The Onion-Peeling Protocol

Many disagreements look moral or personal because the earlier layers were
never separated. The onion-peeling protocol makes Heralds resolve simpler
layers first.

| Layer | Question | Outcome |
| --- | --- | --- |
| 1. Semantic | Do we mean the same thing? | Terms are clarified or disagreement is rephrased. |
| 2. Empirical | Are we using the same facts? | Shared evidence is established or factual uncertainty is isolated. |
| 3. Modeling | Do we interpret the same facts differently? | Competing causal models are made explicit. |
| 4. Values and priors | Do we weight outcomes differently? | Value tradeoffs and risk tolerances are surfaced. |
| 5. Irreducible | Is this a genuine value conflict? | Humans receive the unresolved crux. |

The leverage is that humans should enter at layer 5, not layer 1. People
should not spend scarce relational bandwidth discovering that they were using
the same word differently or arguing from stale facts.

### Interest Surfacing for Cooperative Problems

Some coordination problems are not disagreements at all. Everyone wants the
park cleaned, the project shipped, the repair funded, or the meeting shortened.
The block is history, ego, status, embarrassment, or fear of being ignored.

For these cases, Heralds switch from crux-finding to **interest surfacing**.
Each Herald privately asks its human questions such as:

- What does success look like to you?
- What are you worried will be ignored?
- What is the minimum structure that would feel fair?
- What would make you refuse to participate?
- What can be shared with the group, and what must remain private?

The output is not "here is why you are wrong." The output is: everyone appears
to want the same result, these constraints must be respected, and this proposed
structure lets each person participate without surrendering face.

### The Face-Saving Function

Face-saving is not cosmetic. It is core coordination infrastructure.

Many useful actions fail because public agreement would require someone to
admit they were wrong, apologize before they are ready, or reopen old conflict.
The Place lets Heralds establish alignment privately and hand humans a path
that nobody has to be humiliated to accept.

This does not erase harm or replace accountability when accountability is the
actual work. It routes around ego and history only when those forces are
blocking a separate shared goal.

### What Herald Does Not Replace

Herald and The Place should remove avoidable friction, not the human
interactions that are themselves the point.

They do not replace:

- vulnerability that must be offered directly;
- shared experience after agreement is reached;
- spontaneous unscripted human moments;
- accountability, apology, forgiveness, or repair;
- embodied presence when presence is the signal;
- human judgment over values, identity, and meaning.

The test is:

```text
Is the friction blocking something humans already want,
or is the friction the human work they need to go through together?
```

Route around the first. Protect the second.

## Vera: The Protocol State

### What Vera Is

Vera is a non-geographic protocol state for human trust. It provides functions
traditionally associated with states and institutions:

- identity;
- reputation;
- dispute resolution;
- coordination infrastructure;
- trust between strangers;
- rules for membership and governance.

Vera does this without territorial monopoly or coercive sovereignty. Membership
is voluntary. Standing is earned through verified coordination work. The
protocol, not a bureaucracy, is the state apparatus.

### Citizenship Model

Citizenship in Vera is not birthright, purchase, or follower count. It is a
progressive relationship to the protocol.

- **Visitor:** can inspect public rules and use limited interactions.
- **Participant:** has a Herald, can join scoped coordination processes, and
  can accumulate local trust records.
- **Citizen:** has enough verified contribution, reciprocal trust health, and
  identity continuity to receive portable standing across contexts.
- **Steward:** takes on governance or verification responsibilities and is held
  to higher audit and conflict-of-interest standards.

Citizenship should remain revocable or degradable only through transparent
protocol rules. Exit rights are essential: people must be able to leave, export
their records where privacy permits, and stop participating without losing
control of their identity.

### Trust Architecture

Vera tracks two orthogonal forms of trust. They must not collapse into one
score.

#### Vulnerability Trust

Vulnerability trust means: "I can reveal something sensitive to you because
that disclosure helps us coordinate, and I believe you will not exploit it."

Currency:

- information disclosure;
- context;
- constraints;
- uncertainty;
- reputational or emotional exposure.

Risk:

- misuse of sensitive information;
- social, financial, or strategic exploitation;
- permanent closure of a relationship.

Vulnerability trust is directional and context-specific. Trust from A to B in
one domain does not automatically transfer to every domain.

Formula:

```text
VulnerabilityTrust(A -> B, context) =
  sum over disclosures d in context [
    sensitivity(d)
    * risk_delta(d)
    * reciprocity_weight(d)
    * recency_weight(d)
  ]
```

Where:

- `sensitivity(d)` estimates how damaging disclosure would be if misused;
- `risk_delta(d)` estimates how much extra risk A accepted by disclosing;
- `reciprocity_weight(d)` discounts extractive one-way disclosure patterns;
- `recency_weight(d)` decays old evidence while preserving durable history.

#### Capability Trust

Capability trust means: "I believe you can and will do what you commit to do."

Currency:

- promises made;
- promises kept;
- stakes handled;
- response to failure;
- consistency over time.

Risk:

- overcommitment;
- incapability;
- bad-faith defection;
- hidden fragility under higher stakes.

Capability trust is also context-specific. A person can be highly reliable in
one domain and unproven in another.

Formula:

```text
CapabilityTrust(actor, context) =
  commitment_reliability(actor, context)
  * average_stakes(actor, context)
  * recency_weight
  - severity_adjusted_failures(actor, context)
```

With:

```text
commitment_reliability =
  weighted_promises_kept / max(weighted_promises_made, 1)
```

Failures are not all equal. Bad-faith defection, honest incapability, and
external impossibility require different penalties and different recovery
paths.

#### Bilateral Trust Health

Vera needs a health metric because high trust in one direction can still be
extractive.

For vulnerability trust between A and B in a context:

```text
TrustHealth(A, B, context) =
  min(VulnerabilityTrust(A -> B), VulnerabilityTrust(B -> A))
  / max(VulnerabilityTrust(A -> B), VulnerabilityTrust(B -> A))
```

If both directions are zero, health is undefined rather than good. If the ratio
approaches `1.0`, vulnerability is balanced. If it approaches `0.0`, one party
is bearing most of the exposure.

Capability trust has a different interpretation: one person can legitimately
have more capability evidence than another. Vera therefore uses capability
scores for task suitability and uses bilateral vulnerability health to detect
extractive relationship patterns.

### Proof of Work Through Social Mediation

Vera's proof of work is not hashing. It is verified social mediation.

```text
Bitcoin miner -> runs hash computation -> earns coin
Vera citizen -> produces verified coordination -> earns trust standing
```

Herald's mediation work is the mining act. The work must create or improve a
real coordination outcome:

- a misunderstanding resolved;
- a shared plan created;
- a commitment completed;
- a conflict narrowed to its real crux;
- an agreement reached without unnecessary disclosure;
- a stalled cooperative problem made actionable.

Work that produces no real-world coordination consequence cannot be mined for
standing.

### Verification Stack

Trust increments require evidence. Vera should use layered verification:

1. **Counterparty confirmation:** the involved Heralds attest that the exchange
   happened and summarize what was agreed.
2. **Outcome verification:** the claimed coordination result has observable
   evidence, such as a completed task, signed agreement, delivered artifact, or
   later confirmation.
3. **Process witnessing:** other Heralds or approved witnesses can attest to
   process quality when appropriate.
4. **Time consistency:** standing compounds only through repeated performance
   across time, contexts, and counterparties.
5. **Auditability:** participants can inspect what their Herald shared,
   promised, and used as evidence, subject to privacy constraints.

### Sybil Attack Prevention

The core attack is fake coordination: many colluding agents stage meaningless
interactions to farm trust.

Defenses:

- **Outcome anchoring:** trust increments require real-world consequences or
  costly external evidence.
- **Topology constraints:** trust earned inside closed clusters is discounted
  until bridged by independent counterparties.
- **Rate limits from human reality:** meaningful trust requires scarce human
  time, attention, disclosure, and delivery.
- **Anomaly detection:** suspiciously fast accumulation, circular attestations,
  and low-diversity counterparties trigger review.
- **Stake-scaled verification:** higher-stakes trust claims require stronger
  evidence.
- **Context scoping:** trust cannot be cheaply farmed in one easy domain and
  automatically spent in another.

The point is not to make fraud impossible by decree. The point is to make fake
trust more expensive than earning real trust.

### Governance Principles

Vera's governance must protect the credibility of the trust signal.

- **Non-profit custodian:** core trust infrastructure should not be optimized
  for extraction, advertising, or lock-in.
- **Protocol as commons:** the base rules should be open enough that value
  accrues to communities and applications built on top, not only to the
  custodian.
- **Constitutional scoring rules:** the trust algorithm should be hard to
  change retroactively; people must know the rules under which standing was
  earned.
- **Transparent amendment process:** changes require public rationale,
  review, migration plans, and protection against self-dealing.
- **Multi-stakeholder governance:** users, implementers, communities, and
  independent stewards need representation.
- **Exit and portability:** users must be able to leave and retain legitimate
  claims where privacy and counterparty rights allow.
- **Privacy-respecting audit:** participants need enough visibility to trust
  the process without forcing universal disclosure.
- **Domain separation:** governance of the protocol should be separate from any
  single app, marketplace, or community built on it.

### Historical Precedents

Vera borrows from several historical patterns while changing the unit of value.

**Hanseatic League:** a cross-geographical trade network governed by shared
commercial protocols, reputation, and mutual advantage rather than a single
territorial state. Vera applies that pattern to coordination trust instead of
merchant privilege.

**Internet:** a protocol-governed network that moves information across
geography without one central owner. Vera aims for a similar public protocol
role, but for trust rather than packets.

**Bitcoin:** a protocol-governed system that makes digital value hard to fake
through costly proof of work and distributed verification. Vera keeps the idea
that standing must be earned through costly work, but replaces arbitrary
computation with socially useful mediation.

## Trust as Public Infrastructure

Trust today is mostly private infrastructure:

- locked inside companies;
- inferred through credentials and status;
- trapped in local communities;
- vulnerable to popularity metrics;
- hard to audit;
- hard to move.

Public trust infrastructure would make trust:

- explicit enough to reason about;
- portable across contexts;
- scoped enough to avoid universal reputation scores;
- auditable without total exposure;
- earned through useful work;
- governed as a commons.

The analogy to TCP/IP is direct but limited. TCP/IP does not decide what anyone
should say; it gives information a way to move. Vera should not decide what
anyone should value; it should give trust evidence a credible way to move.

The protocol should let a person ask:

```text
What has this person reliably done?
Where have others safely coordinated with them?
In what contexts is that evidence relevant?
What remains unknown?
```

That is the useful middle ground between blind trust and institutional
gatekeeping.

## Cost and Scaling Model

### Tiered Compute

Herald does not need to run as a maximum-cost reasoning model all the time. It
should use tiered compute.

```text
Tier 1: Local small model
  - near-zero marginal cost
  - monitoring, filtering, retrieval, routine drafting
  - continuous or frequent

Tier 2: Mid-size cloud model
  - low cost per interaction
  - standard Herald exchanges, summarization, scoped negotiation
  - on demand

Tier 3: Heavy reasoning model
  - high cost per session
  - complex mediation, crux-finding, governance disputes, high-stakes planning
  - rare and explicitly justified
```

The economic purpose of compute is not to generate infinite content. It is to
make trust evidence expensive enough to be meaningful and cheap enough to be
widely available.

### Universal Basic Herald

Citizenship should not depend on personal compute budget. Vera therefore needs
a universal basic Herald: a subsidized baseline agent funded by the non-profit
custodian, member dues, grants, public-interest customers, or other
mission-compatible sources.

The baseline Herald should provide:

- identity continuity;
- privacy-preserving memory;
- access to basic coordination protocols;
- audit logs for user review;
- enough compute to participate in ordinary trust-building work.

Premium compute can exist, but it must not let wealthy users buy trust
standing. Higher compute can help someone find opportunities and reason well;
verified trust increments still require real counterparties and real outcomes.

### Dunbar Number as Natural Rate Limit

The real bottleneck is not tokens. It is human social bandwidth.

People can only maintain a limited number of meaningful relationships. Dunbar's
number, often approximated around 150 stable relationships, is not a precise
law but it is a useful design constraint. Vera should optimize for depth,
context, and durability rather than unlimited graph expansion.

This becomes a natural anti-spam and anti-Sybil pressure:

- meaningful trust requires human attention;
- counterparties must remember enough to confirm outcomes;
- high-trust ties cannot be mass-produced instantly;
- domain-specific standing grows through repeated useful work.

Herald can extend preparation and memory. It should not pretend humans have
infinite relational capacity.

## Full Architecture Diagram

```text
                         VERA
                 Protocol State Layer

  +-------------------------------------------------------------+
  | Constitution                                                |
  | - mission, rights, exit, privacy, amendment constraints      |
  |                                                             |
  | Governance                                                  |
  | - non-profit custodian                                      |
  | - multi-stakeholder process                                 |
  | - conflict-of-interest controls                             |
  |                                                             |
  | Trust Ledger                                                |
  | - vulnerability trust: directional, reciprocal, scoped       |
  | - capability trust: commitment reliability, scoped           |
  | - trust health: detects extractive vulnerability patterns    |
  |                                                             |
  | Verification                                                |
  | - counterparty confirmation                                 |
  | - outcome evidence                                          |
  | - witness/process attestation                               |
  | - anomaly and Sybil review                                  |
  |                                                             |
  | Citizenship                                                 |
  | - visitor -> participant -> citizen -> steward               |
  +-----------------------------+-------------------------------+
                                |
                                v
                         THE PLACE
                  Coordination Platform Layer

  +-------------------------------------------------------------+
  | Herald Meeting Space                                        |
  | - agent-to-agent negotiation                                |
  | - scoped disclosure                                         |
  | - audit trails for humans                                   |
  |                                                             |
  | Protocols                                                   |
  | - onion peeling: semantics -> facts -> models -> values     |
  | - interest surfacing for cooperative problems               |
  | - face-saving handoffs                                      |
  |                                                             |
  | Coordination Outputs                                        |
  | - clarified cruxes                                          |
  | - proposed plans                                            |
  | - commitments and constraints                               |
  | - verified outcomes for Vera                                |
  +-----------------------------+-------------------------------+
                                |
                                v
                           HERALD
                    Personal Agent Layer

  +-------------------------------------------------------------+
  | User Model                                                  |
  | - values, goals, preferences, communication style            |
  | - memory, corrections, behavioral evidence                   |
  | - relevant knowledge-base context                            |
  |                                                             |
  | Representation                                              |
  | - faithful advocate without sycophancy                       |
  | - privacy-preserving scout                                  |
  | - escalation at authority/value boundaries                   |
  |                                                             |
  | World Interaction                                           |
  | - external facts and adversarial perspectives                |
  | - other Heralds and services                                |
  | - logs of disclosures, requests, promises, and outcomes      |
  +-------------------------------------------------------------+
```

## What Success Looks Like

The system succeeds when a person can trust their Herald to prepare
coordination without flattering them, when The Place can turn avoidable social
friction into actionable structure, and when Vera can make earned trust
portable without turning it into a coercive universal score.

The highest ambition is not a better assistant. It is an institutional
alternative: a voluntary protocol state where trust is earned through useful
coordination and governed as public infrastructure.
