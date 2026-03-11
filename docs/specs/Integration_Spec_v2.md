# Sauron ↔ Networking Integration Spec v2

## Status
Final draft — ready for implementation

## Owner
Stephen

## Scope
This document defines how Sauron integrates with the Networking App so that Sauron becomes the canonical conversation-intelligence, review, synthesis, and guidance layer, while the Networking App remains the durable contact registry, CRM record system, and execution workflow layer.

This spec covers:
- product thesis and boundary
- Sauron object architecture
- relationship intelligence coverage requirements
- cross-app ownership and routing
- review layer, entity linking, and contact promotion
- routing path design (review-gated direct writes)
- reviewed payload completeness and extraction layer dependencies
- routing execution constraints (commitment ordering, atomicity, field patch safety)
- contact ID resolution and entity routing prerequisites
- deduplication, idempotency, and reprocessing
- failure tracking and retry semantics
- frontend and product-surface implications
- rollout plan, success metrics, and resolved decisions

This spec does **not** define the CFTC app integration in detail. It is focused on the Networking App.

---

# 1. Purpose

Sauron should become the system that turns conversations, texts, emails, and related interactions into reviewed, evidence-backed relationship intelligence that helps Stephen prepare better, follow up better, and manage relationships better. The Networking App should continue to serve as the durable CRM and workflow system where contact records, interactions, commitments, outreach, and related execution artifacts live.

The problem this spec solves is that both systems can currently participate in ingestion and interpretation. If left unstructured, that creates:
- duplicate extraction
- duplicate truth
- drift between reviewed Sauron state and CRM state
- weak reprocessing semantics
- under-surfaced human context
- and an unclear user experience

This spec defines the clean architecture that prevents that.

---

# 2. Product Thesis

## 2.1 Core thesis

**Sauron is the canonical conversation-intelligence, review, synthesis, and guidance layer.**

It ingests conversations and related communication, extracts evidence-backed objects, lets the user review and correct those objects, maintains derived state over time, and powers Today, Prep, Review, and Search.

**The Networking App is the durable contact registry, CRM record system, and execution workflow layer.**

It stores contact records, interaction records, commitments, signals, outreach workflows, dossier artifacts, and related CRM execution state.

## 2.2 Operating principle

Sauron should answer:
- who matters
- what changed
- what needs action
- what the next move is

Networking should answer:
- what durable contact and interaction records exist
- what commitments and workflow items are in the CRM
- what outreach or prep artifacts already exist
- what stable relationship records need to persist over time

## 2.3 Resulting split

Sauron should be the **brain**.
Networking should be the **registry and execution layer**.

---

# 3. Goals and Non-Goals

## 3.1 Goals

1. Make Sauron the canonical reviewed interpretation layer for overlapping relationship inputs.
2. Preserve Sauron review as the single trust gate before downstream CRM writes.
3. Support whole-relationship intelligence, not just professional CRM fields.
4. Prevent duplicate truth across Sauron and Networking.
5. Preserve provenance and enable reprocessing without creating duplicates.
6. Let review discover, resolve, and promote new people/entities when needed.
7. Improve Today, Prep, Review, and Search through this integration.
8. Route all reviewed object classes to the CRM, including life events, scheduling leads, standing offers, and personal details.

## 3.2 Non-goals

1. Do not turn Sauron into a second CRM.
2. Do not expose a database-shaped UI as the primary product.
3. Do not make recommendations or "next move" a foundational truth object.
4. Do not maintain two equal extraction systems for overlapping sources long term.
5. Do not overwrite user-authored CRM strategic fields casually.
6. Do not require a second review step in the Networking App for Sauron-reviewed items.

---

# 4. Product Principles

## 4.1 Modes over database shape
Sauron should remain organized around Today, Prep, Review, and Search, not around a CRM-style list of stored objects.

## 4.2 Trust over fluency
Every important assertion should remain one tap away from source evidence.

## 4.3 Object-level correction first
When something is wrong, fix the specific object first. Generalize later.

## 4.4 Beliefs are rebuildable views
Beliefs are derived state, not sacred hand-edited paragraphs.

## 4.5 Guidance is downstream of truth
Recommendations, next moves, and tactical cues should be derived from lower layers.

## 4.6 Whole-relationship intelligence matters
The system must remember not just commitments and titles, but also life events, rapport, resources, interests, offers, and relationship movement.

## 4.7 Weak downstream surfacing is not a reason to demote a family inside Sauron
If the CRM stores something poorly or barely surfaces it, that is often a reason for Sauron to surface it more strongly, not less.

---

# 5. Sauron Object Architecture

## 5.1 Summary

Sauron should be designed as a layered object system:

**evidence → episodes → atomic objects → derived state → guidance**

This is the core architecture.

## 5.2 Layer 1 — Evidence

Evidence includes:
- raw transcripts
- message bodies
- email text
- speaker segments / diarization output
- timestamps
- source/channel metadata
- ingest metadata

Evidence is immutable. Corrections should not silently rewrite raw evidence.

## 5.3 Layer 2 — Review units

The primary review unit is the **episode**.

An episode is a semantically coherent chunk of a conversation or message stream that exists to:
- localize extracted objects
- reduce review friction
- preserve evidence context
- make correction precise

Episodes are not final truth objects. They are review scaffolding over evidence.

## 5.4 Layer 3 — Atomic extracted objects

These are the smallest meaningful evidence-linked objects Sauron should extract and correct directly.

Core atomic families include:
- claims
- commitments
- standing offers
- scheduling leads
- intelligence signals
- life events
- referenced resources
- relationship notes / rapport observations
- contact relationships / graph edges
- entity links / subject resolution
- speaker assignments

Every atomic object should:
- link to evidence
- carry provenance
- support correction
- remain discrete rather than being buried in prose

## 5.5 Layer 4 — Derived state

Derived state is maintained interpretation over atomic objects.

Core families include:
- beliefs
- relationship trajectory
- reciprocity balance
- what changed
- communication approach
- person/topic synthesis
- dossier-style state summaries

Derived state must remain auditable and recomputable.

## 5.6 Layer 5 — Guidance

Guidance is the topmost action-oriented layer.

Includes:
- next move
- suggested approach
- recommended tone
- what to ask about now
- whether to push / wait / congratulate / reconnect
- active recommendation
- morning priorities

Guidance is not canonical truth. It is contingent on lower-layer evidence, derived state, timing, and user goals.

## 5.7 Compression principle

Every important surfaced object should support:
- 3-second skim (headline — one sentence)
- 15-second skim (summary — 2-3 sentences)
- 2-minute view (full context with evidence links)

Extraction synthesis should produce `headline`, `summary`, and `full_context` as distinct fields to enable these tiers. Belief synthesis should produce `belief_headline` and `belief_detail`. Person Briefs aggregate these into the three compression tiers.

---

# 6. Relationship Intelligence Coverage Requirements

## 6.1 Purpose

Sauron must maintain a whole-relationship intelligence model for important people. It is not enough to remember meeting summaries or tasks. The system should be able to answer:
- who this person is and why they matter
- what happened recently
- how the relationship is moving
- what each side owes or has offered
- what personal context matters
- what they care about
- who connects to them
- what changed enough to affect how Stephen should engage them

## 6.2 Coverage families

Sauron's relationship intelligence should be organized into seven families:

1. Identity and strategic context
2. Interaction history and evidence
3. Open loops and reciprocity
4. Personal continuity and rapport
5. Interest and resource map
6. Network context
7. Derived relationship state

Guidance such as "next move" sits above these families. It is produced from them.

## 6.3 Family 1 — Identity and strategic context

Includes:
- name, aliases, title, organization
- categories, tags
- whyTheyMatter, introductionPathway
- strategic relevance, connection/orbit context

This is mostly slow-changing context.

## 6.4 Family 2 — Interaction history and evidence

Includes:
- interaction summaries, recency
- sentiment, relationship delta
- relationship notes, topics discussed
- linked episodes / claims / source conversations

This spans atomic records and evidence-linked history.

## 6.5 Family 3 — Open loops and reciprocity

Includes:
- commitments, standing offers
- scheduling leads, promised introductions
- promised resources, unresolved asks
- reciprocity balance

This begins as atomic objects and rolls up into derived open-loop state.

## 6.6 Family 4 — Personal continuity and rapport

Includes:
- life events, milestones
- birthdays/anniversaries where appropriate
- family details, preferences
- recurring personal hooks
- rapport observations, remembered details worth following up on

This family prevents the system from becoming cold and purely transactional.

## 6.7 Family 5 — Interest and resource map

Includes:
- referenced resources (books, papers, articles, podcasts, reports)
- repeated subject-matter interests
- desired reading
- things they said they would send, things Stephen should send them
- topical affinities that drive rapport or strategic relevance

## 6.8 Family 6 — Network context

Includes:
- introduction pathway, observed relationships
- family/professional/social links
- graph neighborhood, provenance of observed relationships

## 6.9 Family 7 — Derived relationship state

Includes:
- beliefs about the person
- relationship trajectory, reciprocity balance
- what changed since last time
- communication approach, current stance on key topics

This family is pure derived state.

## 6.10 Surface requirement

These families must be visible in the right places:
- Today
- Prep / Person Brief
- Search
- Review

Coverage is not satisfied simply because some field exists in storage.

---

# 7. Relationship Intelligence Coverage Matrix and System Boundary

## 7.1 Purpose

This section bridges the conceptual relationship-intelligence coverage model and the cross-app ownership model.

## 7.2 Coverage matrix

| Family | Sauron layer | Read from Networking | Write to Networking in v1 | Primary experience | Boundary stance |
|---|---|---|---|---|---|
| Identity & strategic context | slow-changing context | Yes | Limited / careful only | Sauron Person Brief + CRM record | Read, careful writes only |
| Interaction history & evidence | atomic records + evidence | Yes | Yes | both, richer in Sauron | Read + Write |
| Open loops & reciprocity | atomic objects + derived | Yes | Yes (all subtypes) | Sauron Today/Prep + CRM records | Read + Write |
| Personal continuity & rapport | atomic personal-memory | Yes | Yes | primarily Sauron | Read + Write |
| Interest & resource map | atomic interest/resource | Yes | Yes | primarily Sauron | Read + Write |
| Network context | link objects + derived graph | Yes | Yes | both; richer in Sauron prep | Read + Write |
| Derived relationship state | derived state | Supporting only | No | Sauron only | Sauron-local only |
| Guidance | derived guidance | No | No | Sauron only | Sauron-local only |

## 7.3 V1 write scope

All of the following object classes are routed to the Networking App on Sauron review:
- Interaction Summary (with sentiment, relationshipDelta, relationshipNotes, topicsDiscussed)
- Commitment (concrete/intentional firmness; social firmness → SchedulingLead instead; tentative → skip)
- Standing Offer
- Scheduling Lead
- Life Event
- Personal Interest / Activity (as contact field updates)
- Contact Relationship / Graph Edge
- Intelligence Signal (org intel, status changes)
- Referenced Resource
- New Contact stubs (for triage)

**Sauron-local in v1** (not routed to Networking):
- Beliefs, relationship trajectory, what changed
- Tactical cues, next move, recommendation history
- Vocal intelligence (no Networking target exists)

## 7.4 Summary rule

Weak downstream surfacing is not a reason to demote a family inside Sauron. If the CRM stores something poorly, that is often a reason for Sauron to surface it more strongly.

---

# 8. Cross-App Object Ownership and Routing

## 8.1 Ownership summary

### Sauron owns
- intake and evidence handling
- episode construction and extraction
- object-level review and correction
- entity linking and speaker correction
- beliefs, trajectory, and what-changed
- tactical guidance and recommendations
- Today / Prep / Review / Search orchestration

### Networking owns
- durable contact registry and contact UUIDs
- user-edited contact metadata
- persisted interaction timeline records
- persisted commitments/signals/offers/edges as CRM records
- outreach queue and meeting prep artifacts
- dossier versions

### Shared but not co-owned
- contact identity references (via unified_contacts ↔ Contact ID bridge)
- interaction concepts (Sauron extracts, Networking persists)
- relationship context (Sauron derives, Networking stores)

## 8.2 Source-of-truth rules

### Networking is authoritative for
- durable contact UUID / durable contact record
- user-edited CRM contact fields
- persisted CRM interaction record
- persisted CRM commitment state
- dossier artifact
- outreach workflow state

### Sauron is authoritative for
- raw evidence and conversations
- episodes, claims, beliefs, trajectory
- interaction interpretation and extraction
- commitment extraction logic and provenance
- what changed and next move
- relationship guidance

---

# 9. Review Layer, Entity Linking, and Contact Promotion

## 9.1 Purpose

Review is the integrity boundary of the whole system. Extraction should not become durable downstream truth until a human has had the opportunity to inspect and correct it.

## 9.2 Review atoms

Current/planned review atoms include:
- episode review
- per-claim approve/flag/edit
- entity linking on claims
- speaker correction
- belief review (planned / partial)
- daily "what changed" review (planned)
- Mark as Reviewed as routing gate

## 9.3 Review responsibilities

Review inside Sauron should own:
- object correction
- relationship-state integrity
- entity resolution
- routing eligibility

## 9.4 Contact/entity handling during review

Review should support:
- linking claim subject to existing person/entity
- correcting speaker identity
- creating provisional person/entity
- promoting reviewed entity to CRM contact when needed
- merging/reassigning mistaken identities

## 9.5 Contact sync

Sauron syncs contacts from Networking into `unified_contacts` via `sync.py` and uses them for entity resolution, relational reference resolution, prep/search context, and routing safety.

## 9.6 Promotion rules

Promote to CRM when:
- the person is the subject of a meaningful relationship
- the person is likely to recur
- the person is an introducer or promised contact
- the person matters for future prep/search/routing

Keep provisional/local when:
- the mention is incidental
- the identity is ambiguous
- the person matters only as context around another person
- evidence is too thin

## 9.7 Review rule

Sauron review is the single trust boundary. Claims, speakers, entities, and relationship objects are corrected there; beliefs and derived state are then recomputed or marked under review; and only reviewed outputs become eligible for downstream CRM creation or update. There is no second review step in the Networking App.

---

# 10. Routing Path Design

## 10.1 Governing decision

**Sauron uses review-gated direct writes to the Networking App's API endpoints.**

When the user clicks "Mark Reviewed" in Sauron:
1. Sauron builds a routing payload from the reviewed, corrected database state (not the raw extraction JSON)
2. Sauron calls individual Networking App API endpoints to create/update CRM records
3. Every write includes `sourceSystem: 'sauron'` and `sourceId: {conversation_id}` for provenance and idempotency
4. `conversations.routed_at` is set only when all routes succeed

Sauron does NOT use the Networking App's ingestion queue (`POST /api/ingest`) for v1. The ingest-confirm path is a potential v2 migration if auto-confirm is desired, but v1 uses direct writes gated behind Sauron review.

## 10.2 Why direct writes

- Sauron review is the trust boundary. There is no need for a second confirm step in the Networking inbox.
- Direct writes are simpler to implement and debug.
- The Networking App's confirm cascade creates objects through its own internal logic; direct writes give Sauron explicit control over what gets created and in what shape.

## 10.3 Networking App endpoints (Sauron write targets)

| Endpoint | Object class | Status |
|---|---|---|
| `POST /api/interactions` | Interaction + Commitments | Exists — updated with upsert logic |
| `POST /api/commitments` | Standalone Commitment | POST handler added (was GET-only) |
| `POST /api/standing-offers` | Standing Offer | New endpoint created |
| `POST /api/scheduling-leads` | Scheduling Lead | New endpoint created |
| `POST /api/contacts/[id]/life-events` | Life Event | New endpoint created |
| `PATCH /api/contacts/[id]` | Contact field updates | Exists — used for factual updates |
| `POST /api/contacts` | New contact creation | Exists — used for contact promotion |

All endpoints that accept Sauron writes support upsert on `sourceSystem` + `sourceId`. If a record with the same source identity exists, the endpoint updates it instead of creating a duplicate.

## 10.4 Idempotency contract

Every Sauron write includes:
- `sourceSystem: "sauron"`
- `sourceId: {conversation_id}`
- optionally `sourceClaimId: {claim_id}` for per-claim granularity

The Networking App uses these fields to enforce idempotency:
- If `sourceSystem` + `sourceId` match an existing record → update in place
- If no match → create new record

This makes reprocessing and re-review safe. A conversation can be reprocessed, re-extracted, re-reviewed, and re-routed without creating duplicate CRM records.

## 10.5 Schema additions (Networking App)

The following Prisma models receive new nullable fields:

| Model | New fields |
|---|---|
| Interaction | `sourceSystem`, `sourceId` |
| Commitment | `sourceSystem`, `sourceId`, `sourceClaimId` |
| StandingOffer | `sourceSystem`, `sourceId` |
| SchedulingLead | `sourceSystem`, `sourceId` |
| LifeEvent | `sourceSystem`, `sourceId` |
| ContactRelationship | `sourceSystem`, `sourceId` |

All fields are nullable. Existing records are unaffected. Indexes are added on `(sourceSystem, sourceId)` for efficient upsert lookups.

## 10.6 Source tagging

All records created by Sauron include source identification:
- Interactions: `source: 'sauron'`, `sourceSystem: 'sauron'`, `sourceId: conversation_id`
- Commitments: `sourceSystem: 'sauron'`, `sourceId: conversation_id`, `sourceClaimId: claim_id`
- Standing offers, scheduling leads, life events: `sourceSystem: 'sauron'`, `sourceId: conversation_id`

This enables filtering, debugging, and understanding what Sauron contributes versus manual entries.

## 10.7 Reviewed payload completeness

The reviewed payload builder must include all routable object classes from the reviewed extraction data. In v1, this means:

- **Commitments and scheduling leads:** Rebuilt from reviewed `event_claims` rows (claim-level corrections are reflected)
- **Memory writes** (life events, interests, activities, contact field updates): Loaded from the claims pass extraction JSON (pass 2, stored in the `extractions` table)
- **New contacts mentioned:** Loaded from the claims pass extraction JSON
- **Standing offers, follow-ups, graph edges, topics discussed, relationship notes:** Loaded from the synthesis pass extraction JSON (pass 3)

The claims pass already produces memory writes and new contacts in the correct shape (the `MemoryWrite` Pydantic model and the `new_contacts_mentioned` list). The reviewed payload builder currently does not load them — it initializes both as empty lists. This must be fixed as a prerequisite for routing.

**Correction caveat:** Memory writes loaded from the extraction JSON are not updated when individual claims are corrected during review. If a user corrects the underlying claim, the memory write may still reflect the original extraction. This is acceptable in v1. A future improvement would store memory writes as discrete reviewable objects or regenerate them from corrected claims.

**Extraction quality dependency:** The routing path depends on Sonnet consistently producing memory writes for extractable life events, interests, and contact details. After the routing path is operational, memory write recall should be audited. If Sonnet underproduces memory writes for conversations that contain these details, the claims prompt should be tuned to increase recall.

## 10.8 Extraction layer dependencies

The routing path expects the following fields on the Interaction payload sent to the Networking App:

- `sentiment` — one of: warm | neutral | transactional | tense | enthusiastic
- `relationshipDelta` — one of: strengthened | maintained | weakened | new

These are whole-conversation assessments that belong in the Opus synthesis pass (pass 3), alongside summary, relationship_notes, and vocal_intelligence_summary. The `SynthesisResult` schema should be updated to include `sentiment` and `relationship_delta` as explicit fields matching the Networking App's expected enum values.

Until the Opus prompt is updated and validated, the routing code should use keyword inference on `relationship_notes` as a fallback. The fallback should be removed once the Opus prompt produces these fields directly.

## 10.9 Routing execution constraints

### Commitment ordering

The Networking App's `Commitment` model has a required foreign key to `Interaction`. A Commitment cannot be created without an `interactionId`. Therefore, routing must create the Interaction first, receive the returned ID, and use it when creating Commitments for the same conversation.

The preferred approach is to send commitments as part of the Interaction payload (the `POST /api/interactions` handler accepts a `commitments` array and creates Commitment rows inline). This avoids a separate API call and guarantees the FK is satisfied. Standalone `POST /api/commitments` should only be used for commitments that don't have a parent Interaction (edge case).

### Routing atomicity

Routing for a single conversation involves multiple API calls to different endpoints. If some calls succeed and others fail, the Networking App has partial state for that conversation.

**V1 rule:** If any routing call for a conversation fails, the entire conversation is logged as `failed` in `routing_log` and all calls are retried together on the next attempt. The upsert idempotency (Section 10.4) makes retrying already-succeeded calls harmless — they simply update in place.

`conversations.routed_at` is only set when all routing calls for that conversation succeed.

### Contact field patch safety

The Networking App's `PATCH /api/contacts/[id]` endpoint allows Sauron to update contact fields (title, organization, email, phone, address). However, the user may have manually edited these fields in the CRM.

**V1 rule:** Sauron only patches contact fields that are currently null. If a field already has a value — whether set by the user, by the Networking App's own ingestion, or by a prior Sauron write — Sauron does not overwrite it.

This is conservative but safe. It means Sauron fills gaps but never overwrites existing data.

**V2 refinement:** A more sophisticated approach would track the last writer per field (via a `last_modified_by` column or field-level source tagging) and allow Sauron to overwrite its own prior writes while preserving user edits. This requires Networking App schema changes and is deferred.

### Legacy ingestion item removal

The current routing code (`networking.py`) creates an IngestionItem in the Networking App's inbox via `POST /api/inbox` with `source: 'voice'` at the end of every routing run, in addition to the direct writes. This means every reviewed conversation currently produces both CRM records (via direct writes) and a pending inbox item (via the ingestion queue).

When the new routing is operational, this `_create_ingestion_item` call must be removed. Sauron no longer writes to the Networking App's ingestion queue for voice conversations. Direct writes are the sole routing path. The Networking inbox only receives items from its own ingestion sources (email, text, manual).

If the call is not removed, confirmed inbox items will duplicate the CRM records that direct writes already created.

---

# 11. Entity Routing Prerequisites

## 11.1 Purpose

Routing to the Networking App requires knowing the Networking App's contact ID. This section defines how Sauron resolves contact IDs and what happens when resolution fails.

## 11.2 Contact ID bridge

Sauron maintains a `unified_contacts` table with a `networking_app_contact_id` column. This is populated by:
- Contact sync (`sync.py`) — pulls contacts from Networking and matches by name or existing link
- Contact promotion — when a provisional contact is confirmed and pushed to the Networking App, the returned ID is stored
- Contact linking — when a provisional contact is linked to an existing confirmed contact, the target's ID is inherited

## 11.3 Resolution at routing time

When routing, Sauron resolves the Networking contact ID by:
1. Looking up the primary non-Stephen speaker in `unified_contacts`
2. If `networking_app_contact_id` is populated → use it directly (no HTTP lookup)
3. If not populated → do NOT fall back to name-string search (too fragile)
4. Instead, create a `pending_entity` entry in the routing log

**Sauron never does name-string HTTP lookups against the Networking App at routing time.** This eliminates wrong-match, missed-match, and round-trip latency problems.

## 11.4 Pending entity workflow

When Sauron encounters an entity without a `networking_app_contact_id`:

1. The routing payload is stored in `routing_log` with `status: 'pending_entity'` and `entity_id` referencing the `unified_contacts` row
2. The conversation is still marked as reviewed (`reviewed_at` is set)
3. `routed_at` is NOT set (routing is incomplete)
4. The Today page surfaces pending-entity counts as a triage signal

**Release triggers:** When a `unified_contacts` row gets a `networking_app_contact_id` (via sync, promotion, or linking), all pending routes referencing that entity are released:
- The stored payload is sent to the Networking App with the now-resolved contact ID
- The routing log entry is updated to `status: 'sent'`
- `conversations.routed_at` is set on the originating conversation

This is wired into three code paths:
- `graph.py` `confirm_provisional_contact` (after push to Networking App returns an ID)
- `graph.py` `link_provisional_contact` (after merge into a confirmed contact)
- `sync.py` `sync_contacts_from_networking_app` (after sync populates IDs)

## 11.5 Entity lifecycle

Entity/contact states:
1. **Mentioned** — name appears in transcript, no entity record yet
2. **Resolved** — entity resolver links mention to an existing `unified_contacts` row
3. **Provisional** — new `unified_contacts` row created with `is_confirmed = 0`
4. **Confirmed** — `is_confirmed = 1`, may or may not have `networking_app_contact_id`
5. **Promoted** — confirmed AND `networking_app_contact_id` populated (either via push or sync)
6. **Merged/reassigned** — provisional collapsed into another entity

Not every mentioned person should become a durable CRM contact. Routing only proceeds for promoted entities.

---

# 12. Networking Read Contract

## 12.1 Purpose

This section defines what Sauron reads from Networking to enrich Today, Prep, Search, and routing safety.

## 12.2 Core v1 read surfaces

Sauron should read:
- contact core record (via sync into `unified_contacts`)
- recent CRM interactions (for prep context)
- open commitments (for prep and today)
- relationship edges / graph neighborhood
- outreach queue status (for dedup and routing safety)

## 12.3 Read families

### Person Brief reads
Used for identity and strategic context, recent CRM interactions, commitment/open-loop context, graph neighborhood, outreach state.

### Today / what-changed reads
Used for outreach queue, prep status, commitments, relationship recency.

### Search support reads
Used for contact lookup, alias resolution, graph context.

### Routing safety reads
Used before creating new downstream objects: existing contact identity, open commitments context.

## 12.4 Read rule

Networking is the durable relationship registry and workflow context source. Sauron reads from it to improve entity resolution, prep, and routing safety, but does not treat it as the source of its higher-layer beliefs, trajectory, or guidance.

## 12.5 Implementation note

In v1, the read contract is partially implemented. `sync.py` pulls contacts. `brief.py` and `morning_email.py` currently read from Sauron's own database only. As Prep and Search surfaces mature, reads from Networking will be added for dossier context, outreach state, and commitment status.

---

# 13. Failure Tracking and Retry

## 13.1 Purpose

Routing failures must not silently lose data. If the Networking App is down or a write fails, the failure must be logged, visible, and retryable.

## 13.2 Routing log table

Sauron maintains a `routing_log` table:

```
routing_log (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    target_system TEXT,          -- 'networking' or 'cftc'
    route_type TEXT,             -- 'direct_write' or 'ingest_payload'
    object_class TEXT,           -- 'interaction', 'commitment', etc.
    status TEXT,                 -- 'pending', 'pending_entity', 'sent', 'failed', 'skipped'
    entity_id TEXT,              -- unified_contacts.id (for pending_entity)
    attempts INTEGER,
    last_attempt_at DATETIME,
    last_error TEXT,
    payload_json TEXT,
    networking_item_id TEXT,     -- ID returned by Networking App on success
    created_at DATETIME
)
```

## 13.3 Failure semantics

- Routing failures are **non-blocking**: the conversation is marked reviewed regardless
- Failed routes are logged with the payload and error message
- `conversations.routed_at` is only set when ALL routes succeed
- A periodic retry job re-attempts failed routes (max 5 attempts)
- The Today page surfaces failed-route and pending-entity counts as triage signals
- Manual retry is available via `POST /pipeline/retry-failed-routes`

## 13.4 Reprocessing rule

When a conversation is reprocessed and re-reviewed:
- The idempotency contract (Section 10.4) prevents duplicate CRM records
- Existing routing_log entries for the conversation are not affected (new entries are created for the new routing attempt)
- If the Networking App already has records for this `sourceId`, they are updated in place

---

# 14. Deduplication and Idempotency

## 14.1 Required mechanism

Every Sauron-originated downstream write uses `sourceSystem: 'sauron'` + `sourceId: {conversation_id}` as a stable external identity.

## 14.2 Networking App behavior on duplicate sourceId

If an incoming Sauron write matches an existing record by `sourceSystem` + `sourceId`:
- **Update in place.** The existing record's fields are updated with the new values.
- Do not create a second record.

If no match exists:
- **Create new record.**

## 14.3 Commitment-level granularity

Commitments use `sourceClaimId` in addition to `sourceId` for per-claim dedup. A single conversation may produce multiple commitments; each is identified by its claim ID.

## 14.4 Why this is sufficient

The direct-write path with upsert-on-sourceId provides the same dedup guarantee as the ingest-confirm path's external-ID mechanism, without requiring changes to the Networking App's ingestion queue. The upsert logic is simpler to reason about and debug.

---

# 15. Frontend and Surface Implications

## 15.1 Purpose

This section translates the architecture and boundary decisions into frontend behavior inside Sauron.

## 15.2 Top-level navigation

Do not add top-level Contacts or Networking sections.

Keep the four-mode shell:
- Today
- Prep
- Review
- Search

People/topics/entities should surface *within* those modes, not replace them.

## 15.3 Review implications

Current review surface should continue to support:
- episode review
- per-claim approve/flag/edit
- entity linking
- speaker correction
- raw JSON inspection
- Mark as Reviewed

Still required by the architecture but not fully built:
- Quick Pass
- belief review
- daily "what changed" review

## 15.4 Prep implications

Prep should become the main whole-relationship intelligence surface.

Person Brief should include:
- 3-second skim (headline)
- 15-second skim (summary)
- 2-minute full brief

And should draw from all relationship families, including:
- identity and strategic context
- recent interactions
- commitments/open loops
- personal continuity
- interest/resource map
- network context
- beliefs/trajectory/what changed
- suggested approach

## 15.5 Today implications

Today should surface:
- what changed
- urgent and overdue obligations
- prep status
- active recommendations
- relationship movement
- life events when timely
- stale scheduling leads
- promised resources / forgotten loops
- **routing status** (failed routes, pending-entity holds)

## 15.6 Search implications

Search must retrieve:
- people, topics, conversations
- beliefs (where exposed)
- open-loop clusters
- relationship notes, standing offers
- life events, referenced resources
- network context

Search should not behave like transcript-only semantic lookup.

## 15.7 Frontend rule

The person/topic surfaces inside Prep and Search must become rich enough that the user does not miss having a CRM-style navigation section.

---

# 16. Rollout and Implementation Plan

## 16.1 Sequence

### Phase A — Networking App endpoint changes
- Add `sourceSystem`/`sourceId` fields to 6 Prisma models
- Add upsert logic to `POST /api/interactions`
- Create `POST /api/standing-offers` endpoint
- Create `POST /api/scheduling-leads` endpoint
- Create `POST /api/contacts/[id]/life-events` endpoint
- Add `POST` handler to `/api/commitments`
- Run Prisma migration

### Phase B — Sauron routing infrastructure
- Add `routing_log` table to Sauron schema
- Implement contact ID bridge resolution (use `unified_contacts.networking_app_contact_id`, no HTTP name lookups)
- Implement pending-entity hold and release workflow
- Wire release triggers into `graph.py` (confirm, link) and `sync.py`
- Fix `reviewed_payload.py` to load memory_writes and new_contacts from the claims pass extraction JSON (pass 2)
- Fix `reviewed_payload.py` to load standing offers, graph edges, and other synthesis data from pass 3

### Phase B.5 — Extraction layer updates
- Add `sentiment` and `relationship_delta` fields to `SynthesisResult` schema
- Update the Opus synthesis prompt to produce these fields with the Networking App's expected enum values
- Validate against a few real conversations before proceeding to Phase C

### Phase C — Rewrite Sauron routing
- Rewrite `networking.py` to use resolved contact IDs and include `sourceSystem`/`sourceId` on all writes
- Send commitments inline with the Interaction payload (not as separate calls) to satisfy the interactionId FK constraint
- Implement all-or-nothing routing: if any call fails, log the entire conversation as failed and retry all calls together
- Implement null-only contact field patching (do not overwrite existing values)
- Remove the `_create_ingestion_item` call — Sauron no longer writes to the Networking inbox for voice conversations
- Add failure logging to `routing_log` instead of silent exception swallowing
- Remove keyword-inference fallback for sentiment/delta once Opus produces them directly
- Update `mark_reviewed` to only set `routed_at` on full routing success
- Add `POST /pipeline/retry-failed-routes` and `GET /pipeline/routing-status` endpoints

### Phase D — Validate end-to-end
- Process conversations → review → verify CRM records appear correctly
- Test reprocessing → verify upsert (no duplicates)
- Test with unresolved contacts → verify pending-entity hold → promote → verify release
- Test Networking App down → verify failure logging → restart → verify retry
- Test with all object classes: interactions, commitments, standing offers, scheduling leads, life events, contact relationships, intelligence signals

### Phase E — Stabilize daily-use loop
- Improve morning email content
- Review friction improvements
- Today temporal awareness and routing status display
- Prep launcher and surprise-call flow
- Validate Prep pulls graph/belief/what-changed data correctly

### Phase F — Make Sauron canonical for overlapping sources
- Once the path is stable, treat Sauron as the primary interpreter for voice conversations
- Networking-native extraction remains for direct non-Sauron inputs (email, text, manual)
- Overlapping sources (voice) flow exclusively through Sauron

## 16.2 Things not to do first

Do not start by:
- building a parallel Contacts/Networking section in Sauron
- writing beliefs/trajectory directly into Networking
- building the ingest-confirm path (deferred to v2 if needed)
- replacing the Networking App's own extraction for non-voice sources

---

# 17. Success Metrics

## 17.1 Architecture success
- Sauron becomes the trusted review/intelligence layer for voice conversations
- Networking remains the durable CRM/workflow layer
- There is no persistent dual-truth extraction path for voice

## 17.2 Routing success
- Reviewed Sauron conversations produce correct CRM records via direct writes
- All 10 object classes route successfully (interaction, commitment, standing offer, scheduling lead, life event, contact relationship, intelligence signal, referenced resource, new contact stub, contact field update)
- Reprocessed conversations update rather than duplicate

## 17.3 Entity resolution success
- Contacts with `networking_app_contact_id` route immediately
- Contacts without it are held, not silently dropped or wrong-matched
- Pending routes release automatically when the ID is populated

## 17.4 Failure handling success
- No routing failures are silently swallowed
- Failed routes are visible in Today and retryable
- Networking App downtime during review does not lose data

## 17.5 Relationship-intelligence success
- Person Briefs surface not just commitments and summaries, but also personal continuity, interests/resources, standing offers, network context, and relationship movement
- Search can retrieve those same families meaningfully
- Today surfaces real "what changed" and open-loop intelligence

## 17.6 Review success
- Claim/entity/speaker corrections are easy enough to happen regularly
- Beliefs and derived state are updated or marked under review correctly after lower-layer changes
- Quick Pass, belief review, and daily delta review can be added without changing the architecture

---

# 18. Resolved Decisions

These were open questions in v1. They are now resolved.

## 18.1 Single vs. double review gate
**Resolved: Single gate.** Sauron review is the only trust boundary. The Networking App does not require a second confirm step for Sauron-originated writes. Direct writes land CRM records immediately on Mark Reviewed.

## 18.2 Direct writes vs. ingest-confirm path
**Resolved: Direct writes for v1.** Sauron calls individual Networking App API endpoints. The ingest-confirm path is available as a v2 migration if auto-confirm or manifest/undo support is desired, but v1 uses direct writes with upsert idempotency.

## 18.3 Contact ID bridge
**Resolved: Required for v1.** Sauron resolves contact IDs from `unified_contacts.networking_app_contact_id` at routing time. No HTTP name-string lookups. Items involving unresolved entities are held in the routing log until the ID is populated.

## 18.4 Write scope
**Resolved: Full scope in v1.** All object classes are routed, including life events, scheduling leads, referenced resources, and personal details. These were previously deferred to v2 but already had working (if silently failing) code. With the new endpoints in place, they route correctly.

## 18.5 Failure semantics
**Resolved: Non-blocking with retry.** Routing failures are logged, not swallowed. Conversations are marked reviewed regardless. Failed routes are retryable. Routing status is visible in Today.

## 18.6 Sentiment and relationship delta
**Resolved: Opus produces them explicitly.** The Opus synthesis pass is updated to produce `sentiment` and `relationship_delta` as enum fields matching the Networking App's expected values. Keyword inference on relationship_notes prose is a temporary fallback only, removed once the Opus prompt is validated.

## 18.7 Commitment ordering
**Resolved: Commitments go inline with Interaction.** Sauron sends commitments as part of the Interaction payload to satisfy the Networking App's required FK constraint. Standalone commitment creation is only used for edge cases without a parent Interaction.

## 18.8 Contact field safety
**Resolved: Null-only patching in v1.** Sauron only patches contact fields that are currently null. Existing values are never overwritten. A more sophisticated last-writer-tracking approach is deferred to v2.

## 18.9 Routing atomicity
**Resolved: All-or-nothing per conversation.** If any routing call fails, the entire conversation is logged as failed and all calls are retried together. Upsert idempotency makes retrying already-succeeded calls safe.

## 18.10 Reviewed payload completeness
**Resolved: Load from extraction JSON.** Memory writes and new contacts are loaded from the claims pass extraction JSON (pass 2). They are not reconstructed from event_claims rows. This is a known gap in the current code that must be fixed before routing is operational.

## 18.11 Legacy ingestion item removal
**Resolved: Remove on routing rewrite.** The current `_create_ingestion_item` call in `networking.py` is removed when the new direct-write routing is operational. Sauron does not write to the Networking App's ingestion queue for voice conversations. Direct writes are the sole path. Leaving the call in place would create duplicate CRM records when inbox items are confirmed.

## 18.12 Belief integration pattern
**Deferred.** Beliefs remain Sauron-local in v1. Whether they eventually feed Networking through dossier synthesis or a new CRM belief model is a later decision.

## 18.13 Vocal intelligence
**Deferred.** Sauron's vocal insights have no direct Networking target. Later options include feeding dossier context or creating a dedicated UI surface.

---

# Known Gaps / Deferred Tasks

The following items are implemented at the backend/API level but lack frontend integration or are otherwise deferred:

1. **Today page routing status display** (Section 15.5 implication)
   - `GET /pipeline/routing-status` endpoint exists (Phase C) and returns pending-entity holds, failed routes, and sent counts from routing_log.
   - The Today page does not yet call this endpoint to display routing status (failed routes, pending-entity holds).
   - This is a Phase E frontend task. The backend is ready; only the React component needs wiring.

2. **Referenced resources routing** (Section 10.9, Phase D)
   - Routing code exists in networking.py as a stub (`synthesis.referenced_resources`).
   - The Opus extraction prompt does not yet produce a `referenced_resources` list on SynthesisResult.
   - Will activate once the extraction layer is updated.

3. **Belief integration pattern** (Section 18.12) — Deferred. Beliefs remain Sauron-local in v1.

4. **Vocal intelligence routing** (Section 18.13) — Deferred. No Networking target yet.

---

# 19. Final Summary

Sauron is the canonical conversation-intelligence, review, synthesis, and guidance layer. It stores evidence, organizes it into reviewable episodes, extracts atomic relationship objects, maintains derived state over time, and powers Today, Prep, Review, and Search.

Networking is the durable contact registry, CRM record system, and execution workflow layer. Sauron reads context from it and writes reviewed additive relationship intelligence back into it through review-gated direct API writes with sourceSystem/sourceId idempotency.

The boundary is asymmetric:
- Sauron owns interpretation, beliefs, trajectory, what changed, and guidance
- Networking owns contact identity, CRM records, outreach workflow, and dossier artifacts
- Routing uses the contact ID bridge (no name-string lookups) and holds unresolved entities until promoted

The routing contract requires:
- The reviewed payload builder loads all routable data (including memory writes from the claims extraction JSON, not just event_claims rows)
- The Opus synthesis pass produces sentiment and relationship_delta as explicit enum fields
- Commitments are sent inline with the Interaction payload (FK constraint)
- Routing is all-or-nothing per conversation (partial state is never left in the CRM)
- Contact field patches only fill null fields (never overwrite existing values)
- The legacy `_create_ingestion_item` call is removed (no dual-path writes to avoid duplicates)
- All failures are logged, visible, and retryable

The integration succeeds if:
- review remains the single trust boundary
- sourceId-based upsert prevents reprocessing duplication
- the contact ID bridge and pending-entity workflow prevent wrong-match and silent-drop failures
- routing failures are logged, visible, and retryable
- and the person-level experience in Sauron becomes richer than the CRM on the dimensions that matter most: whole-relationship memory, what changed, open loops, network context, and guidance
