# Post-Extraction Enrichment Pass — Design Document

**Created**: 2026-03-13
**Status**: Designed, partially implemented
**Location**: Run after claim extraction, before review queue

## Overview

After claims are extracted from a text or voice cluster, a lightweight enrichment
pass runs to resolve information that the extraction model couldn't determine from
the cluster transcript alone. This pass uses Sauron's accumulated knowledge base
(prior claims, beliefs, contacts, calendar data) to fill gaps.

## Enrichment Categories

### 1. Contextual Date Resolution

**Problem**: Commitments reference relative dates ("after the recess", "when I get
back") that depend on information not in the current cluster.

**Approach**:
- Query `event_claims` for travel/schedule facts about the commitment's subject
- Query external reference tables (congressional calendar, CFTC calendar)
- If a matching fact is found, upgrade `date_confidence` from `conditional` → `approximate` or `exact`
- Log the enrichment source for auditability

**Example**: Commitment says "when I get back" by Stephen. Sauron has a prior claim
"Stephen is traveling to DC, returning March 18." → Resolve `due_date` to 2026-03-18,
`date_confidence` to `approximate`, `date_note` to "resolved from travel claim [claim_id]".

### 2. Compound/Conditional Commitment Resolution

**Problem**: Commitments have conditions ("after we talk to Schmitt"). When a later
cluster contains evidence that the condition was met, the commitment should be
flagged for upgrade.

**Approach**:
- After extracting claims from a new cluster, query all `date_confidence: conditional`
  commitments from the database
- For each, semantic-search the new cluster's claims against the `condition_trigger` text
- If similarity exceeds threshold (0.70), create a `condition_match` record
- Surface in review UI: "Condition may be met — [new claim] matches [conditional commitment]"
- On review approval: upgrade `date_confidence`, set `due_date` if resolvable

**Module**: `sauron/extraction/condition_checker.py`

### 3. Entity Name Resolution (Thread-Context Memory)

**Problem**: First-name-only references ("Ethan") can't be resolved at extraction
time without prior context about who participates in this thread.

**Approach**:
- Maintain a `thread_entity_memory` table: (thread_id, short_name, resolved_contact_id, confidence, last_confirmed)
- After a reviewer confirms "Ethan" = "Ethan Harper" in the Hawley Legal thread,
  store that mapping
- On future extractions from the same thread, check thread_entity_memory before
  flagging as a new contact
- Decay: if a mapping hasn't been confirmed in 90 days, lower confidence but don't delete

**Cross-thread generalization** (Phase 3+):
- Once org entities exist, promote thread-level mappings to org-level:
  "Ethan" in any thread involving Hawley's office members → Ethan Harper
- Without orgs: frequency-based generalization (if "Ethan" → "Ethan Harper" in 4+ threads,
  suggest globally)

### 4. Abbreviation Expansion (Lookup Table)

**Problem**: WH, OLA, CFTC, etc. appear in claims without expansion.

**Approach**:
- Maintain an `abbreviation_guide` table or JSON config: {"WH": "White House", "OLA": "Office of Legislative Affairs", ...}
- Post-extraction: scan claim_text for known abbreviations, expand in-place
- No model tokens spent — pure string replacement
- User-editable via review UI or admin config

### 5. Subject Matter Linking

**Problem**: Claims about "the amendment" lose context about which bill/project/deal
they relate to.

**Approach**:
- The extraction prompt is tuned to include subject matter context in claim_text
- Post-extraction: if claim_text mentions a project/bill/event, check for a
  matching `topic` tag from triage or prior claims
- Store topic linkage for search and filtering

## Execution Order

```
Cluster → Triage → Extraction → [Enrichment Pass] → Review Queue
                                    ├── Date resolution
                                    ├── Condition checking
                                    ├── Entity memory lookup
                                    ├── Abbreviation expansion
                                    └── Subject matter linking
```

## Implementation Phasing

| Component | Status | Phase |
|-----------|--------|-------|
| Condition checker module | Building now | Phase 1 |
| Date resolution (from cluster context) | In extraction prompt | Phase 1 |
| Date resolution (from knowledge base) | Designed | Phase 2+ |
| Thread entity memory | Designed | Phase 2 |
| Abbreviation expansion | Designed | Phase 2 |
| Cross-thread entity generalization | Designed | Phase 3 (with orgs) |
| Subject matter linking (from prompt) | In extraction prompt | Phase 1 |
| Subject matter linking (post-extraction) | Designed | Phase 2 |
