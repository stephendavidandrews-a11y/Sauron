# D4: Phase 0A Sanity Report

> Live-verified 2026-03-13 on Mac Mini. All automated checks pass.

---

## 1. Startup Migration Verification

**Method**: Cleared all `sauron/**/__pycache__/`, killed uvicorn, cold-restarted.

| Check | Result |
|-------|--------|
| `init_db()` runs on startup | ✅ `[MIGRATION] Schema tables created/verified` logged |
| `run_migration()` called after table creation | ✅ All v5-v24 migrations run sequentially |
| `_verify_schema()` validates 15 critical columns | ✅ All 15 present |
| No migration errors | ✅ Clean startup |

**Bug found and fixed**: v24 migration was not executing on restart because stale `__pycache__` was serving the pre-patch `migrate.pyc`. Root cause: earlier session applied the code change but did not clear bytecache before restarting. **Fix**: manually ran v24 + cleared pycache. Now verified across cold restart.

**Lesson**: Any code change to `sauron/db/migrate.py` or `sauron/db/schema.py` MUST be followed by `find sauron -name '__pycache__' -exec rm -rf {} +` before restart.

---

## 2. Critical Schema Assumptions

All 15 columns verified present in live DB:

| Table.Column | Status |
|-------------|--------|
| graph_edges.from_type | ✅ |
| graph_edges.to_type | ✅ |
| graph_edges.review_status | ✅ |
| routing_summaries.conversation_id | ✅ (TEXT - v24 applied) |
| routing_summaries.final_state | ✅ |
| event_claims.review_status | ✅ |
| event_claims.text_user_edited | ✅ |
| unified_contacts.networking_app_contact_id | ✅ |
| unified_contacts.relationships | ✅ |
| unified_contacts.current_title | ✅ |
| unified_contacts.current_organization | ✅ |
| conversations.reviewed_at | ✅ |
| conversations.routed_at | ✅ |
| transcripts.original_text | ✅ |
| transcripts.user_corrected | ✅ |

v24 evidence: `routing_summaries.id` = TEXT, `routing_summaries.conversation_id` = TEXT (was INTEGER). 6 existing rows preserved with CAST.

---

## 3. /people Graceful Degradation

**Endpoint**: `GET /api/conversations/{id}/people`
**Test**: Hit endpoint for conversation `016ed2e0-...` (6 claims).
**Result**: Returned 3 people, HTTP 200. The graph_edges query is wrapped in try/except; missing columns log a warning while other sources still return data.

---

## 4. Routing Architecture Confirmation

**Finding: Single-pass, review-gated. No dual-fire risk.**

| Call site | What happens |
|-----------|-------------|
| `processor.py` pipeline | Sets `awaiting_claim_review`, returns. `_run_routing()` at line 1552 is dead code (defined, zero callers). |
| `conversations.py` `mark_reviewed()` | Sole production trigger for `route_extraction()`. |

Grep evidence: `_run_routing(` appears in 1 file (processor.py), only in the `def` line. Never invoked.

---

## 5. Dedup Patch Verification

### 5a. Sauron-side (networking.py) - 24 sourceClaimId references

| Lane | Object | sourceClaimId format | ID type |
|------|--------|---------------------|---------|
| 1 | interaction | `sourceId` only (one per contact) | N/A - naturally unique |
| 1A | participant | `participant:primary:{id}` / `participant:{label}:{id}` | Synthetic |
| 2 | scheduling_lead | Real claim UUID | Real |
| 3 | standing_offer | Real claim UUID | Real |
| 6 | life_event | Real claim UUID | Real |
| 7 | commitment | `{conv_id}_claim_{NNN}` | Synthetic |
| 8 | intelligence_signal | `claim_{NNN}` | Synthetic |
| 9 | contact_relationship | `sorted(A,B):edge_type` (canonicalized) | Synthetic |
| 10 | interest | Real claim UUID via content match | Real |
| 10b | org_intel_signal | `claim_{NNN}` | Synthetic |
| 10c | what_changed_signal | None | No sourceClaimId |
| 11 | profile_signal | None | No sourceClaimId |
| 13 | provenance | `claim_{NNN}` | Synthetic |
| 14 | status_change_signal | `claim_{NNN}` | Synthetic |
| 15 | referenced_resource | Real claim UUID | Real |
| 16 | calendar_event | Real UUID or `cal:{title[:60]}` (TEMPORARY) | Real / Fallback |
| 17 | activity | None | No sourceClaimId |
| 18 | vocal_summary | None | No sourceClaimId |

### 5b. Networking App-side - 3 endpoint fixes

| Endpoint | Fix | Verified |
|----------|-----|----------|
| `POST /api/calendar/events` | Upsert via Google Calendar `extendedProperties`. Returns `action: 'created'/'updated'`. | Code review |
| `POST /api/contact-relationships` | `observationCount` only increments when `sourceId` differs. | Code review |
| `POST /api/personal/interests` | Tier 1 match (exact sourceClaimId) skips `mentionCount` increment. | Code review |

### 5c. Re-route Analysis (conversation e93b2569, 71 claims, 390 lane entries)

This conversation routed BEFORE 0A.4, showing pre-patch state:

| Object class | Entries | sourceClaimId | Re-route risk |
|-------------|---------|---------------|---------------|
| activity | 33 | None (pre-patch) | Would duplicate |
| commitment | 44 | Synthetic | Safe (upsert) |
| contact_relationship | 9 | None (pre-patch) | observationCount inflation |
| intelligence_signal | 37 | Synthetic | Safe (upsert) |
| interaction | 11 | N/A (one per contact) | Safe |
| interest | 31 | None (pre-patch) | mentionCount inflation |
| life_event | 13 | None (pre-patch) | Would duplicate |
| org_intel_signal | 18 | Synthetic | Safe (upsert) |
| profile_signal | 132 | None (pre-patch) | Would duplicate |
| provenance | 9 | Synthetic | Safe (upsert) |
| status_change_signal | 9 | Synthetic | Safe (upsert) |
| vocal_summary | 11 | None (pre-patch) | Would duplicate |
| what_changed_signal | 33 | None (pre-patch) | Would duplicate |

**Assessment**: Core dedup lanes (scheduling_leads, standing_offers, life_events, calendar_events, contact_relationships, interests) are now protected for new routes. Remaining lanes without sourceClaimId (activity, profile_signal, vocal_summary, what_changed_signal) are append-only signals — duplicates are cosmetically annoying but not data-corrupting.

---

## 6. Known Gaps (deferred)

1. **Lane 16 calendar title fallback** (`cal:{title[:60]}`) - temporary until extraction provides real claim IDs for calendar items
2. **Lanes 11, 17, 18** (profile_signal, activity, vocal_summary) - no sourceClaimId. Lower risk: append-only signals.
3. **Lane 10c** (what_changed_signal) - no sourceClaimId. Same assessment.
4. **Next.js rebuild needed** on Mac Mini for NA endpoint changes to take effect in production
5. **No live end-to-end re-route test** - first post-patch routing will serve as real integration test
6. **`__pycache__` discipline** - must clear after any code change to db/ modules

---

## 7. Files Modified in 0A

### Sauron
- `sauron/db/schema.py` - init_db + _verify_schema + routing_summaries TEXT types
- `sauron/db/migrate.py` - v24 migration + [MIGRATION] log prefixes
- `sauron/main.py` - startup log tag
- `sauron/api/conversations.py` - /people graceful degradation
- `sauron/routing/networking.py` - 8 sourceClaimId additions + Lane 9 canonicalization
- `tests/test_people_graph_degraded.py` - regression test

### Networking App
- `src/app/api/calendar/events/route.ts` - upsert via extendedProperties
- `src/app/api/contact-relationships/route.ts` - conditional observationCount
- `src/app/api/personal/interests/route.ts` - Tier 1 mentionCount fix

### Docs (docs/integration/)
- `networking-app.md` - living integration doc
- `D1-lane-inventory.md` - 18-lane inventory
- `D2-dedup-matrix.md` - dedup matrix
- `D2-dedup-patch-summary.md` - patch summary with real vs synthetic ID table
- `D4-0A-sanity-report.md` - this file

---

## 8. Verdict

**0A is complete.** Schema fixes verified live, routing confirmed single-pass, dedup patches in place. First post-patch mark-as-reviewed will serve as true integration test. Proceed to 0B stability extractions.
