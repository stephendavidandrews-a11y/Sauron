# Sauron Frontend — Design Spec

*Supersedes Section 10.1 of the plan. Governs Phase 8 (Sauron App).*

This document defines the frontend architecture for sauron.stephenandrews.org. It supersedes Section 10.1 of the plan. The app structure, interaction principles, and view designs below should govern Phase 8 (Sauron App).

## Foundational Principles

The frontend is organized around modes of use (Today, Prep, Review, Search), not around stored data objects. People, topics, conversations, and beliefs are underlying objects surfaced within those modes, not exposed as the primary navigation model. Do not build a database-shaped UI.

The real value of Sauron is not that it remembers. It's that it helps you move well. Every screen should answer: who matters, what changed, what needs action, what's the next move. If a screen just displays stored information without driving a decision, it's wrong.

Trust over intelligence. Every important assertion should be one tap away from its evidence: which conversation, which episode, what was actually said, stated or inferred, how recent. If the frontend just sounds insightful without showing its work, it will eventually feel slippery. Design for trust.

Default to the smallest useful surface. Expand only when the user asks for more. Every list defaults to 3-7 most relevant items with explicit expansion. Every object defaults to 15-second skim with drill-down available. Do not dump long feeds, dense profiles, or full evidence by default.

## Top-Level Navigation

Four items. No more.

```
[ Today ]  [ Prep ]  [ Review ]  [ Search ]
```

Plus a universal command palette (keyboard shortcut or tap) that is always available from any screen.

People, topics, conversations, and beliefs are NOT top-level nav items. They are objects that surface within these four modes.

## Today

Your command center. The default landing page. Shows what matters right now.

**Temporal logic:**
- Morning mode: active until first completed meeting of the day OR 1:00 PM local time, whichever comes first
- Evening mode: after 1:00 PM local time, with stronger weighting toward summary after the last calendar event of the day
- Small manual toggle available for edge cases (light-meeting days, unusual schedules)

**Morning mode:**
- Upcoming meetings today with [Prep →] links
- What changed overnight (new belief updates, position shifts, relationship movement)
- Urgent follow-ups and overdue obligations
- Open loops you're forgetting
- Active recommendations
- Triage count (items needing attention in Review)
- Weekly performance snapshot (Monday mornings only)

**Evening mode:**
- What happened today (conversations processed, what was extracted)
- What changed today (new beliefs, updated positions, relationship signals)
- What still needs action
- What tomorrow looks like (tomorrow's meetings with prep status)
- Items that need review before tomorrow

There is no separate end-of-day brief view. Today handles both by being temporally aware.

**List rule:** Every list on Today defaults to top 3-7 most relevant items. Explicit "show more" for expansion. Do not dump long feeds.

**Empty state:** When there's little data: "No major changes overnight. 2 meetings today — prep available for 1. No urgent review items." Show what exists without pretending there's deep intelligence where there isn't.

**Recency display:** Use human-readable recency everywhere: "2 days ago," "last Tuesday," "3 meetings ago." Exact timestamps available on expand. For beliefs, prefer "last confirmed" language.

## Prep

Everything oriented around going into a person, topic, meeting, or ask smart. This is the "I need to be ready" mode.

**Single launcher, not a menu tree.** Prep should have one input field at the top. Type a person name, a meeting title, a phone number, a topic, or a vague phrase. The system routes to the appropriate prep surface automatically. Do not make users choose between Person / Topic / Meeting / Call as separate menu items.

### Prep surfaces:

#### Person Brief:

**3-second skim:**
- Name, why they matter, latest change, next move

**15-second skim:**
- Recent interactions, active commitments in both directions, current stance on key topics, tactical cue, relationship trajectory

**2-minute full brief** — split into core (always visible) and expandable modules:

Core brief (default visible):
- Relationship status and trajectory with contributing signals
- Communication approach (their style, what they respond to, what to avoid)
- Open commitments with overdue flags
- Reciprocity balance
- "What changed since last time" (belief movement, new positions, new obligations)
- "What to ask about" (personal details worth following up on)
- Interaction patterns and vocal-derived tactical cues (shown only when they produce a concrete tactical insight, NOT raw metrics like "pitch variability elevated")
- Suggested approach

Expandable modules (collapsed by default, expand on tap):
- Vocal baseline detail
- Knowledge graph connections
- Full evidence rollup for current beliefs
- Complete interaction history

#### Surprise Call Card

The 3-second skim, designed for unexpected calls or drop-bys. Who they are, last three interactions, open commitments, current tactical guidance, recent changes, recommended tone. Must be scannable in 3 seconds.

#### Topic Brief

Who has discussed this topic, what they think, where views diverge, recent shifts, linked conversations, strategic next conversations, related asks.

#### Meeting Game Plan

Auto-generated from calendar. The full person brief plus meeting-specific context, including stated goals from prep capture if available. Includes ask builder notes in later phases.

**Briefing lock:** When a game plan is generated (triggered by calendar 24h before meeting, or manually), it freezes as a stable snapshot. If new data arrives after generation, the brief shows a small indicator: "2 updates since this brief was generated" with option to refresh. This prevents the brief from shifting while you're scanning it. You want to trust what you read, walk in, and not worry that the advice changed.

**Empty state for sparse contacts:** "Limited history available." Show last interaction, known commitments, and any linked topics. Do not pretend there's deep intelligence where there isn't. Avoid filling the brief with placeholder language or speculative filler.

## Review

The human-in-the-loop cleanup and learning mode. Where you process conversations, confirm or correct extractions, and make the system smarter.

Two interaction patterns: Quick Pass and Deep Review.

### Quick Pass (the default)

A stream of claim cards from recently processed conversations. For each claim, available actions:
- Keep
- Edit
- Downgrade confidence
- Delete
- Mark claim type wrong
- Needs deeper review (graceful handoff to Deep Review — flags the conversation for closer examination without requiring you to do it now)

Swipeable, fast, minimal friction. Most days you spend 3-5 minutes here. This is the primary surface that feeds the iterative improvement system. If review is annoying, it won't happen enough and the system won't learn.

Quick pass also surfaces:
- New commitments to confirm
- Belief transitions to approve or correct (shown as movement: "Sarah on Part 39: Active → Qualified")
- Low-confidence items flagged for attention
- Unknown speakers needing identification (with audio clip playback)

### Deep Review (entered from Quick Pass or Search)

Full conversation view with episode timeline, transcript, vocal analysis, all extracted claims per episode, commitment details, belief updates, routing log. This is where you correct speaker assignments, fix episode boundaries, add missed claims, and examine vocal analysis details.

### Belief review surface

Current belief, supporting evidence (linked claims with quotes), conflicting evidence, confidence, recency. Actions: confirm / refine / qualify / mark contested / mark stale / mark under_review. Show belief movement explicitly — the transition and what caused it, not just the current state.


### Browse All Beliefs — Design Decision

Browse All Beliefs: Browsing healthy/active beliefs does not belong on the Review page (which is a work queue for actionable items). The right home for belief exploration is the Search page — add a 'Beliefs' tab to Search that queries by person, topic, or keyword. The Prep page should also surface per-person beliefs in game plan context. The Review page's Belief section always shows when beliefs exist (total > 0), but the BeliefReview page itself only shows beliefs needing attention (under_review/contested/stale) and recent movement.

### Recommendation feedback (later phases)

For each recommendation: useful / not useful / wrong timing / wrong person / wrong framing / snoozed / acted on / linked to outcome. Recommendations are scorable objects, not just text.

**Empty state:** "Nothing needs review. Recently confirmed: [last 3 belief updates]. Or search for something specific." Don't show a blank screen.

## Search

Universal retrieval and command surface. The fastest way into everything. Primarily an entry point into the other modes, but must also stand on its own for fast recall and evidence lookup.

Two usage patterns it must handle:

**Specific queries:** "Heath stablecoins" or "Part 39 enforcement" — keyword and semantic search across episodes, claims, transcripts, contacts, topics. Results show context snippets from episodes (not just claim text), with source conversation, timestamp, and confidence visible. Group results by relevance, not just chronologically.

**Vague queries:** "who was that person at the Treasury event" or "something someone said about jurisdiction last month" — semantic search shines here. The UI must show enough context in results that you can recognize what you're looking for even when you couldn't precisely describe it.

Search results open into mode context. Tapping a person opens their person brief in Prep. Tapping a topic opens the topic brief. Tapping a conversation opens it in Review. But search results are also useful on their own for evidence lookup — the results page should display enough information (evidence quote, episode context, confidence, recency) to answer questions without always requiring navigation into another mode.

## Command Palette

Always available from any screen via keyboard shortcut or persistent input.

Not just search — actual commands:
- `prep heath` → opens Heath's person brief
- `prep tomorrow` → shows tomorrow's meetings with prep status
- `review today` → opens today's processed conversations in quick pass
- `call jennifer` → opens Jennifer's surprise call card
- `search tokenized collateral` → semantic search
- `correct last` → opens the most recently processed conversation in deep review
- `topic stablecoins` → opens stablecoin topic brief
- `today` → goes to Today

Keyboard shortcuts from any screen:
- `/` → focus command palette
- `T` → Today
- `P` → Prep
- `R` → Review
- `S` → Search

## Compression Principle: 3 / 15 / 120

Every major object (person, topic, meeting, belief, recommendation, conversation) should be viewable at three levels of compression:

**3-second skim:** One line. Name, why it matters, latest change, next move. Used for: surprise calls, scanning lists, quick decisions.

**15-second skim:** One card. Recent interactions, active commitments, current stance, tactical cue, trajectory. Used for: walking into meetings, deciding whether to follow up.

**2-minute full view:** Full brief with evidence, history, connections, and tactical recommendations. Split into core + expandable modules. Used for: serious prep before important meetings.

The app should default to the 15-second level and expand/collapse on demand. Do not default to the 2-minute level.

## Confidence Cues

The backend stores the full belief state set: Active, Provisional, Refined, Qualified, Time-bounded, Superseded, Contested, Stale, Under Review.

**In Review** (deep view and belief review): Show full granular states. The user needs precision here for corrections.

**In Prep and Today:** Compress belief states into visible families to avoid semantic overload:
- **Solid** (Active, Refined) — high confidence, well supported
- **Shifting** (Provisional, Qualified, Time-bounded) — true but with caveats or limited evidence
- **Contested** (Contested) — conflicting evidence
- **Stale** (Stale) — no recent confirmation
- **Under Review** (Under Review) — supporting evidence was just corrected

Use subtle visual treatment (chips, badges, or color coding) — not giant labels. The rule: everything should feel appropriately certain, not equally true.

## Belief Movement Visualization

Do not just show the current belief state. Show the transition.

**Bad:**
> Sarah on Part 39: mixed

**Good:**
> Sarah on Part 39: Qualified ← was Solid. Latest meeting narrowed support to implementation aspects only. Enforcement provisions now uncertain. [View evidence →]

## What NOT to Build

Do not build analytics dashboards as primary surfaces. A few charts are useful in the weekly performance section but they are secondary, not home screen material.

Do not build a CRM-style contact list. People are accessed through Prep and Search.

Do not build a conversation archive browser. Conversations are accessed through Review and Search.

Do not over-nest within modes. Each mode should feel like one surface with expandable depth, not a tree of sub-pages.

## Build Order (Phase 8)

1. Today page with temporal awareness (morning/evening modes) and empty states
2. Command palette and keyboard shortcuts
3. Search with semantic results, context snippets, and evidence display
4. Prep launcher + person brief (3-second / 15-second / 2-minute with core + expandable)
5. Review quick pass (claim card stream with keep/edit/delete/downgrade/needs-deeper-review)
6. Review deep view (conversation detail with episodes, claims, vocal analysis)
7. Surprise call card
8. Topic brief
9. Meeting game plan with briefing lock
10. Belief movement visualization
11. Confidence cues across all surfaces
12. Email upload drag-and-drop zone (placeholder)

**Implementation notes:** React with Tailwind, consistent with the networking app. Mobile-responsive — Prep and Today must work well on phone screens since game plans will be checked on the way to meetings. Infrastructure deployment (Cloudflare Tunnel / Tailscale) is a separate concern from frontend architecture.

---

## Implementation Status (March 9, 2026)

### Built (Phase 9 — Minimal React Frontend)
- **Nav**: Today / Prep / Review / Search (four items only, per spec)
- **Today page**: Dashboard with upcoming meetings, recent conversations, pipeline status, triage count
- **Prep page**: Person brief launcher, game plan generation
- **Search page**: Semantic search across conversations, claims, contacts, topics with context snippets and evidence quotes
- **Review page**: Needs Review (unreviewed conversations with episode/claim counts, warning badge) + Recently Reviewed (sorted by reviewed_at DESC) + Processing + Pending
- **ConversationDetail** (accessible from Review):
  - **Episodes tab** (primary review surface): expandable accordion per episode, per-claim approve/flag/edit, entity linking (tap subject_name to link to contact), "Approve All" per episode
  - **Transcript tab**: speaker correction (click speaker label → contact search dropdown), inline text editing (click text → edit Whisper misspellings, preserves original_text)
  - **Claims tab**: flat list alternate view with same claim actions
  - **Summary tab**: synthesis, vocal intelligence, topics, commitments, follow-ups, belief updates, self-coaching
  - **Raw tab**: raw extraction JSON viewer
  - **Header**: Mark as Reviewed button (triggers routing to downstream apps), Reprocess button (for error/pending conversations), metadata chips (duration, context, voice alignment)
  - **Entity linking UI enhancements** (March 8, 2026):
    - Entity add/remove updates inline immediately (no page refresh needed) via props-to-local-state pattern with useEffect sync
    - Bulk reassign modal includes display name override text input
    - Relational references banner has pencil-edit button for changing anchor contact with search dropdown
    - Relational reference save form: editable relationship type, source person display, multi-target support ("Add another person" button with contact search per target)
    - Entity text replacement: full-name to full-name word-boundary regex replacement in claim text on entity link and bulk reassign
- **Contact sync admin**: collapsible admin section in Search page with Sync Contacts button and result stats
- **Learning page** (/learning): amendment viewer/editor, correction stats by error type, activate/deactivate amendments, contact preference management
- **Dark theme**: consistent #0a0f1a bg, #111827 cards, inline styles
- **Build**: Vite + React, served as SPA by FastAPI with 404 exception handler fallback
- **Pipeline Redesign frontend (Deploy 2-3, March 9, 2026):**
  - **Review.jsx** completely restructured: 6 queue sections — Speaker Review (purple, `awaiting_speaker_review`), Triage Check (yellow, `triage_rejected` with inline expand/promote/archive), Claim Review (blue, `awaiting_claim_review`), Processing (`transcribing`/`triaging`/`extracting`), Pending, Recently Reviewed
  - **SpeakerReview.jsx** — NEW page at `/review/:id/speakers`: speaker summary cards with voiceprint match method/confidence, per-speaker audio sample playback, contact assignment via search dropdown, speaker merge, full transcript view with per-segment audio playback, "Confirm & Start Extraction" button
  - **NavBar.jsx** — badge count on Review tab showing total items across speaker/triage/claim queues; polls `/api/conversations/queue-counts` every 30 seconds via App.jsx
  - **api.js** — 15 new methods: `queueCounts`, `confirmSpeakers`, `promoteTriage`, `archiveTriage`, `audioClipUrl`, `speakerSampleUrl`, `getAnnotations`, `createAnnotation`, `deleteAnnotation`, `speakerMatches`, `triageData`, `mergeSpeakers`, `reassignSegment`
  - **ProcessingChip** in Today.jsx updated for all 9 pipeline statuses
  - **ConversationDetail.jsx** — "Confirm Speakers" link for `awaiting_speaker_review`, "Mark as Reviewed" now accepts `awaiting_claim_review` status
  - **Triage.jsx** — now includes `triage_rejected` conversations
  - **App.jsx** — speaker review route at `/review/:id/speakers`, SpeakerReview component import, badge count polling with 30s interval

- **Belief Review Surface** (March 9, 2026):
  - **BeliefReview.jsx** -- NEW page at /review/beliefs: two-mode view (Needs Attention / Recent Movement)
  - **BeliefCard** with expandable evidence drill-down (linked claims with quotes, source conversations) and status-specific action buttons (confirm/refine/qualify/mark contested/mark stale/mark under_review)
  - **Status family grouping**: Solid (Active, Refined), Shifting (Provisional, Qualified, Time-bounded), Contested, Stale, Under Review -- color-coded chips
  - **belief_transitions table**: tracks all status changes with source type (new_evidence, correction, user_action), old/new status, reasoning
  - **6 new API endpoints**: beliefs stats, recent beliefs, recent transitions, belief evidence, per-belief transitions, enhanced list with status/person/topic filters
  - **Transition writes from pipeline**: new_evidence (extraction), correction (claim corrections), user_action (manual review actions)
  - **last_changed_at fix**: correct_belief endpoint now updates last_changed_at timestamp
  - **Integration**: route at /review/beliefs, Beliefs section on Review page links to BeliefReview when beliefs exist (total > 0), shows only actionable items (under_review/contested/stale) plus recent movement
  - **Browse All Beliefs**: NOT on Review page per design decision -- belongs on Search page (Beliefs tab, not yet built)


- **Discard feature (March 9, 2026):**
  - Backend: `PATCH /api/conversations/{id}/discard` — validates status in (`awaiting_speaker_review`, `triage_rejected`, `awaiting_claim_review`), sets `processing_status = 'discarded'`, logs correction_event
  - `api.js`: `discardConversation(id, reason)` method
  - **SpeakerReview.jsx**: red "✗ Discard" button next to "Confirm & Start Extraction", with confirmation dialog
  - **Review.jsx**: "✗" discard button on speaker review cards, "Discard" button on TriageCard (triage_rejected conversations)
  - **ConversationDetail.jsx**: "✗ Discard" button in header next to "Mark as Reviewed" (for completed/awaiting_claim_review)
  - All discard buttons: confirmation dialog, disabled state during async, navigate to /review on success
  - `discarded` added as 10th pipeline status (terminal)
- **Speaker assignment fix (March 9, 2026):**
  - Root cause: `speaker-matches` endpoint only queried `voice_match_log`. Manual assignments via `correctSpeaker` updated `transcripts.speaker_id` but never inserted new voice_match_log entries. After assignment, `loadData()` got same (now overridden) match data — UI appeared unchanged
  - Fix: Updated endpoint to filter out `was_correct=0` entries AND include manual assignments by joining transcripts with unified_contacts. Returns `match_method: "manual"` for manually assigned speakers
- **Summary tab fix (March 9, 2026):**
  - Root cause: `CommitmentRow` was rewritten (Phase 3 refactor) to expect `claim` prop but SummaryTab still passed `commitment` from synthesis objects. `claim` was undefined → `claim.claim_text` TypeError → blank page
  - Fix: Rewrote SummaryTab commitments section to use live `claims` prop, filtering by `claim_type === 'commitment'` with direction-based grouping (owed_by_me / owed_to_me)
- **Bug fixes (March 9, 2026):**
  - `handleAddClaim` and `handleReassign` restored at component level in ConversationDetail.jsx (were removed from `.map()` by automated fix but insertion pattern didn't match for re-addition)
  - Hooks before early returns — moved all useState/useEffect calls above conditional returns
  - React.useState/useEffect → useState/useEffect (named imports, not React. prefix)
  - Orphaned `setClaims` → proper `updateClaim` callback
  - Review.jsx: `reload()` → `loadData()` in discard handler

### Not Yet Built (per spec)
- **Today**: temporal awareness (morning vs evening mode), empty states, recency display, **routing status display** (failed routes, pending-entity holds via `GET /pipeline/routing-status` — endpoint exists per Integration Spec v2 Section 15.5 but frontend call not yet wired)
- **Prep**: single launcher input, surprise call card, topic brief, meeting game plan with briefing lock
- **Review**: Quick Pass mode (swipeable claim card stream), daily "what changed" review
- **Search**: command palette with keyboard shortcuts (/, T, P, R, S), vague query handling
- **Compression principle**: 3-second / 15-second / 2-minute views per object
- **Confidence cues**: belief state families (Solid/Shifting/Contested/Stale/Under Review) across surfaces
- **Belief movement visualization**: transition display across Prep and Today surfaces (implemented in BeliefReview but not globally)
- **Mobile-responsive**: phone-optimized prep and today views
- **Email upload**: drag-and-drop zone
