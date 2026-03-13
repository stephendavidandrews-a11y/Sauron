# Sauron - Networking App Integration Contract

> Living document. Updated as decisions are made during Phase 0.
> Last updated: 2026-03-13

## 1. Ownership Map

| Domain | System of Record | Reader(s) | Notes |
|--------|-----------------|-----------|-------|
| Contact identity and metadata | Networking App | Sauron (sync) | 405 contacts; Sauron syncs 391 (14 gap under investigation) |
| Organizations and affiliations | Networking App | Sauron (cache) | Sauron sends name strings; NA resolves to org records |
| Conversation transcripts and audio | Sauron | -- | Source files on Mac Mini |
| Claims and beliefs | Sauron | Networking App (routed subset) | Only reviewed claims route |
| Interaction records | Networking App | -- | Sauron creates via routing; NA stores |
| Commitments | Networking App (stores) | Sauron (creates) | Firmness field: concrete/intentional/social/tentative |
| Signals / life events / offers | Networking App (stores) | Sauron (creates) | |
| Contact relationships (graph) | Networking App (stores + enriches) | Sauron (creates) | |
| Calendar | Google Calendar | Both (read-only) | |
| Email content | Networking App (IMAP) | Future: Sauron | Phase 2 migration |
| Text/iMessage content | Networking App (bulk import) | Future: Sauron | Phase 1 migration |

## 2. Integration Contracts

### Routing Rules
- **Review-gated**: Nothing leaves Sauron until Mark as Reviewed
- **Null-only patching**: Sauron never overwrites populated contact fields (Lane 5)
- **User corrections sacred**: review_status=user_corrected or link_source=user never overwritten by pipeline
- **Org resolution is NA's job**: Sauron sends organization name strings, NA resolves via orgResolver (5-step)

### Dedup Rules
- **Upsert triple**: (sourceSystem, sourceId, sourceClaimId) is the dedup key
- sourceSystem = always "sauron"
- sourceId = conversation UUID
- sourceClaimId = claim UUID (for claim-derived records) or composite key (for non-claim records)
- See Dedup Matrix (Section 3) for per-lane details

### Contact Stub Creation Rules
- Only after Mark as Reviewed (never during pipeline)
- Only for entities in 2+ reviewed claims with confidence > 0.7
- Check NA by name (case-insensitive) before creating; link if match found
- Always tier-3 / status="mentioned" / source="sauron"
- Minimum fields: name (required). Optional: organization, title
- After creation: update unified_contacts.networking_app_contact_id, release pending routes
- Idempotent: if stub exists (same name + source=sauron), link, don't create

## 3. Dedup Matrix

> To be produced before 0A.4 implementation. Will be a lane-by-lane table.

*Placeholder -- see D2 deliverable*

## 4. Endpoint Contract Table

> To be produced during 0D. Per-endpoint documentation from code inspection.

*Placeholder -- see D3 deliverable*

## 5. Known Gotchas

| # | Issue | Status | Resolution |
|---|-------|--------|------------|
| 1 | Speaker linked to wrong contact (calendar inference outranked weak voiceprint) | Known | Verification gate in entity_resolver.py |
| 2 | Entity routed before review | Fixed | Hold-until-review is permanent default |
| 3 | Stale org field overwrote newer local correction | Fixed | Null-only patching |
| 4 | First-name-only match caused false entity resolution | Fixed | Verification gate added |
| 5 | Networking App port was 3000 in config but 3001 in reality | Fixed | Config corrected |
| 6 | routing_summaries.conversation_id is INTEGER but conversations.id is TEXT | Open | Fix in 0A.2 |
| 7 | sourceClaimId not populated in all routing lanes | Open | Fix in 0A.4 |
| 8 | /people endpoint crashes on missing graph_edges columns | Open | Fix in 0A.3 |
| 9 | 14 contacts don't sync (405 NA vs 391 Sauron) | Open | Investigate in 0E.1 |
