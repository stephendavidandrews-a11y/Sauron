# D3: Endpoint Contract Table

> Produced during Phase 0D from actual code inspection of all 18 Networking App endpoints.
> Verified 2026-03-13.

---

## Summary

| Metric | Count |
|--------|-------|
| Total endpoints | 18 |
| Full triple dedup (sourceSystem+sourceId+sourceClaimId) | 10 |
| Partial dedup (sourceSystem+sourceId only) | 4 |
| Content-based dedup fallback | 8 |
| No dedup (pure create or PATCH) | 3 |
| Org resolution via resolveOrganization() | 2 |
| Google Calendar API (not Prisma) | 1 |

---

## Contract Table

### 1. POST /api/interactions

| Field | Value |
|-------|-------|
| **Prisma model** | Interaction |
| **Semantics** | Upsert on (sourceSystem, sourceId); else create |
| **Required fields** | contactId |
| **Optional fields** | type, date, summary, commitments (JSON array), sentiment, relationshipDelta, relationshipNotes, topicsDiscussed, source, followUpRequired, followUpDescription, newContactsMentioned, sourceSystem, sourceId |
| **Dedup rule** | findFirst(sourceSystem + sourceId). On match: update summary/sentiment/etc, delete+recreate child Commitment rows from same source |
| **Triple check** | Partial — sourceClaimId NOT checked at interaction level (checked on child commitments) |
| **Null handling** | `body.field \|\| undefined` on update (skips nulls), `body.field \|\| null` on create |
| **Idempotent on reroute** | YES — upserts interaction, replaces commitments |
| **Side effects** | Updates contact.lastInteractionDate; dual-writes to Commitment table |
| **Risks** | No sourceClaimId on the interaction itself (only on child commitments). Commitment deleteMany+recreate is safe but lossy if user manually edited a commitment between routes |
| **Code location** | src/app/api/interactions/route.ts |

### 2. POST /api/interaction-participants

| Field | Value |
|-------|-------|
| **Prisma model** | InteractionParticipant |
| **Semantics** | Idempotent create on (interactionId, contactId) compound unique |
| **Required fields** | interactionId, contactId |
| **Optional fields** | role (default "participant"), speakerLabel, sourceSystem, sourceId |
| **Dedup rule** | findUnique on compound key interactionId_contactId. If exists, returns existing with action: "existing" |
| **Triple check** | NO — dedup is structural (one participant per contact per interaction) |
| **Null handling** | role defaults to "participant", others null |
| **Idempotent on reroute** | YES — returns existing record |
| **Risks** | None significant |
| **Code location** | src/app/api/interaction-participants/route.ts |

### 3. POST /api/commitments

| Field | Value |
|-------|-------|
| **Prisma model** | Commitment |
| **Semantics** | Upsert on full triple (sourceSystem+sourceId+sourceClaimId); else create |
| **Required fields** | contactId (or contactName for resolution), description |
| **Optional fields** | interactionId, dueDate, direction, kind, firmness, sourceSystem, sourceId, sourceClaimId |
| **Dedup rule** | findFirst(sourceSystem + sourceId + sourceClaimId). On match: update description/dueDate/direction/kind/firmness. If no interactionId provided, resolves from existing Sauron interaction by sourceId |
| **Triple check** | YES — full triple |
| **Null handling** | `body.field ?? existing.field` on update (preserves existing); `body.field \|\| null` on create |
| **Idempotent on reroute** | YES |
| **Risks** | interactionId resolution by sourceId could fail if interaction was deleted. firmness field properly flows through |
| **Code location** | src/app/api/commitments/route.ts |

### 4. POST /api/scheduling-leads

| Field | Value |
|-------|-------|
| **Prisma model** | SchedulingLead |
| **Semantics** | Upsert on (sourceSystem, sourceId); else create |
| **Required fields** | contactId (or contactName) |
| **Optional fields** | description, originalWords, timeframe, sourceSystem, sourceId |
| **Dedup rule** | findFirst(sourceSystem + sourceId). On match: update description/originalWords/timeframe |
| **Triple check** | NO — sourceClaimId not checked (uses sourceId = real claim UUID from Sauron) |
| **Null handling** | `body.field \|\| existing.field` on update |
| **Idempotent on reroute** | YES — but only deduped at conversation level (sourceId), not claim level |
| **Risks** | If two scheduling leads from same conversation have different sourceClaimIds, only the first one persists. However, Sauron sends real claim UUIDs as sourceId for this lane, so this is effectively claim-level dedup |
| **Code location** | src/app/api/scheduling-leads/route.ts |

### 5. POST /api/standing-offers

| Field | Value |
|-------|-------|
| **Prisma model** | StandingOffer |
| **Semantics** | Upsert on (sourceSystem, sourceId); else create |
| **Required fields** | contactId (or contactName) |
| **Optional fields** | description, offeredBy, originalWords, sourceSystem, sourceId |
| **Dedup rule** | findFirst(sourceSystem + sourceId). On match: update description/offeredBy/originalWords |
| **Triple check** | NO — same pattern as scheduling-leads (real claim UUID in sourceId) |
| **Null handling** | `body.field \|\| existing.field` on update |
| **Idempotent on reroute** | YES |
| **Risks** | Same as scheduling-leads — effectively claim-level via real UUID in sourceId |
| **Code location** | src/app/api/standing-offers/route.ts |

### 6. POST /api/signals

| Field | Value |
|-------|-------|
| **Prisma model** | IntelligenceSignal |
| **Semantics** | 3-tier dedup: (1) full triple, (2) content-based (contactId+signalType+title+sourceSystem+sourceId), (3) create |
| **Required fields** | contactId, signalType, title |
| **Optional fields** | description, sourceUrl, sourceName, outreachHook, relevanceScore, sourceSystem, sourceId, sourceClaimId |
| **Dedup rule** | Tier 1: full triple. Tier 2: content match within same conversation. Tier 3: create |
| **Triple check** | YES (Tier 1) |
| **Null handling** | `body.field ?? existing.field` on update |
| **Idempotent on reroute** | YES — robust 2-tier dedup |
| **Risks** | None significant. Returns action: "created"/"updated" for observability |
| **Code location** | src/app/api/signals/route.ts |

### 7. PATCH /api/contacts/[id]

| Field | Value |
|-------|-------|
| **Prisma model** | Contact |
| **Semantics** | Partial update — only updates fields explicitly provided in body |
| **Required fields** | At least one allowed field |
| **Optional fields** | name, title, organization, email, phone, linkedinUrl, twitterHandle, personalWebsite, tier, categories, tags, targetCadenceDays, status, contactType, introductionPathway, connectionToHawleyOrbit, whyTheyMatter, notes |
| **Dedup rule** | N/A — updates by ID |
| **Triple check** | N/A |
| **Null handling** | Only updates fields present in body. Sauron uses null-only patching (checks before sending). The endpoint itself does NOT enforce null-only — it will overwrite |
| **Idempotent on reroute** | YES — same PATCH produces same result |
| **Risks** | No null-only guard on NA side. Sauron's _update_contact_field_null_only does the guard client-side. If another caller PATCHes without checking, it could overwrite |
| **Code location** | src/app/api/contacts/[id]/route.ts |

### 8. POST /api/contacts/[id]/life-events

| Field | Value |
|-------|-------|
| **Prisma model** | LifeEvent |
| **Semantics** | Upsert on (sourceSystem, sourceId); else create |
| **Required fields** | description (via body), contactId (via URL) |
| **Optional fields** | person, eventDate/date, recurring, sourceSystem, sourceId |
| **Dedup rule** | findFirst(sourceSystem + sourceId). On match: update description/person/eventDate/recurring |
| **Triple check** | NO — sourceClaimId not checked (Sauron sends real claim UUID as sourceId) |
| **Null handling** | `body.field \|\| existing.field` on update |
| **Idempotent on reroute** | YES |
| **Risks** | Same conversation-level dedup as scheduling-leads. Real claim UUID in sourceId makes this effectively claim-level |
| **Code location** | src/app/api/contacts/[id]/life-events/route.ts |

### 9. POST /api/personal/interests

| Field | Value |
|-------|-------|
| **Prisma model** | PersonalInterest |
| **Semantics** | 3-tier dedup: (1) full triple (no mentionCount increment), (2) content-based (increment mentionCount), (3) create |
| **Required fields** | contactId, interest |
| **Optional fields** | confidence, source, sourceSystem, sourceId, sourceClaimId |
| **Dedup rule** | Tier 1: full triple — updates text/confidence, does NOT increment mentionCount (re-send protection). Tier 2: content match — increments mentionCount. Tier 3: create |
| **Triple check** | YES (Tier 1) |
| **Null handling** | `body.field \|\| existing.field` on update |
| **Idempotent on reroute** | YES — Tier 1 prevents count inflation on exact re-send |
| **Risks** | None. Phase 0A fix applied correctly |
| **Code location** | src/app/api/personal/interests/route.ts |

### 10. POST /api/personal/activities

| Field | Value |
|-------|-------|
| **Prisma model** | PersonalActivity |
| **Semantics** | 3-tier dedup: (1) full triple, (2) content-based, (3) create |
| **Required fields** | contactId, activity |
| **Optional fields** | frequency, confidence, source, sourceSystem, sourceId, sourceClaimId |
| **Dedup rule** | Tier 1: full triple. Tier 2: content match (same activity text + conversation). Tier 3: create |
| **Triple check** | YES (Tier 1) |
| **Null handling** | Updates activity text and confidence on Tier 1; only lastMentioned on Tier 2 |
| **Idempotent on reroute** | YES |
| **Risks** | Sauron does NOT currently send sourceClaimId for activities (Lane 17). Falls back to Tier 2 content match |
| **Code location** | src/app/api/personal/activities/route.ts |

### 11. POST /api/contact-relationships

| Field | Value |
|-------|-------|
| **Prisma model** | ContactRelationship |
| **Semantics** | Upsert on (contactAId, contactBId) pair (checks both orderings); else create |
| **Required fields** | contactAId, contactBId |
| **Optional fields** | relationshipType, strength, source, notes, observationSource, sourceSystem, sourceId |
| **Dedup rule** | findFirst(A,B OR B,A). On match: update fields + conditional observationCount increment (skip if same sourceId = re-send from same conversation) |
| **Triple check** | NO — dedup is structural (one relationship per contact pair). sourceClaimId not stored |
| **Null handling** | `body.field \|\| existing.field` on update |
| **Idempotent on reroute** | YES — observationCount skip on same sourceId prevents inflation |
| **Risks** | No sourceClaimId column on ContactRelationship model. Dedup is by contact pair which is correct for this domain |
| **Code location** | src/app/api/contact-relationships/route.ts |

### 12. POST /api/contact-provenance

| Field | Value |
|-------|-------|
| **Prisma model** | ContactProvenance |
| **Semantics** | 4-tier dedup: (1) full triple, (2) person-introduced (contactId+sourceContactId+type+sourceId), (3) non-person (contactId+type+sourceId), (4) create |
| **Required fields** | contactId, type |
| **Optional fields** | sourceContactId, eventId, sourceInteractionId, notes, sourceSystem, sourceId, sourceClaimId |
| **Dedup rule** | Priority cascade through 4 tiers. UNIQUE constraint as last-resort guard |
| **Triple check** | YES (Tier 1) |
| **Null handling** | `body.field ?? existing.field` on update |
| **Idempotent on reroute** | YES — robust 4-tier dedup |
| **Risks** | None significant. Well-defended |
| **Code location** | src/app/api/contact-provenance/route.ts |

### 13. POST /api/contact-profile-signals

| Field | Value |
|-------|-------|
| **Prisma model** | ContactProfileSignal |
| **Semantics** | 3-tier dedup: (1) full triple, (2) conversation-based (contactId+signalType+sourceId), (3) create |
| **Required fields** | contactId, signalType, content |
| **Optional fields** | confidence, conversationDate, sourceSystem, sourceId, sourceClaimId |
| **Dedup rule** | Tier 1: full triple. Tier 2: per-conversation per-signalType (covers vocal/what_changed signals without sourceClaimId). Tier 3: create |
| **Triple check** | YES (Tier 1) |
| **Null handling** | `body.field ?? existing.field` on update |
| **Idempotent on reroute** | YES — Tier 2 covers the no-sourceClaimId case |
| **Risks** | Tier 2 dedupes by signalType per conversation — if two different profile signals of same type from same conversation, only first persists. Acceptable because Sauron typically sends one per type |
| **Code location** | src/app/api/contact-profile-signals/route.ts |

### 14. POST /api/contact-affiliations

| Field | Value |
|-------|-------|
| **Prisma model** | ContactAffiliation |
| **Semantics** | 3-tier dedup: (1) full triple, (2) content-based (contactId+organizationId+sourceSystem+sourceId), (3) create |
| **Required fields** | contactId, organizationId or organizationName |
| **Optional fields** | title, department, roleType, isCurrent, isPrimary, startDate, endDate, notes, sourceSystem, sourceId, sourceClaimId |
| **Dedup rule** | Tier 1: full triple. Tier 2: same contact+org from same conversation |
| **Triple check** | YES (Tier 1) |
| **Org resolution** | resolveOrganization() — fuzzy match by name, returns orgId + resolutionSource |
| **Null handling** | `body.field ?? existing.field` on update |
| **Side effects** | syncPrimaryAffiliationToContact() — updates flat Contact.title/organization from primary affiliation |
| **Idempotent on reroute** | YES |
| **isPrimary policy** | Conservative — defaults false for Sauron. Only explicit isPrimary=true promotes. Clears other isPrimary flags first |
| **Risks** | Org resolution could fail (returns 422). Sauron should handle this gracefully |
| **Code location** | src/app/api/contact-affiliations/route.ts |

### 15. POST /api/organization-signals

| Field | Value |
|-------|-------|
| **Prisma model** | OrganizationSignal |
| **Semantics** | 3-tier dedup: (1) full triple, (2) content-based (orgId+signalType+title+sourceSystem+sourceId), (3) create |
| **Required fields** | organizationId or organizationName, signalType, description |
| **Optional fields** | title, confidence, observedAt, relatedOrg, relationshipType, sourceSystem, sourceId, sourceClaimId |
| **Dedup rule** | Tier 1: full triple. Tier 2: content match |
| **Triple check** | YES (Tier 1) |
| **Org resolution** | resolveOrganization() — same as affiliations |
| **Null handling** | `body.field ?? existing.field` on update |
| **Side effects** | industry_mention signalType auto-fills org.industry if null |
| **Idempotent on reroute** | YES |
| **Risks** | Org resolution failure returns 422 |
| **Code location** | src/app/api/organization-signals/route.ts |

### 16. POST /api/referenced-resources

| Field | Value |
|-------|-------|
| **Prisma model** | ReferencedResource |
| **Semantics** | Upsert on full triple (sourceSystem+sourceId+sourceClaimId); else create (no content fallback) |
| **Required fields** | description |
| **Optional fields** | contactId, resourceType, url, action, sourceSystem, sourceId, sourceClaimId |
| **Dedup rule** | Full triple only. No content-based fallback (description text too variable) |
| **Triple check** | YES |
| **Null handling** | `body.field ?? existing.field` on update |
| **Idempotent on reroute** | YES with sourceClaimId; NO without (creates duplicates) |
| **Risks** | If sourceClaimId is absent, no dedup at all. Sauron sends real claim UUIDs for this lane, so should be OK |
| **Code location** | src/app/api/referenced-resources/route.ts |

### 17. POST /api/calendar/events

| Field | Value |
|-------|-------|
| **Backend** | Google Calendar API (not Prisma) |
| **Semantics** | Upsert via Google Calendar extendedProperties if full triple provided; else create |
| **Required fields** | summary, start |
| **Optional fields** | end (defaults to start), location, description, sourceSystem, sourceId, sourceClaimId |
| **Dedup rule** | Search calendar.events.list with privateExtendedProperty filters for all 3 source fields. If found: update. Else: create with extendedProperties |
| **Triple check** | YES — all three stored in extendedProperties.private |
| **Null handling** | end defaults to start; location/description omitted if null |
| **Idempotent on reroute** | YES with full triple; NO without (creates duplicate calendar events) |
| **Risks** | Google Calendar API latency. Title fallback (cal:{title[:60]}) as sourceClaimId is temporary — noted in D4 |
| **Code location** | src/app/api/calendar/events/route.ts |

### 18. POST /api/contacts/[id]/dossier

| Field | Value |
|-------|-------|
| **Backend** | Claude Sonnet 4 API via budget-enforced wrapper |
| **Semantics** | Synthesis trigger — generates/updates contact dossier |
| **Required fields** | contactId (via URL) |
| **Optional fields** | mode (full/incremental) |
| **Dedup rule** | N/A — overwrites previous dossier on same contact |
| **Triple check** | N/A |
| **Null handling** | N/A |
| **Idempotent on reroute** | YES — regenerating dossier is harmless (just costs API budget) |
| **Sauron integration** | NOT currently called by Sauron (0C.2 deferred) |
| **Risks** | $10/day API budget cap. Incremental mode depends on previous dossier existing |
| **Code location** | src/app/api/contacts/[id]/dossier/route.ts |

---

## Cross-Cutting Findings

### Dedup Maturity by Tier

| Tier | Description | Endpoints |
|------|-------------|-----------|
| **Full triple** | sourceSystem+sourceId+sourceClaimId | commitments, signals, interests, activities, provenance, profile-signals, affiliations, org-signals, referenced-resources, calendar |
| **Partial (sourceSystem+sourceId)** | Effectively claim-level because Sauron sends real UUIDs in sourceId | interactions, scheduling-leads, standing-offers, life-events |
| **Structural** | Dedup by domain key (contact pair, interaction+contact) | interaction-participants, contact-relationships |
| **PATCH (by ID)** | No dedup needed | contacts/[id] |
| **External API** | Google Calendar extendedProperties | calendar/events |
| **Synthesis** | Idempotent by nature | dossier |

### Null-Only Patching

The PATCH /api/contacts/[id] endpoint does NOT enforce null-only semantics server-side. Sauron's `_update_contact_field_null_only()` in commitments.py does this check client-side before sending. This means any other caller (manual edits, future integrations) could overwrite populated fields.

**Recommendation**: Consider adding a `nullOnly: true` parameter to the PATCH endpoint that would skip fields where the existing value is non-null. Low priority — current client-side guard works.

### Org Resolution

Two endpoints use `resolveOrganization()`: contact-affiliations and organization-signals. This function does fuzzy name matching to find or create an Organization record. If resolution fails, both return 422. Sauron should log these failures clearly (it currently does via secondary lane result tracking).

### Missing sourceClaimId Columns

| Model | Has sourceClaimId? |
|-------|-------------------|
| Interaction | NO — uses sourceId only |
| InteractionParticipant | NO — structural dedup |
| Commitment | YES |
| SchedulingLead | NO — but real claim UUID in sourceId |
| StandingOffer | NO — but real claim UUID in sourceId |
| IntelligenceSignal | YES |
| Contact | N/A (PATCH target) |
| LifeEvent | NO — but real claim UUID in sourceId |
| PersonalInterest | YES |
| PersonalActivity | YES |
| ContactRelationship | NO — structural dedup by contact pair |
| ContactProvenance | YES |
| ContactProfileSignal | YES |
| ContactAffiliation | YES |
| OrganizationSignal | YES |
| ReferencedResource | YES |
| Calendar Event | YES (extendedProperties) |
| Dossier | N/A |

### Action Items

1. **No critical fixes needed** — all 18 endpoints have adequate dedup for current usage
2. **Future**: Add sourceClaimId to SchedulingLead, StandingOffer, LifeEvent models for consistency (currently safe because real claim UUIDs go in sourceId)
3. **Future**: Add null-only guard server-side on PATCH /api/contacts/[id]
4. **Future**: Calendar title fallback (cal:{title[:60]}) should be replaced with real claim UUIDs when extraction provides them
5. **Monitor**: Org resolution failures (422s) on affiliations and org-signals lanes

---

## Verdict

All 18 endpoints are production-ready for Sauron integration. Dedup coverage is comprehensive — no lane creates unbounded duplicates on reroute. The four endpoints using sourceId-only dedup (scheduling-leads, standing-offers, life-events, interactions) are effectively claim-level because Sauron sends real claim UUIDs as sourceId for those lanes. The system is safe for the volume increase when user starts at CFTC.
