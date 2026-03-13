# D5: Phase 0 Contract Report

> Final deliverable for Phase 0: Sauron-as-Sole-Brain Foundation.
> Completed 2026-03-13.

---

## 1. Executive Summary

Phase 0 established the integration foundation between Sauron (voice intelligence system) and the Networking App (CRM). All planned sub-phases (0A-0E) are complete. The system is stable, dedup-hardened, and documented for the volume increase when user starts at CFTC.

| Sub-phase | Status | Key outcome |
|-----------|--------|-------------|
| 0A Schema + Dedup | COMPLETE | v24 migration, 15-column verification, sourceClaimId on all critical lanes |
| 0B Stability Extractions | COMPLETE | networking.py -45%, conversations.py -70%, 4 new lane modules |
| 0C Missing Lanes | COMPLETE | Contact status advance (Lane 1C), firmness verified, dossier/stubs deferred |
| 0D Endpoint Contract | COMPLETE | All 18 endpoints audited with full contract documentation |
| 0E Contact Sync + Cleanup | COMPLETE | 405 contacts linked, email junk cleared |

---

## 2. Shared Objects Between Sauron and Networking App

| Object | Owner | Write Direction | Sauron Role | NA Role |
|--------|-------|----------------|-------------|---------|
| Contact | NA | NA creates, Sauron reads + patches | Enriches flat fields (null-only), advances status | Source of truth, full CRUD |
| Interaction | Shared | Sauron creates via routing | Creates from voice conversations | Stores, displays, links to commitments |
| InteractionParticipant | Sauron | Sauron creates | Registers speakers as participants | Stores, displays |
| Commitment | Shared | Sauron creates, NA manages lifecycle | Creates from extraction, includes firmness | Tracks fulfillment, snooze, due dates |
| SchedulingLead | Sauron | Sauron creates | Extracts from conversations | Displays, user manages |
| StandingOffer | Sauron | Sauron creates | Extracts from conversations | Displays, user manages |
| IntelligenceSignal | Sauron | Sauron creates | Extracts what-changed, status-change signals | Displays, feeds dossier |
| LifeEvent | Sauron | Sauron creates | Extracts birthdays, milestones | Displays, feeds dossier |
| PersonalInterest | Sauron | Sauron creates | Extracts hobbies, topics | Displays with mention count |
| PersonalActivity | Sauron | Sauron creates | Extracts activities mentioned | Displays |
| ContactRelationship | Sauron | Sauron creates | Extracts interpersonal connections | Displays network graph |
| ContactProvenance | Sauron | Sauron creates | Records how contacts were introduced | Displays relationship origin |
| ContactProfileSignal | Sauron | Sauron creates | Vocal analysis, sentiment, deltas | Feeds dossier synthesis |
| ContactAffiliation | Shared | Sauron creates, NA resolves org | Creates from extraction, org resolved by NA | Stores, syncs to flat contact fields |
| OrganizationSignal | Sauron | Sauron creates | Extracts org-level intel | Displays, feeds dossier |
| ReferencedResource | Sauron | Sauron creates | Extracts book/article/tool mentions | Displays |
| CalendarEvent | Shared | Sauron creates via Google API | Routes scheduling leads to calendar | Google Calendar is backend |
| Dossier | NA | NA generates | NOT currently triggered by Sauron (deferred) | Claude Sonnet 4 synthesis |

---

## 3. Dedup Key Per Object

| Object | Dedup Key | Mechanism |
|--------|-----------|-----------|
| Interaction | sourceSystem + sourceId | findFirst upsert |
| InteractionParticipant | interactionId + contactId | Compound unique |
| Commitment | sourceSystem + sourceId + sourceClaimId | Full triple upsert |
| SchedulingLead | sourceSystem + sourceId | findFirst upsert (real claim UUID in sourceId) |
| StandingOffer | sourceSystem + sourceId | findFirst upsert (real claim UUID in sourceId) |
| IntelligenceSignal | Tier 1: full triple. Tier 2: content match | 2-tier dedup |
| LifeEvent | sourceSystem + sourceId | findFirst upsert (real claim UUID in sourceId) |
| PersonalInterest | Tier 1: full triple (no count increment). Tier 2: content match (increment) | 2-tier with count protection |
| PersonalActivity | Tier 1: full triple. Tier 2: content match | 2-tier dedup |
| ContactRelationship | contactAId + contactBId (bidirectional) | Structural + conditional count |
| ContactProvenance | 4-tier: full triple > person-introduced > non-person > create | 4-tier cascade |
| ContactProfileSignal | Tier 1: full triple. Tier 2: conversation-based | 2-tier dedup |
| ContactAffiliation | Tier 1: full triple. Tier 2: contact+org+conversation | 2-tier dedup |
| OrganizationSignal | Tier 1: full triple. Tier 2: content match | 2-tier dedup |
| ReferencedResource | Full triple only | No content fallback |
| CalendarEvent | Full triple via extendedProperties | Google Calendar API search |
| Contact (PATCH) | By ID | Idempotent PATCH |

---

## 4. Reroute/Reprocess Behavior

All 18 lanes are idempotent on reroute when sourceClaimId is populated. Summary:

| Category | Lanes | Behavior on reroute |
|----------|-------|-------------------|
| Full upsert (update existing) | Commitments, signals, interests, activities, provenance, profile-signals, affiliations, org-signals, resources, calendar | Updates in place, no duplicates |
| Structural dedup | Participants, relationships | Returns existing record |
| Source-level upsert | Interactions, scheduling-leads, standing-offers, life-events | Upserts by sourceId (real claim UUID) |
| PATCH | Contacts | Idempotent by nature |
| Not called | Dossier | Deferred (0C.2) |

---

## 5. Review Gate

**Confirmed**: Routing fires ONLY on Mark as Reviewed.

- Pipeline sets conversation status to `awaiting_claim_review` and stops
- `_run_routing()` in processor.py is dead code (marked with comment, zero callers)
- `mark_reviewed()` in `sauron/api/review_actions.py` is the sole production trigger for `route_extraction()`
- This is a permanent design choice, not a temporary gate

---

## 6. Unresolved-Entity Behavior

When a claim references a person not yet in unified_contacts:

1. Entity resolver attempts match against canonical_name + aliases
2. If no match: entity marked as unresolved, routing_log entry created with status `pending_entity`
3. On next contact sync (when NA creates the contact), `release_pending_routes()` fires for any newly-linked entities
4. Contact stub auto-creation was considered (0C.3) and explicitly dropped — NA remains source of truth

---

## 7. Files Modified Across Phase 0

### New files created
| File | Lines | Purpose |
|------|-------|---------|
| sauron/routing/lanes/__init__.py | 0 | Package marker |
| sauron/routing/lanes/core.py | 115 | RoutingSummary, _api_call, _store_routing_summary |
| sauron/routing/lanes/entity_resolution.py | 124 | Entity resolution helpers |
| sauron/routing/lanes/signals.py | 370 | Lanes 13-15 (provenance, profile intel, affiliations) |
| sauron/routing/lanes/commitments.py | 387 | Lanes 1A-1B, 5 (participants, commitments, contact patch) |
| sauron/api/people_endpoints.py | 565 | People review endpoints |
| sauron/api/review_actions.py | 158 | Flag, discard, mark-as-reviewed |
| sauron/api/routing_preview.py | 171 | Routing preview endpoint |
| sauron/api/bulk_reassign.py | 272 | Bulk reassign (isolated, unused) |
| tests/test_people_graph_degraded.py | 164 | Regression test |
| docs/integration/networking-app.md | — | Living integration doc |
| docs/integration/D1-lane-inventory.md | — | 18-lane inventory |
| docs/integration/D2-dedup-matrix.md | — | Dedup matrix |
| docs/integration/D2-dedup-patch-summary.md | — | Patch summary |
| docs/integration/D3-endpoint-contract-table.md | — | Endpoint contracts (all 18) |
| docs/integration/D4-0A-sanity-report.md | — | Post-0A verification |
| docs/integration/D6-0C-completion-report.md | — | 0C completion with dossier deep dive |

### Modified files
| File | Before | After | Change |
|------|--------|-------|--------|
| sauron/routing/networking.py | 2042 | ~1210 | -40%, extracted lanes, added status advance |
| sauron/api/conversations.py | 1576 | 470 | -70%, extracted 4 sub-routers |
| sauron/db/schema.py | — | — | init_db + _verify_schema + TEXT types |
| sauron/db/migrate.py | — | — | v24 migration + [MIGRATION] logs |
| sauron/main.py | — | — | Startup log tag |
| sauron/api/graph.py | — | — | Fixed stale import |
| sauron/pipeline/processor.py | — | — | Dead code comment on _run_routing() |
| .gitignore | — | — | Added *.bak |

### Networking App files modified (not committed in NA repo)
| File | Change |
|------|--------|
| src/app/api/calendar/events/route.ts | Upsert via extendedProperties |
| src/app/api/contact-relationships/route.ts | Conditional observationCount |
| src/app/api/personal/interests/route.ts | Tier 1 mentionCount skip |

---

## 8. Deferred Items

| Item | Reason | When to revisit |
|------|--------|----------------|
| 0C.2 Dossier trigger from Sauron | User wants to design trigger logic ("after enough new information") | Phase 1+ |
| 0C.3 Contact stub creation | Dropped — "all risk and no reward" | Not planned |
| Commitment "ordered/promised" tier | Needs extraction schema + NA model update | Phase 1+ |
| Calendar title fallback (cal:{title[:60]}) | Temporary until extraction provides real claim IDs for calendar | Next extraction schema update |
| Null-only guard server-side on PATCH | Currently client-side in Sauron only | When other callers emerge |
| processor.py extraction (0B.2) | Only networking.py and conversations.py extracted; processor deferred until after text/email ingestion settles | Phase 3 |
| ConversationDetail.jsx extraction (0B.4) | Frontend extraction deferred — backend was priority | Phase 3 |

---

## 9. Known Gotchas

1. **__pycache__ discipline**: Any code change to db/ modules MUST be followed by cache clear before restart
2. **Org resolution failures**: Affiliations and org-signals lanes return 422 when org name doesn't resolve. Sauron logs these as secondary lane failures
3. **Email coverage**: 58% of contacts missing email — will impact future email entity resolution
4. **Dead code**: `_run_routing()` in processor.py is retained for reference but should be deleted in Phase 1
5. **bulk_reassign.py**: Isolated but unused — user said "i never use it". Delete candidate

---

## 10. Verification Checklist

| Check | Status |
|-------|--------|
| App startup — migrations run cleanly | PASS (v24 applied, 15 columns verified) |
| /people endpoint — returns 200, no graph-edge crash | PASS |
| Reroute idempotent — no duplicates | PASS (per D4 sanity report) |
| Routing single-pass, review-gated | CONFIRMED |
| 18 endpoint contracts documented | PASS (D3) |
| Contact sync — 405 contacts linked | PASS |
| Email junk cleared | PASS (475 dismissed) |
| Full app import — 133 routes | PASS |
| Integration doc complete | PASS (networking-app.md + 6 deliverables) |

---

## 11. What's Next

Phase 0 is complete. The foundation is solid for:
- **Phase 1**: Text ingestion in Sauron (add text as source type alongside voice)
- **Phase 2**: Email ingestion in Sauron
- **Phase 3**: Full module refactoring (after ingestion patterns settle)
