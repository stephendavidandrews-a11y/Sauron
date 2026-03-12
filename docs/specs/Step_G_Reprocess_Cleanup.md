# Step G Follow-Up: Historical Reprocess Cleanup

## Status
Deferred — not a blocker for Category 3 sign-off.

## Problem
Conversations processed before Step G have ordinal claim IDs (`claim_001`, `claim_002`).
Reprocessing those conversations now produces content-hash IDs (`claim_a1b2c3d4e5f6`).
Because `_store_claims()` uses `INSERT OR IGNORE`, old ordinal claims remain alongside
new hash claims — creating duplicate claim sets for the same conversation.

## Scope
- 353 existing `event_claims` with ordinal IDs
- 431 linked `claim_entities`
- 363 linked `belief_evidence` records
- 315 `correction_events` referencing ordinal IDs (audit trail, not active links)

## Fix
In `sauron/pipeline/processor.py`, function `_store_claims()`:

1. Before the INSERT loop, delete old claims for the conversation:
   ```python
   # Clean old claims on reprocess (Step G follow-up)
   conn.execute("DELETE FROM event_claims WHERE conversation_id = ?", (conversation_id,))
   ```
2. `claim_entities` will CASCADE-delete automatically (FK constraint).
3. `belief_evidence` references will become dangling — add a post-cleanup:
   ```python
   conn.execute("DELETE FROM belief_evidence WHERE claim_id NOT IN (SELECT id FROM event_claims)")
   ```
4. `correction_events.claim_id` has no FK — historical audit records remain (correct behavior).

## When to Apply
Before the next planned reprocess cycle. Not urgent for new-only processing.

## Risk
Low. CASCADE handles entity links. Belief evidence cleanup is a simple orphan sweep.
Correction events are preserved as historical audit trail.
