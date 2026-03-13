# D2 Addendum: Post-Dedup Patch Summary

> Phase 0 — Applied 2026-03-13. Covers all Sauron-side sourceClaimId additions and Networking App endpoint fixes.

## Sauron-Side Patches (networking.py)

### Real Claim IDs (passed through from extraction)

| Lane | Field | Source | Notes |
|------|-------|--------|-------|
| 2a | `lead.get("source_claim_id")` | Extraction JSON | Real claim ID from Sonnet output. Null if extraction doesn't populate it. |
| 2b | `c.get("source_claim_id")` | Extraction JSON | Social-firmness commitments promoted to scheduling leads. Same provenance. |
| 3 | `offer.get("source_claim_id")` | Extraction JSON | Standing offers from Sonnet. Real claim ID. |
| 6 | `mw.get("claim_id")` | Memory writes | Life events derived from claims. Real claim ID. |
| 7, 8, 10, 10b, 10c, 11, 13, 15, 17, 18 | Already had sourceClaimId | — | No change needed. |

### Synthetic/Composite IDs (constructed by routing code)

| Lane | Pattern | Construction | Temporary? | Risk |
|------|---------|-------------|-----------|------|
| 9 | `"{sorted_A}:{sorted_B}:{edge_type}"` | Canonicalized: `sorted([from_name, to_name])` + edge_type | **No** — deterministic, stable | Names could change across conversations if LLM uses different forms (e.g., "Steve" vs "Stephen"). Resolved contact IDs would be more stable but NA doesn't accept sourceClaimId on this model yet. |
| 16 | `cal_event.get("source_claim_id")` with fallback `f"cal:{title[:60]}"` | Real ID preferred; title fallback if absent | **YES — title fallback is temporary** | Title truncation could collide for similar events. Real claim IDs should flow once extraction schemas include calendar event claim IDs. |
| 1A (primary) | `f"participant:primary:{contact_id}"` | Prefix + resolved contact UUID | **No** — deterministic | Stable as long as contact resolution is consistent. |
| 1A (speakers) | `f"participant:{speaker_label}:{contact_id}"` | Prefix + speaker label + contact UUID | **No** — deterministic | Speaker labels (SPEAKER_00 etc.) are session-specific. Same person could get different labels across conversations. Contact ID provides the real anchor. |

### Directionality Note (Lane 9)

Graph edges from LLM extraction have **no guaranteed direction** — "Alice:Bob:knows" and "Bob:Alice:knows" represent the same relationship. The Networking App's contact-relationships endpoint already matches bidirectionally (`(A,B) OR (B,A)`), so the sourceClaimId is **canonicalized** with `sorted()` to produce a consistent key regardless of extraction direction. This is correct for the current symmetric relationship model. If asymmetric relationships are needed later (e.g., "reports_to"), the canonicalization should be limited to symmetric edge types only.

## Networking App Endpoint Fixes

### Lane 16: Calendar Events (CRITICAL → FIXED)
**File**: `src/app/api/calendar/events/route.ts`
- Added: upsert via Google Calendar `extendedProperties.private` storing `{sourceSystem, sourceId, sourceClaimId}`
- Before insert: searches existing events with `privateExtendedProperty` filter
- If match found: updates existing event instead of creating duplicate
- If no source triple provided: falls back to original insert-only behavior (backward compatible)
- **Limitation**: Google Calendar API `privateExtendedProperty` search is eventually consistent — extremely rapid re-sends (sub-second) could theoretically miss a match. Acceptable for review-gated routing.

### Lane 9: Contact Relationships (HIGH → FIXED)
**File**: `src/app/api/contact-relationships/route.ts`
- Added: `isSameSource` check — if existing record's `sourceId` matches incoming `sourceId`, skip `observationCount` increment
- Logic: `isSameSource ? existingPair.observationCount : { increment: 1 }`
- Why `sourceId` not `sourceClaimId`: the ContactRelationship Prisma model has no `sourceClaimId` column. The `sourceId` (conversation_id) is sufficient because routing fires once per conversation.
- **Future work**: Add `sourceClaimId` to ContactRelationship Prisma schema for full triple-based dedup if multi-edge-per-conversation scenarios arise.

### Lane 10: Interests (HIGH → FIXED)
**File**: `src/app/api/personal/interests/route.ts`
- Changed: Tier 1 match (exact sourceClaimId) no longer increments `mentionCount`
- Before: `mentionCount: existing.mentionCount + 1`
- After: `mentionCount: existing.mentionCount`
- Rationale: Tier 1 matches on the exact `(sourceSystem, sourceId, sourceClaimId)` triple — this IS a re-send, not a new mention. Tier 2 (content match, different claim) still increments correctly.

## Remaining Work

### Lanes that still lack true endpoint-side sourceClaimId support

| Lane | Model | Issue | Priority |
|------|-------|-------|----------|
| 9 | ContactRelationship | No `sourceClaimId` column in Prisma schema. Sauron sends it but NA drops it. Dedup works via (A,B) pair + sourceId check. | Low — works today, schema change only needed if multi-edge-per-conversation. |
| 1A | Interaction participants | NA endpoint unknown structure for participant dedup. Synthetic IDs sent but may be dropped. | Low — single-pass architecture makes collision unlikely. |

### Calendar title fallback — TODO

Lane 16's `f"cal:{title[:60]}"` fallback fires when extraction doesn't produce a `source_claim_id` for calendar events. This is a known gap:
- The extraction schema (`sauron/extraction/schemas.py`) should be updated to include `claim_id` on calendar event outputs
- Once real claim IDs flow, the title fallback becomes dead code
- Until then, the fallback provides reasonable (but not collision-proof) dedup

### Items NOT in scope for this patch

- Lane 1 (Interaction): single record per conversation, natural dedup on sourceId. No fix needed.
- Lane 14 (Profile Intelligence): PATCH /api/contacts/{id} with null-only writes. Idempotent by design.
- Lanes with existing sourceClaimId (1B, 7, 8, 10b, 10c, 11, 13, 15, 17, 18): Already safe.

## Test Plan

1. **Smoke test**: Process a known conversation through mark_reviewed. Verify no errors in routing log.
2. **Re-review test**: Mark same conversation as reviewed again. Verify:
   - No duplicate Google Calendar events created
   - observationCount on contact-relationships does NOT increment
   - mentionCount on interests (Tier 1 match) does NOT increment
   - mentionCount on interests (Tier 2 / different conversation) DOES increment
3. **New conversation test**: Process a new conversation mentioning same people/interests. Verify counters DO increment (different sourceId).
