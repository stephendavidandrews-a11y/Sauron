# D1: Current Lane Inventory

> Produced 2026-03-13. All 18 Sauron to Networking App routing lanes.

## Routing Architecture

- **Entry**: route_extraction() in sauron/routing/router.py
- **Orchestrator**: route_to_networking_app() in sauron/routing/networking.py
- **Review gate**: mark_reviewed() in sauron/api/conversations.py calls build_reviewed_payload() then route_extraction()
- **Note**: Hold-until-review is permanent default. Reviewed payload uses corrected DB state (edited claims, corrected speakers), not stale extraction JSON. VERIFY: whether initial routing fires during extraction or is fully deferred.
- **Failure semantics**: Core lane failure = entire conversation routing fails (return False). Secondary lane failure = warning only (return True).
- **Retry**: Full conversation retry via routing_log (all-or-nothing per conversation, no individual lane retries)

## Lane Table

| # | Lane | Endpoint | Core/Secondary | Currently Fires | Review-Gated | Idempotent on Reroute | Missing Side Effects | Notes |
|---|------|----------|---------------|----------------|-------------|----------------------|---------------------|-------|
| 1 | interaction | POST /api/interactions | Core | Yes | Yes (reviewed payload) | Yes (sourceSystem+sourceId upsert) | No contact status advance; no dossier trigger | Skipped for solo prep; skipped for solo debrief with thin summary |
| 1A | interaction_participants | POST /api/interaction-participants | Core (sub) | Yes | Yes | Yes (unique constraint on interactionId+contactId) | -- | Only fires if interaction created; resolves speakers via contact bridge |
| 1B | commitment (standalone) | POST /api/commitments | Secondary | Yes | Yes | Partial (requires sourceClaimId; skipped if absent) | -- | direction: i_owe/they_owe; kind: commitment/scheduling/soft_ask; firmness flows |
| 2 | scheduling_leads | POST /api/scheduling-leads | Core | Yes | Yes | Unclear (sourceId only, no sourceClaimId) | -- | Includes social-firmness commitments plus dedicated scheduling list |
| 3 | standing_offers | POST /api/standing-offers | Core | Yes | Yes | Unclear (sourceId only, no sourceClaimId) | -- | Phase 4 entity resolution via synthesis_entity_links |
| 4 | follow_ups | (inline with Interaction) | Secondary | Yes | Yes | N/A (part of interaction payload) | -- | Sets followUpRequired + followUpDescription on Interaction |
| 5 | contact_field_updates | PATCH /api/contacts/{id} | Secondary | Yes | Yes | Yes (null-only patching) | -- | Only writes null/empty fields; reads current state first |
| 6 | life_events (claims) | POST /api/contacts/{id}/life-events | Secondary | Yes | Yes | Unclear (sourceId dedup) | -- | From claims.memory_writes where field==lifeEvent |
| 7 | interests | POST /api/personal/interests | Secondary | Yes | Yes | Yes (sourceClaimId populated) | -- | From claims.memory_writes where field==interest; increments mentionCount on match |
| 8 | activities | POST /api/personal/activities | Secondary | Yes | Yes | Yes (sourceClaimId populated) | -- | From claims.memory_writes where field==activity; updates lastMentioned on match |
| 9 | graph_edges | POST /api/contact-relationships | Core | Yes | Yes | Partial (no sourceClaimId; dedup on contactA+contactB unique) | -- | Bidirectional contact resolution; holds on provisional entities; skips self-refs |
| 10 | policy_positions | POST /api/signals (type=policy_position) | Core | Yes | Yes | Yes (sourceClaimId populated) | -- | Routed as intelligence signals |
| 10b | status_changes | POST /api/signals (type=status_change) | Secondary | Yes | Yes | Yes (sourceClaimId populated) | -- | Routed as intelligence signals |
| 10c | org_intelligence | POST /api/organization-signals | Secondary | Yes | Yes | Yes (sourceClaimId populated) | Side effect: store_provisional_org() on 422 | Provisional org capture on resolution failure |
| 11 | referenced_resources | POST /api/referenced-resources | Secondary | Yes | Yes | Yes (sourceClaimId populated) | -- | |
| 13 | provenance | POST /api/contact-provenance | Secondary | Yes | Yes | Yes (sourceClaimId populated) | -- | |
| 14 | profile_intelligence | POST /api/contact-profile-signals | Secondary | Yes | Yes | Partial (sourceId dedup, no sourceClaimId) | -- | Per-contact vocal/behavioral summaries |
| 15 | affiliations | POST /api/contact-affiliations | Secondary | Yes | Yes | Yes (sourceClaimId populated) | -- | Wave 2 feature; org resolution on NA side |
| 16 | calendar_events | POST /api/calendar/events | Secondary | Yes | Yes | No (no dedup key; creates new event each time) | -- | Attendee names in description; date/time inference |
| 17 | asks | POST /api/commitments (kind=soft_ask) | Secondary | Yes | Yes | Yes (requires sourceClaimId; skipped if absent) | -- | direction: i_owe/they_owe; firmness: tentative/social/intentional |
| 18 | life_events (synthesis) | POST /api/contacts/{id}/life-events | Secondary | Yes | Yes | Unclear (sourceId dedup) | -- | Complements Lane 6 (claims-derived life events) |

## Missing Downstream Side Effects (Gaps)

| Gap | Description | Impact |
|-----|-------------|--------|
| Contact status advance | After interaction routing, contact status should advance (target/outreach_sent to active; cold/dormant to warm) | Contacts stay in stale status; cadence check and scoring use wrong state |
| Dossier synthesis | After routing completes, dossier should be re-synthesized for primary contact | Contact dossier stale; meeting prep and daily briefing use old narrative |
| Contact stub creation | Unresolved entities held as pending_entity but no stub created in NA | Pending routes never release until manual contact creation in NA |

## Idempotency Risk Summary

| Risk Level | Lanes | Issue |
|------------|-------|-------|
| Safe | 1, 1A, 5, 7, 8, 10, 10b, 10c, 11, 13, 15, 17 | sourceClaimId populated or inherent dedup |
| At Risk | 2, 3, 6, 14, 18 | sourceId only (no sourceClaimId); reroute may create duplicates |
| Dangerous | 16 (calendar_events) | No dedup key at all; reroute creates duplicate calendar events |
| Gated | 1B, 17 | Commitments/asks require sourceClaimId; skipped if absent (safe but may lose data) |

## Lane Count Summary
- **Total lanes**: 18 (+ 1A as sub-function of 1)
- **Core**: 6 (interaction, interaction_participants, scheduling_leads, standing_offers, graph_edges, policy_positions)
- **Secondary**: 12 (all others)
- **All currently fire**: Yes
- **All review-gated**: Yes (via mark_reviewed payload reconstruction)
- **Idempotent on reroute**: 12 safe, 5 at risk, 1 dangerous
