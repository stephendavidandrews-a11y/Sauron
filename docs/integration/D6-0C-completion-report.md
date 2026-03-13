# Phase 0C — Missing Routing Lanes: Completion Report

> Verified 2026-03-13 on Mac Mini. App loads cleanly (133 routes).

---

## Scope Decision

Original 0C plan had 4 items. After user review and discussion, scope was reduced:

| Item | Decision | Reason |
|------|----------|--------|
| 0C.1 Contact status advance | **Implemented** | Clear value — auto-advances contact lifecycle based on real conversations |
| 0C.2 Dossier synthesis trigger | **Deferred** | User wants to design trigger logic later ("after enough new information") |
| 0C.3 Contact stub creation | **Dropped** | "All risk and no reward" — NA remains source of truth for contacts |
| 0C.4 Commitment firmness | **Already implemented** — verified | Firmness flows through routing; Prisma schema confirmed |

---

## 0C.1: Contact Status Advance

### What it does
After Sauron successfully creates an Interaction in the Networking App (Lane 1), a new secondary lane (1C) reads the contact's current status and advances it based on conversation signals.

### Transition rules
| Current Status | Condition | New Status |
|---------------|-----------|------------|
| target | Any interaction | active |
| outreach_sent | Any interaction | active |
| cold / dormant | Warm/enthusiastic sentiment OR strengthened relationship | warm |
| warm | Any interaction | active |
| active | — | No change |

### Implementation details
- **File**: sauron/routing/networking.py, lines ~315-410 (Lane 1C)
- **Trigger**: Only fires when interaction lane succeeded (created_interaction_id is truthy)
- **Reads**: sentiment and relationshipDelta from the interaction payload already built for Lane 1
- **HTTP calls**: GET /api/contacts/{id} to read current status, PATCH /api/contacts/{id} to update
- **Lane type**: Secondary (non-fatal) — failure logged as warning, does not block other lanes
- **Logging**: [ROUTING] Contact status advance: {old} -> {new} for contact {id}
- **Result tracking**: Appends to secondary_lane_results with status (success/failed/skipped_no_transition/skipped_no_interaction)

### Guard rails
- Skipped entirely if interaction creation failed or was skipped
- Skipped if no networking_app_contact_id resolved
- Cold/dormant contacts only advance to warm with positive sentiment signal (not on neutral/transactional conversations)
- No status downgrade ever happens
- Wrapped in try/except — any exception is caught and logged

---

## 0C.4: Commitment Firmness — Verification

### Current state
- **Sauron routing** (networking.py): firmness is already included in commitment payloads sent to NA
- **Networking App schema** (prisma/schema.prisma, line 337): firmness String? confirmed on Commitment model
- **Extraction** (sauron/extraction/schemas.py): Deep extraction produces firmness values

### Current firmness levels
- concrete — specific, actionable commitment with clear deliverable
- intentional — stated intention without concrete deliverable
- tentative — exploring possibility, hedged language
- social — social niceties ("we should get coffee")

### Future enhancement note
User wants a level above concrete: "ordered/promised" — reserved for explicit obligations where someone MUST do an action. Examples:
- Work project deadlines
- Explicit promises to Catherine
- Bills and financial commitments
- Tasks with external accountability

This would create a 5-tier hierarchy: ordered > concrete > intentional > tentative > social

**Action**: Deferred to Phase 1+ when commitment system is revisited. Requires:
1. Add "ordered" to extraction schema and prompts
2. Update NA Prisma enum/validation
3. Update frontend display (potentially different visual treatment for ordered commitments)

---

## 0C.2: Dossier Trigger — Deferred (with Deep Dive)

### Why deferred
User wants to design the trigger logic thoughtfully rather than auto-triggering on every routing. Quote: "I know I don't want every conversation to generate a dossier for everyone. After enough new information has been added about the contact, it generates one, but I'm not sure how it would work."

### Dossier System Deep Dive

**What it is**: Per-contact intelligence document synthesized by Claude from all NA data sources. Produces a structured markdown dossier covering relationship context, interaction history, commitments, interests, and communication patterns.

**Model**: Claude Sonnet 4 (claude-sonnet-4-20250514) — NOT Opus. $10/day API budget cap enforced via src/lib/api-budget.ts.

**API call parameters**:
- max_tokens: 4000
- temperature: 0.3
- System prompt: "You are an expert relationship intelligence analyst..."

**10 internal data sources** (all Prisma queries, no external APIs):
1. Contact record (name, org, title, status, tags)
2. Interactions (last 50, with participants and notes)
3. Commitments (all, grouped by status)
4. Scheduling leads and standing offers
5. Contact relationships (with other contacts)
6. Life events
7. Personal interests and activities
8. Intelligence signals (profile, org, status change)
9. Contact provenance records
10. Previous dossier version (for incremental mode)

**Modes**:
- Full: Synthesizes from scratch using all 10 sources
- Incremental: Receives previous dossier + new data since last synthesis, produces delta update

**Triggers (current)**:
- Manual: POST /api/contacts/{id}/dossier from the NA UI
- Auto: Inbox confirmation (/api/inbox/[id]/confirm) triggers incremental dossier after confirming an inbox item
- No Sauron trigger exists (this was 0C.2's purpose)

**Storage**: Dossier text stored on the Contact record, with dossierGeneratedAt timestamp and dossierVersion counter.

**Future trigger design considerations**:
- Could track "new data points since last dossier" counter per contact
- Trigger when counter exceeds threshold (e.g., 5+ new claims/interactions)
- Or trigger on first routing after N days of silence for a contact
- User needs to decide — this is a product design question, not just engineering

---

## 0C.3: Contact Stub Creation — Dropped

User's reasoning: "All risk and no reward." Networking App should remain the source of truth for contact creation. Risks of auto-creating stubs:
- Duplicate contacts from slight name variations
- Cluttering the CRM with throwaway mentions
- Entity resolution becomes harder with more low-quality contacts
- User already has 405 contacts in NA — wants quality over quantity

---

## Files Modified in 0C

| File | Change |
|------|--------|
| sauron/routing/networking.py | +~90 lines: Lane 1C (contact status advance) |

No schema changes. No Networking App changes. No new files.

---

## Verification

| Check | Result |
|-------|--------|
| networking.py imports clean | PASS |
| Full app import (133 routes) | PASS |
| Lane 1C positioned after Lane 1A (participants) | PASS |
| Lane 1C is secondary (non-fatal) | PASS |
| Lane 1C skipped when no interaction | PASS |
| Firmness field in Prisma schema | PASS (line 337) |
| Firmness in routing payload | PASS (already present) |

---

## Summary

Phase 0C delivered one new routing lane (contact status advance) and confirmed one existing capability (firmness flow). Two items were consciously deferred/dropped based on user judgment. The codebase is ready for commit and progression to 0D (Endpoint Contract Table).
