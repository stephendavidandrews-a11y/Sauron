# D2: Lane-by-Lane Dedup Matrix

> Phase 0 Deliverable — confirms idempotency status of every Sauron→Networking App routing lane

## Architecture Context

**Routing fires exactly once per conversation**, on Mark as Reviewed only.
The pipeline sets `awaiting_claim_review` and stops — `_run_routing()` in processor.py is dead code.
Dedup fixes are therefore **defensive hardening** against re-review/reprocessing, not emergency triage.

## Risk Levels

| Risk | Meaning |
|------|---------|
| SAFE | Upserts correctly on re-send via sourceSystem + sourceId + sourceClaimId |
| LOW | Upserts on sourceSystem + sourceId (one record per conversation — no collision) |
| MEDIUM | Missing sourceClaimId — multiple records per conversation collide on re-review |
| HIGH | Counter inflation — mentionCount/observationCount increments on every re-send |
| CRITICAL | No dedup fields at all — every re-send creates duplicates |

## Dedup Matrix

| Lane | Name | Endpoint | sourceClaimId | Records/Conv | Re-review Risk | Priority |
|------|------|----------|---------------|-------------|----------------|----------|
| 1 | Interaction | POST /api/interactions | No | 1 | LOW | P3 |
| 1A | Participants | POST /api/interactions/{id}/participants | No | N per speaker | MEDIUM | P2 |
| 1B | Topics | POST /api/interactions/{id}/topics | Yes | N per topic | SAFE | — |
| 2 | Scheduling Leads | POST /api/scheduling-leads | No | N per claim | MEDIUM | P1 |
| 3 | Standing Offers | POST /api/standing-offers | No | N per claim | MEDIUM | P1 |
| 6 | Life Events | POST /api/life-events | No | N per claim | MEDIUM | P1 |
| 7 | Commitments | POST /api/commitments | Yes | N per claim | SAFE | — |
| 8 | Activities | POST /api/activities | Yes | N per claim | SAFE | — |
| 9 | Graph Edges | POST /api/contact-relationships | No | N per edge | HIGH | P1 |
| 10 | Interests | POST /api/interests | Yes | N per mention | HIGH | P1 |
| 10b | Referenced Resources | POST /api/referenced-resources | Yes | N per resource | SAFE | — |
| 10c | Intelligence Signals | POST /api/intelligence-signals | Yes | N per signal | SAFE | — |
| 11 | Expertise Tags | POST /api/expertise | Yes | N per tag | SAFE | — |
| 13 | Contact Notes | POST /api/contact-notes | Yes | 1 | SAFE | — |
| 14 | Profile Intelligence | PATCH /api/contacts/{id} | No | 1 | LOW | P3 |
| 15 | Goals & Priorities | POST /api/goals | Yes | N per goal | SAFE | — |
| 16 | Calendar Events | POST /api/calendar/events | No sourceSystem, No sourceId, No sourceClaimId | N per event | CRITICAL | P0 |
| 17 | Shared Connections | POST /api/shared-connections | Yes | N per connection | SAFE | — |
| 18 | Professional Updates | POST /api/professional-updates | Yes | N per update | SAFE | — |

## Fix Plan (by priority)

### P0 — CRITICAL (blocks safe re-review)

**Lane 16: Calendar Events**
- Problem: No dedup fields. Every re-route creates duplicate Google Calendar events.
- Sauron fix: Add `sourceSystem: "sauron"`, `sourceId: conversation_id`, `sourceClaimId: claim_id` to payload.
- Networking fix: Add upsert logic to `POST /api/calendar/events` — match on sourceSystem+sourceId+sourceClaimId, update instead of create.

### P1 — HIGH/MEDIUM (counter inflation + collision on re-review)

**Lane 9: Graph Edges (contact-relationships)**
- Problem: observationCount increments on every re-send. No sourceClaimId for edge-level dedup.
- Sauron fix: Add `sourceClaimId` derived from edge hash (from_entity + to_entity + edge_type).
- Networking fix: Make observationCount increment conditional — skip if sourceClaimId already exists.

**Lane 10: Interests**
- Problem: mentionCount increments on every re-send.
- Networking fix: Make mentionCount increment conditional — skip if sourceClaimId already exists for this interest.

**Lanes 2, 3, 6: Scheduling Leads / Standing Offers / Life Events**
- Problem: Only sourceSystem+sourceId (conversation-level). Multiple records per conversation collide.
- Sauron fix: Add `sourceClaimId: claim_id` to each payload item.
- Networking fix: Already has 3-field upsert logic, just needs the third field populated.

### P2 — MEDIUM

**Lane 1A: Participants**
- Problem: No sourceClaimId. Multiple participants per conversation.
- Sauron fix: Add `sourceClaimId` derived from participant identifier (speaker label or contact ID).
- Networking fix: Upsert on sourceSystem+sourceId+sourceClaimId.

### P3 — LOW (single record per conversation, natural dedup)

**Lanes 1, 14: Interaction / Profile Intelligence**
- One record per conversation — sourceSystem+sourceId is sufficient.
- No fix needed unless architecture changes.

## Summary

| Status | Count | Lanes |
|--------|-------|-------|
| SAFE (no fix needed) | 9 | 1B, 7, 8, 10b, 10c, 11, 13, 15, 17, 18 |
| LOW (no fix needed) | 2 | 1, 14 |
| MEDIUM (Sauron-side fix) | 4 | 1A, 2, 3, 6 |
| HIGH (both-side fix) | 2 | 9, 10 |
| CRITICAL (both-side fix) | 1 | 16 |

**Total lanes: 18 — 11 safe, 4 need Sauron fix only, 3 need fixes on both sides.**
