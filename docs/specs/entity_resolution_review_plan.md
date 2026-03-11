# Entity Resolution & Review Integration Plan

## Problem Statement

Sauron extracts intelligence about people, but the link between "person mentioned in conversation" and "contact record in the CRM" breaks at multiple points:

1. **During extraction:** Sonnet uses conversational names ("Senator Hawley", "the Commissioner", "Heath")
2. **During synthesis:** Opus produces standing offers, scheduling leads, and graph edges using whatever names Sonnet used — these are name strings, not entity-linked objects
3. **During routing:** Name strings don't match Networking App contact records, causing failed routes, self-referential edges, or dropped objects

The entity resolver and review UI currently handle claim-level entity linking well. But synthesis objects (standing offers, scheduling leads, graph edges, follow-ups) bypass entity linking entirely — they go from Opus output straight to routing as unlinked name strings.

## Current State

**What works:**
- Claims have `subject_entity_id` linking to `unified_contacts`
- The entity resolver auto-links claims using canonical names, aliases, and relational terms
- The review UI lets you manually link/relink claim subjects to contacts
- The `claim_entities` junction table tracks all entity links with `link_source` (model/resolver/user)

**What doesn't work:**
- Standing offers have `contact_name` (string) — no entity link
- Scheduling leads have `contact_name` (string) — no entity link
- Graph edges have `from_entity` / `to_entity` (strings) — no entity link
- Follow-ups have no person reference at all
- New contacts mentioned are name strings
- The review UI doesn't show standing offers, scheduling leads, or graph edges (they're in the Raw JSON tab only)
- Routing resolves these strings at write time using `_resolve_contact_id_for_entity`, which fails on informal names

## Solution Design

### Part 1: Auto-Link Synthesis Objects Using Claim Entities

**When:** After Opus synthesis completes, before the conversation enters the review queue.

**What:** A post-synthesis pass that scans every synthesis object's person references and attempts to resolve them using the claim entity links that already exist for this conversation.

**How it works:**

For each person reference in synthesis objects (standing offer `contact_name`, graph edge `from_entity`/`to_entity`, scheduling lead `contact_name`):

1. **Exact match on claim entities:** Query `claim_entities` + `event_claims` for this conversation: is there a `claim_entities.entity_name` that matches this string? If yes, use that `entity_id`. This is the highest-leverage strategy because Sonnet and the entity resolver already did the hard work during extraction.

2. **Fuzzy match on claim subjects:** Query `event_claims.subject_name` for this conversation: did any claim use this same name string and get linked to a `subject_entity_id`? If yes, use that entity ID.

3. **Direct match on unified_contacts:** Check canonical_name and aliases in `unified_contacts`.

4. **Last-name fallback:** Extract the last word from the name string and check if there's exactly one `unified_contacts` entry with that last name. Only use this if the match is unique — if ambiguous, skip.

If resolved, store the link with the resolution method and apply the color coding rules from Part 2:

- **Strategy 1** (exact claim entity match) → store as confirmed (`link_source: 'auto_synthesis'`, green) — high trust, no user action needed
- **Strategy 2** (claim subject fuzzy match) → store as tentative (`link_source: 'auto_synthesis'`, yellow) — needs one-click confirmation
- **Strategy 3** (canonical name or alias match) → green if the match is on the full canonical name or a multi-word alias; yellow if the match is on a single-word alias
- **Strategy 4** (last-name fallback) → store as tentative (`link_source: 'auto_synthesis'`, yellow) — always needs confirmation

If not resolved:
1. Check if a provisional contact already exists in `unified_contacts` with this name
2. If not, create one with `is_confirmed = 0` and `source_conversation_id` set
3. Also scan `event_claims` for claims with matching `subject_name` or `target_entity` where the entity is not yet linked (`subject_entity_id = NULL` for subject matches, or no `claim_entities` entry with `role: 'target'` for target matches), and link them to the new provisional (same logic as `_create_provisional_contacts` in processor.py lines 1213-1236, extended to also check `target_entity`)
4. Store the synthesis entity link pointing to this provisional with `resolution_method: 'provisional_created'` and low confidence
5. The unresolved item surfaces in review for manual resolution (Create Contact / Link to Existing / Skip)

**Storage:**

Add a `synthesis_entity_links` table:

```sql
CREATE TABLE IF NOT EXISTS synthesis_entity_links (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id),
    object_type TEXT NOT NULL,        -- 'standing_offer', 'scheduling_lead', 'graph_edge', 'new_contact'
    object_index INTEGER NOT NULL,    -- index within the synthesis array
    field_name TEXT NOT NULL,         -- 'contact_name', 'from_entity', 'to_entity'
    original_name TEXT NOT NULL,      -- the name string from Opus
    resolved_entity_id TEXT,          -- unified_contacts.id (null if unresolved)
    resolution_method TEXT,           -- 'claim_entity', 'claim_subject', 'canonical_name', 'alias', 'last_name', 'provisional_created', null
    confidence REAL,                  -- 0-1
    link_source TEXT DEFAULT 'auto_synthesis',  -- 'auto_synthesis' or 'user'
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_sel_conversation ON synthesis_entity_links(conversation_id);
CREATE INDEX IF NOT EXISTS idx_sel_entity ON synthesis_entity_links(resolved_entity_id);
```

### Part 2: Three-Layer Review Model

**The review UI uses three layers for entity resolution, each with a distinct purpose:**

**Layer 1: ProvisionalContactsBanner — Identity Resolution Hub**

This becomes the central surface for resolving ALL people in the conversation — green, yellow, and red. Not just unrecognized people. Every person referenced in claims or synthesis objects appears here with their resolution status.

Shows:
- 🟢 Green items — auto-resolved with high confidence. Visible for verification and one-click correction if wrong.
- 🟡 Yellow items — auto-resolved but tentative. One click to confirm.
- 🔴 Red items — unresolved. Create contact, link to existing, or skip.

For each person: object counts (claims, standing offers, scheduling leads, graph edges), expand to see detail.

**When you confirm a person, the cascade fires:**

1. **Subject entity linking** — all claims where `subject_name` matches the resolved name → update `subject_entity_id` to the resolved contact, upsert `claim_entities` with `role: 'subject'`

2. **Target entity linking** — all claims where `target_entity` matches the resolved name → upsert `claim_entities` with `role: 'target'` and the resolved contact's `entity_id`. This is the key addition: claims reference multiple people, and both subject and target get entity-linked.

   The cascade does NOT scan `claim_text` for name strings — that's fragile and error-prone ("Hawley" could appear in "the Hawley building"). Instead, it uses `subject_name` and `target_entity` — fields that Sonnet set during extraction with full conversational context. If Sonnet attributed the person as a subject or target, the link is safe. If Sonnet didn't, scanning prose would be guessing.

   Example: "Mike Fiato told Cliff that Senator Hawley supports the bill"
   - `subject_name`: "Mike Fiato" → `subject_entity_id` already linked
   - `target_entity`: NULL (Sonnet didn't flag Hawley as the target here)
   - Confirming Senator Hawley = Josh Hawley would NOT tag this claim for Josh Hawley, because Sonnet didn't put him in `target_entity`. Correct — Hawley is mentioned in the claim content but isn't the subject or target of the claim itself.

   Example: "Stephen Andrews works with Senator Hawley"
   - `subject_name`: "Stephen Andrews" → linked
   - `target_entity`: "Senator Hawley" → cascade adds `claim_entities(role='target', entity_id=josh_hawley_id)`
   - Now this claim is tagged for both Stephen Andrews and Josh Hawley with clear roles.

3. **Claim text and target_entity rewriting** — `claim_text` is rewritten to use the canonical name via `replace_name_in_text` (existing function). `target_entity` string is updated to the canonical name. `evidence_quote` stays untouched as verbatim transcript evidence. `text_user_edited` is set to track the modification. This ensures claims are searchable by canonical name ("Josh Hawley") even when the transcript said "Senator Hawley".

4. **Episode titles** — any episode title referencing the old name is updated to use the canonical name

5. **Synthesis entity links** — standing offers, graph edges, scheduling leads referencing this name get linked to the resolved contact

6. **RelationalReferencesBanner updates** — if this person appears as an anchor or target in a relational reference, that reference auto-updates. "Senator Hawley's aide" becomes resolvable because "Senator Hawley" is now resolved.

7. **Transcript display** — the display layer shows the canonical name on transcript segments mentioning this person. Raw transcript text is not rewritten (evidence integrity).

8. **Alias learning** — the resolved name form is added as an alias per the rules in Part 3 (e.g., "Senator Hawley" → alias for Josh Hawley)

The cascade uses existing infrastructure: `replace_name_in_text` and `replace_confirmed_name` in `entity_helpers.py`, the bulk reassign pattern in `conversations.py`, and the `claim_entities` junction table which already supports multiple entities per claim with roles.

**Layer 2: RelationalReferencesBanner — Relationship Resolution**

Stays as a separate component. Handles "his wife", "my brother", "Stephen's colleague" — relational terms that need linking to specific contacts.

This is a fundamentally different interaction from identity resolution. You're not asking "who is this person?" — you're asking "which of my contacts has this relationship to that person?"

When you resolve a relational reference:
- The same cascade fires for the target person (claim linking, text replacement, synthesis links)
- The relationship is saved to `unified_contacts` (and eventually routed to Networking App's `ContactRelationship`)
- If the anchor person was resolved in Layer 1, the relational reference may already have auto-updated

Layer 2 gets simpler over time as Layer 1 resolves more people — relational references where the anchor is resolved become easier to complete.

**Layer 3: Routing Preview — What Will Be Routed**

A new read-mostly section below the banners. Shows standing offers, scheduling leads, and graph edges with their current entity resolution status. This is where you SEE the result of entity resolution, not where you DO it.

```
Routing Preview (18 objects ready, 2 blocked)

Standing Offers (1):
  🟢 Heath Tarbert offered to introduce Stephen to the SEC team → ready to route

Scheduling Leads (1):
  🟢 Legislative hearing testimony — dates TBD → ready to route

Graph Edges (11):
  🟢 Cliff Millikan → supports → Josh Hawley → ready to route
  🟢 Cliff Millikan → knows → Alex Little → ready to route
  🔴 Cliff Millikan → knows → Mike Fiato → blocked (Mike Fiato unresolved)
  🔴 Cliff Millikan → knows → Chris Cuomo → blocked (Chris Cuomo unresolved)
  ...

Intelligence Signals (5): all ready to route
```

If something is blocked, it points you back to Layer 1 to resolve the person. The routing preview doesn't have its own entity linking controls — it's a status dashboard.

When you click "Mark Reviewed":
- All green and confirmed-yellow objects route normally
- All blocked objects are held as `pending_entity` in the routing log
- The review completeness indicator shows: "Mark Reviewed (2 people need attention — 4 objects will be held)"

**What this replaces vs preserves:**

| Component | Change |
|---|---|
| ProvisionalContactsBanner | **Extended** — now shows all people (green/yellow/red), not just unrecognized. Cascade on confirmation. |
| RelationalReferencesBanner | **Preserved** — stays as-is for relational resolution. Updates automatically when Layer 1 resolves anchor people. |
| Claim entity linking (Episodes tab) | **Preserved** — stays for per-claim corrections. Primary entity resolution moves to Layer 1. |
| Routing Preview | **New** — read-mostly status dashboard for what will be routed. |
| Raw JSON tab | **Preserved** — still available for debugging. |

### Part 3: Contact Sync Integrity

**Current state:**
- `sync.py` pulls contacts from Networking App → creates/updates `unified_contacts`
- Matching is by `networking_app_contact_id` (if already linked) or by exact name
- One-directional: Networking → Sauron only
- Aliases come from relational terms in the contact's relationship data, not from conversational usage

**Problems:**
- A contact might exist in both systems under slightly different names and never get linked
- New contacts created manually in the Networking App aren't in Sauron until the next sync
- Aliases are sparse — "Senator Hawley" isn't automatically added as an alias for "Josh Hawley"
- Provisional contacts in Sauron might duplicate Networking App contacts

**Improvements:**

**3A: Fuzzy name matching in sync.**

When sync encounters a Networking App contact that doesn't match any `unified_contacts` entry by ID or exact name, try fuzzy matching:
- Last name match: "Josh Hawley" matches any unified_contacts entry with last name "Hawley"
- First name + org match: "Josh" at "Senate" matches "Josh Hawley" if he has org/tags indicating Senate
- Only auto-link if the fuzzy match is unique (one candidate). If ambiguous, flag for review.

**3B: Conversational alias learning.**

When the entity resolver or the user links a name to a contact, automatically add that name as an alias to the contact's `unified_contacts.aliases` field. This happens in:
- The entity resolver (when it successfully resolves via claim context)
- The review UI (when the user manually links an entity)
- The synthesis auto-linker (Part 1, when it resolves via claim entities)

This means the system gets smarter over time. The first time someone says "Senator Hawley", you might need to link it manually. Every subsequent conversation, the alias is there and resolution is automatic.

**Alias learning rules:**

1. **Multi-word names with titles** ("Senator Hawley", "Commissioner Pham", "Dr. Chen") — always add as alias. These are specific enough to be unambiguous across conversations.

2. **Title abbreviation expansion** — when learning a title-based alias, also add the abbreviated/expanded form automatically. The lookup table:
   - Senator ↔ Sen.
   - Commissioner ↔ Comm.
   - Representative ↔ Rep.
   - Secretary ↔ Sec.
   - Professor ↔ Prof.
   - Doctor ↔ Dr.
   
   So confirming "Senator Hawley" as Josh Hawley adds both "Senator Hawley" and "Sen. Hawley" as aliases.

3. **Single-word last names** ("Hawley") — add as alias, but tag as low-specificity. These are treated as yellow during auto-linking (never green) because another person with the same last name could appear in a future conversation.

4. **Bare title references** ("the Senator", "the Commissioner", "my boss") — never add as alias. These are too generic and would cause false matches across conversations.

5. **First names alone** ("Josh", "Heath", "Sarah") — never add as alias. Too common. The entity resolver already handles first-name matching with conversation-connection gating.

6. **Alias source tagging** — aliases learned from confirmation are tagged with `alias_source: 'learned'` so they can be distinguished from manually added aliases or sync-derived aliases. This enables cleanup if an alias is later found to be wrong.

**Alias confidence and auto-link color:**

- Multi-word alias match → 🟢 green (specific enough to trust)
- Single-word alias match → 🟡 yellow (plausible but needs confirmation)
- This is determined at auto-link time by checking the length of the alias that matched, not the length of the input name

**3C: Sync frequency.**

Run sync before review when possible. When a user opens a conversation for review, trigger a lightweight sync check: are there any Networking App contacts created since the last sync? If yes, pull them. This ensures the entity resolver has the freshest contact list when you're doing entity linking.

**3D: Unlinked contact surfacing.**

Add a section to the Sauron pipeline status (or a new triage view) that shows:
- `unified_contacts` entries with no `networking_app_contact_id` — need linking or promotion
- `unified_contacts` entries that are provisional (`is_confirmed = 0`) — need confirmation
- Count of these as a triage signal in Today

This already partially exists (the provisional contacts triage in `graph.py`). Extend it to cover the networking_app_contact_id gap.

## Part 4 Addendum: Contact Creation From Review

### The Problem

Right now, provisional contacts are only created from Sonnet's `new_contacts_mentioned` list (in `_create_provisional_contacts` in processor.py). This catches people Sonnet flags as new. But many people referenced in synthesis objects — graph edges especially — are never in that list. Opus produces a graph edge `Mike Fiato → Senator Hawley` but neither Mike Fiato nor Senator Hawley was in `new_contacts_mentioned`, so neither gets a provisional contact record. At routing time, `_resolve_contact_id_for_entity("Mike Fiato")` finds nothing and the edge is skipped.

This means graph edges, standing offers, and scheduling leads that reference people not in `unified_contacts` are silently dropped. The data exists in Sauron's extraction but never reaches the Networking App, and the user has no way to fix this during review because the people aren't linkable — they don't exist as contacts anywhere.

### The Solution

This is handled by the auto-linker (Part 1). When the auto-linker encounters a person name that doesn't resolve through any strategy, it creates a provisional contact (steps 1-5 under "If not resolved" in Part 1). The provisional gets linked to matching claims, and appears in the review UI's Layer 1 (ProvisionalContactsBanner) as a red/unresolved item with Create Contact, Link to Existing, and Skip actions.

**What this changes in the existing code:**

- `_create_provisional_contacts` stays as-is (handles Sonnet's `new_contacts_mentioned`)
- The auto-linker (Part 1) additionally creates provisionals for synthesis object references that don't resolve
- Layer 1 of the review UI (Part 2) surfaces these provisionals with the person-centric resolve-once-cascade-everywhere interaction
- The routing code (Phase 4) checks `synthesis_entity_links` — if both sides of a graph edge are resolved (either to confirmed contacts or to newly-promoted provisionals), route it. If either side is unresolved or skipped, don't route.
- The existing `confirm_provisional_contact` and `link_provisional_contact` endpoints already handle the heavy lifting — they set `is_confirmed`, push to Networking App, update claim entities, and release pending routes.

### What This Means For The Cliff Conversation

Processing the Cliff Millikan interview today:
- Opus produced 11 graph edges referencing people like Mike Fiato, Charles Jackson, Senator Hawley, Chris Cuomo, Alex Little
- Senator Hawley would auto-link via alias (Part 1, strategy 3)
- Mike Fiato, Charles Jackson, Chris Cuomo, Alex Little would get provisional contacts created
- During review, Layer 1 would show all people with their resolution status
- You'd confirm Senator Hawley with one click (yellow → green)
- For Mike Fiato et al., you'd choose: create as new contact (push to Networking App), link to existing if they're already there under a different name, or skip if they're irrelevant
- Each resolution cascades to all that person's claims, graph edges, and synthesis objects
- Only graph edges where both sides are resolved would route to the Networking App
- The rest stay in Sauron's graph (still searchable, still in Person Briefs) but don't create CRM records

## Updated Build Sequence

### Phase 1: Auto-linker + provisional creation (highest leverage)
- Create `synthesis_entity_links` table
- Build the post-synthesis auto-linker that runs after Opus, before review queue
- Resolution strategies 1-4 in order (claim entity match, claim subject match, canonical name/alias match, last-name fallback)
- **When resolution fails: create provisional contact for the unresolved name and link matching claims**
- When linking claims to a newly created provisional, match on both `event_claims.subject_name` AND `event_claims.target_entity` — a person can be either the subject or a referenced target of a claim
- Store links with confidence and method
- Wire into the pipeline (processor.py, after `_store_synthesis`)

**Implementation note for Claude Code:** Read the existing `entity_resolver.py` and `processor.py` `_create_provisional_contacts` before writing code — the patterns you need are already in the codebase.

### Phase 2: Conversational alias learning (quick win — can run in parallel with Phase 1)
- When entity resolver links a name → contact, add that name to aliases if not already present
- When user links in review UI, same
- When auto-linker resolves via claim entities, same
- This makes future resolution better automatically

**Implementation note for Claude Code:** Follow the alias learning rules from Part 3 of this plan:
- Multi-word names with titles ("Senator Hawley") — always add. Also add the abbreviated/expanded form using the lookup table: Senator ↔ Sen., Commissioner ↔ Comm., Representative ↔ Rep., Secretary ↔ Sec., Professor ↔ Prof., Doctor ↔ Dr.
- Single-word last names ("Hawley") — add but tag as low-specificity
- Bare title references ("the Senator", "my boss") — never add
- First names alone ("Josh", "Heath") — never add
- Deduplicate against existing aliases before adding
- Touches: `entity_resolver.py` (on successful resolution), entity linking API endpoint in `conversations.py` or `corrections.py` (on user linking), and the new auto-linker from Phase 1 (on successful resolution)

### Phase 3: Three-layer review UI
- **Layer 1:** Extend ProvisionalContactsBanner to show ALL people (green/yellow/red), not just unrecognized
  - Show object counts per person (claims, standing offers, scheduling leads, graph edges)
  - Expand to show detail
  - On confirmation: cascade to claim text (rewrite via `replace_name_in_text`, preserve `evidence_quote`), claim entities (both `subject_entity_id` and `target_entity` via `claim_entities` junction with role), episode titles, synthesis entity links, transcript display, RelationalReferencesBanner updates, and alias learning
  - Create Contact: mini-form with push-to-CRM defaulting on
  - Link to Existing: search-and-link flow
  - Skip: marks all objects for this person as don't-route
- **Layer 2:** RelationalReferencesBanner stays as-is for relational resolution ("his wife", "my brother"). Auto-updates when Layer 1 resolves anchor people.
- **Layer 3:** New Routing Preview section — read-mostly dashboard showing what will be routed with current entity resolution status. Shows ready/blocked counts. Blocked items point back to Layer 1.
- Review completeness indicator on Mark Reviewed: "2 people need attention — 4 objects will be held"

**Implementation note for Claude Code:** The existing `ProvisionalContactsBanner` and `RelationalReferencesBanner` in `ConversationDetail.jsx` are the starting patterns. Layer 1 extends `ProvisionalContactsBanner`, Layer 2 preserves `RelationalReferencesBanner`, Layer 3 is new. The cascade uses existing infrastructure: `replace_name_in_text` in `entity_helpers.py`, the bulk reassign pattern in `conversations.py`, and the `claim_entities` junction table. Read Part 2 of this plan thoroughly before building.

### Phase 4: Routing reads synthesis entity links
- Update `networking.py` to read from `synthesis_entity_links` instead of calling `_resolve_contact_id_for_entity` with name strings
- For each routed object, check if a confirmed or high-confidence auto-link exists
- If yes, use the resolved `networking_app_contact_id`
- If no, skip the object (or hold as pending_entity)
- Remove the old `_resolve_contact_id_for_entity` name-matching fallback for synthesis objects

### Phase 5: Contact sync improvements
- Fuzzy name matching in sync
- Sync-before-review trigger
- Unlinked contact surfacing in Today/triage

## Dependencies

- Phase 1 has no dependencies — can start immediately
- Phase 2 has no dependencies — can run in parallel with Phase 1
- Phase 3 depends on Phase 1 (needs the `synthesis_entity_links` table and data to display)
- Phase 4 depends on Phase 1 and Phase 3 (needs links to exist and be reviewable)
- Phase 5 is independent — can run anytime

## Success Criteria

- "Senator Hawley" automatically resolves to Josh Hawley in synthesis objects (via claim entity lookup or learned alias)
- People referenced in graph edges who aren't in unified_contacts get provisional records created automatically
- Claims referencing those same people are automatically linked to the new provisional contacts (both as subjects via `subject_entity_id` and as targets via `claim_entities` with `role: 'target'`)
- Layer 1 (ProvisionalContactsBanner) shows ALL people in the conversation with green/yellow/red status
- For unknown people: one-click create contact (with push to Networking App), link to existing, or skip
- Creating a contact during review pushes to the Networking App and releases any pending routes in one action
- Resolving a person cascades to all their claims (subject + target linking, text rewriting), episode titles, synthesis objects, and relational references
- One-click confirm for auto-linked entities; manual linking for unresolved ones
- Routing uses resolved entity IDs from synthesis_entity_links, not name-string guessing
- Aliases grow automatically from conversational usage — the system gets smarter with every reviewed conversation, including title abbreviation expansion (Senator ↔ Sen.)
- Bare title references ("the Senator", "the Commissioner") are left unresolved for manual linking
- Unlinked and provisional contacts are visible as triage signals
- Graph edges where both sides are resolved route to the Networking App; unresolved edges stay in Sauron only

## Future Enhancements

**Haiku entity tagging pass.** After the `subject_name` + `target_entity` cascade is proven, consider adding an optional Haiku pass that scans all claims in a conversation and identifies every person referenced in each claim — not just subject and target, but any mention within the claim text. This would catch cases like "Mike Fiato told Cliff that Senator Hawley supports the bill" where Hawley appears in the content but isn't the subject or target. Cost would be ~$0.01 per conversation. Build this only if the `subject_name` + `target_entity` approach is found to miss important entity links after reviewing 20-30 conversations.
