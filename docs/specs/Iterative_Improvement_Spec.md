# Iterative Improvement System — Design Spec

*Supersedes Section 12 of the plan. correction_events table and object-level fixes in Phase 7. Pattern detection, four-bucket routing, and prompt amendments in Phase 10. Confidence calibration and outcome-based learning are later phases.*

This document defines how Sauron learns from corrections. It supersedes Section 12 of the plan. Do not build iterative improvement as "monthly batch → rewrite prompt." Build it as the layered system described below.

## Core Principle

Object-level correction first, generalize second. When something is wrong, fix the specific object immediately (edit the claim, reassign the speaker, downgrade the belief). Log the error type. Only propose system-level changes when patterns emerge across many corrections. The system should improve mostly by getting better at structured objects and promotion rules, not by endlessly rewriting one giant extraction prompt.

## 1. Correction Events Table

Replace the existing extraction_corrections table with this:

```sql
CREATE TABLE correction_events (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    episode_id TEXT,
    claim_id TEXT,
    belief_id TEXT,
    error_type TEXT,           -- see taxonomy below
    old_value TEXT,
    new_value TEXT,
    user_feedback TEXT,
    correction_source TEXT,    -- 'manual_ui', 'bulk_review', 'system_detected'
    created_at DATETIME DEFAULT (datetime('now'))
);
```

## 2. Error Taxonomy

Every correction must be tagged with an error type. This determines which layer gets fixed:

- `speaker_resolution` — wrong speaker assignment
- `bad_episode_segmentation` — episode boundary wrong or episode type wrong
- `missed_claim` — claim should have been extracted but wasn't
- `hallucinated_claim` — claim was extracted but shouldn't exist
- `wrong_claim_type` — e.g. labeled as fact when it's a position
- `wrong_modality` — stated vs inferred vs implied
- `wrong_polarity` — positive/negative/neutral/mixed
- `wrong_confidence` — too high or too low
- `wrong_stability` — stable_fact vs soft_inference vs transient
- `bad_entity_linking` — claim linked to wrong person or topic
- `bad_commitment_extraction` — missed commitment or false commitment
- `bad_belief_synthesis` — belief derived incorrectly from claims
- `overstated_position` — position stronger than evidence supports
- `bad_recommendation` — suggestion was wrong, badly timed, or wrong framing

## 3. The Correction Loop

```
extract → review → correct objects → log error type → detect patterns → update prompts/schema/rules → rerun derived layers
```

Step by step:

**Immediate (on every correction):**
- Fix the specific object (edit claim text, change polarity, reassign speaker, downgrade belief, etc.)
- Log the correction event with error_type
- If the corrected object is a claim that supports a belief, mark that belief as under_review
- Re-synthesize affected beliefs from corrected claims
- Tag belief updates driven by corrections as correction-driven (not new-evidence-driven) — this matters for confidence calibration

**Periodic (every 50 corrections or monthly, whichever comes first):**
- Scan correction_events for patterns
- Weight recent corrections more heavily than old ones (EMA decay — corrections from 3 months ago when the system was rough count less than corrections from last week)
- Ask: are we repeatedly making the same kind of error?

**Only when patterns are clear:**
- Propose a system-level fix routed to the correct bucket (see below)
- Present the proposed fix for human review before applying

## 4. Four Fix Buckets

Not everything is a prompt problem. When patterns emerge, route the fix to the right layer:

**A. Prompt fix** — Use when the model is consistently misunderstanding instructions. Example: Claude keeps labeling weak vibes as stated instead of inferred. Fix: Tighten extraction instructions and examples for modality in the Sonnet claims prompt.

**B. Schema fix** — Use when the data model is too crude. Example: "contradicted" is too blunt; many cases are actually "qualified." Fix: Add belief states or refine field definitions.

**C. Threshold / rule fix** — Use when the logic is okay but trigger levels are off. Example: Beliefs get promoted to active from one weak claim too early. Fix: Require 2 supporting claims or higher confidence before promotion to active.

**D. UI / workflow fix** — Use when the model may be okay but review is too hard. Example: You only notice missed claims when rereading giant summaries. Fix: Add a compact claim review screen per episode.

## 5. Beliefs Are Rebuildable Views Over Evidence

Do NOT treat beliefs as fragile hand-edited objects. Beliefs should be re-synthesizable from claims plus prior state. If claim quality improves, or confidence scoring improves, or belief-state logic improves, you should be able to recompute beliefs from their underlying claims without rebuilding the system manually.

This means the beliefs table is more like a maintained view over evidence, not a one-time generated paragraph.

## 6. Belief States

The full set of belief states (add under_review to what's in the plan):

- **active** — high confidence, well supported
- **provisional** — new, limited evidence
- **refined** — narrowed or made more specific by new evidence
- **qualified** — true but with caveats
- **time_bounded** — true now but expected to change
- **superseded** — replaced by newer information
- **contested** — conflicting evidence
- **stale** — no recent confirmation
- **under_review** — a supporting claim was just corrected; do not surface in game plans or morning email until re-synthesized

## 7. Generalization Gating

Not every correction should generalize. Rules:

**Should generalize faster (pattern detected across 3+ corrections):**
- Repeated wrong modality assignments
- Repeated wrong claim type
- Repeated over-promotion of beliefs from weak evidence
- Repeated missed commitments
- Repeated wrong confidence direction (always too high or too low)

**Should stay local unless repeated 5+ times:**
- One-off speaker confusion
- One unusual relationship inference
- A niche topic-specific nuance
- Edge case entity linking failure

This prevents overfitting to isolated cases.

## 8. Confidence Calibration (Later Phase)

Initially, confidence is model-produced. Over time, add empirical calibration:

- If inferred negative position claims are corrected 40% of the time → reduce default confidence for that class
- If commitment claims with direct quotes are rarely corrected → increase trust
- If claims from noisy Pi ambient capture are less reliable → discount slightly
- Track correction rate per claim_type × modality × source combination

Confidence becomes: model judgment + empirical correction rate.

## 9. Outcome-Based Learning for Recommendations (Later Phase)

When Sauron suggests an action (follow up with Heath, use a concrete ask, mention reciprocity angle), track what happened:

- Did you follow the suggestion?
- Did they respond?
- Did the meeting happen?
- Did the relationship warm or cool?
- Did the ask succeed?

Over time this creates a dataset: which recommendation types work for which people, which framing styles produce responses, which meeting patterns correlate with progress, which recommendations you consistently ignore.

This is much more powerful than just tracking whether the user edited the recommendation text.

## 10. Review Surfaces (Build in Phase 8 Sauron App)

Correction must be friction-light or it won't happen enough. The right review atoms:

**Episode review:** Claims extracted from one episode. Accept/edit/delete each claim quickly. This is the primary review surface.

**Belief review:** Current belief, supporting evidence, conflicting evidence. Mark as refined/qualified/stale/contested/under_review.

**Daily "what changed" review:** Confirm whether the deltas are real. Quick yes/no per change.

**Recommendation feedback (later phases):** Useful / not useful / wrong timing / wrong person / wrong framing.

Do NOT require reviewing whole transcripts unless the user specifically wants to. The default review unit is the episode, not the conversation.

## 11. Correction Provenance on Derived Objects

When a belief gets updated because an underlying claim was corrected, tag that belief update as correction_driven, not new_evidence. This lets the system distinguish:

- "This belief changed because we learned something new" (good — the system is working)
- "This belief changed because we fixed a bad extraction" (diagnostic — the extraction needs improvement)

A belief that keeps getting correction-driven updates is less trustworthy than one that keeps getting new-evidence updates. This feeds into confidence calibration.

## Build Order

- **Phase 7:** correction_events table and object-level fix flow
- **Phase 10:** Pattern detection, four-bucket routing, and prompt amendment generation
- **Later phases:** Confidence calibration and outcome-based learning

---

## Implementation Status (March 8, 2026)

### Phase 7 — COMPLETE
- **correction_events table** created with full schema (id, conversation_id, episode_id, claim_id, belief_id, error_type, old_value, new_value, user_feedback, correction_source)
- **Error taxonomy** implemented — all 14 error types with validation
- **Object-level fixes** via API endpoints:
  - POST /api/correct/claim — edit claim text, change type/modality/polarity/confidence, dismiss hallucinated claims
  - POST /api/correct/speaker — reassign speaker, cascade to transcripts + voice match log
  - POST /api/correct/belief — change belief status (including under_review)
  - POST /api/correct/event — generic correction event logging
  - GET /api/correct/error-types — list taxonomy + generalization thresholds
- **Belief under_review** — when a claim is corrected, all beliefs supported by that claim are automatically marked under_review
- **Legacy compatibility** — POST /api/correct/extraction still works, logs to both tables
- **Frontend inline corrections** — ClaimsTab in ConversationDetail has Edit + Flag buttons with error taxonomy dropdown

### Phase 10 — COMPLETE (core)
- **Generalization gating** — fast types (wrong_modality, wrong_claim_type, wrong_confidence, bad_commitment_extraction, overstated_position) trigger at 3 corrections, all others at 5
- **Four-bucket routing** — amendment prompt classifies each pattern as Prompt Fix, Schema Fix, Threshold Fix, or UI/Workflow Fix; only writes prompt rules for bucket A
- **Pattern detection** — reads from correction_events table, falls back to extraction_corrections
- **Weekly scheduled job** — runs every Sunday at midnight via APScheduler
- **Manual trigger** — POST /api/learning/analyze
- **Learning review page** — /learning route with amendment viewer/editor, correction stats by type, amendment history with activate/deactivate, contact preference management
- **Amendment CRUD** — view, edit, activate/deactivate amendments; all versioned in prompt_amendments table

### Review Surface — COMPLETE (March 8, 2026)
- **Episode-level review** — primary review atom per spec. Expandable accordion per episode in ConversationDetail, claims grouped by episode_id
- **Per-claim actions** — approve (checkmark), flag (error taxonomy dropdown), edit (inline textarea) on every claim
- **Approve All per episode** — one-click bulk approval
- **Entity linking** — tap claim subject_name to search and link to unified_contacts. Distinct from speaker correction: entity linking = who the claim is ABOUT; speaker correction = who SAID it
- **Speaker correction** — click speaker label in transcript tab to reassign via contact search dropdown
- **Inline transcript editing** — click transcript text to edit Whisper misspellings; preserves original_text, sets user_corrected flag
- **Mark as Reviewed** — conversation-level button that sets reviewed_at AND triggers routing to downstream apps. Routing is deferred until review (hold-until-review is the permanent default)
- **Needs Review vs Recently Reviewed** — Review page splits conversations into two sections with episode/claim counts
- **Contact sync** — 391 contacts synced from Networking App with relationship labels (partnerName, personalGroup, howWeMet, personalRing, tags) stored as JSON
- **Relational entity resolution** — pipeline pass after Sonnet claims extraction auto-resolves casual references ("my brother", "his wife") against unified_contacts relationship data and aliases
- **Hold-until-review routing** — pipeline no longer routes extraction results to downstream apps immediately. Routing is triggered only when user clicks Mark as Reviewed
- **Entity linking bug fixes** (March 8, 2026):
  - Inline re-render on entity add/remove — EpisodesTab and ClaimsTab use local state (useState + useEffect sync from parent props); entity mutations trigger `setClaims(prev => [...prev])` for immediate React re-render without page refresh
  - Full-name text replacement — `replace_name_in_text()` in entity_helpers.py uses word-boundary regex for old-name-to-new-name substitution in claim text; complements existing `replace_confirmed_name` which only handles first-name-to-full-name
  - Bulk reassign with display name override — modal includes text input for custom name; transcript reassign scoped to matching speaker_id only
  - Shared relational terms module — `sauron/api/relational_terms.py` with ~80 default terms (family, professional, social, medical, legal) plus DB-learned terms; replaces hardcoded sets in corrections.py, graph.py, entity_resolver.py
  - Entity resolver target mapping fix — relational lookup maps terms to TARGET contacts (who the relationship points to) not ANCHOR contacts (who has the relationship JSON); uses contacts_by_id dict for correct resolution
  - Relational reference anchor editing — pencil button + search dropdown UI to change anchor contact
  - Multi-target relationship save — relationship form supports editable relationship type, source person display, multiple targets with "Add another person" button; frontend loops api.saveRelationship() per target
  - Save-relationship endpoint logging — logs anchor/relationship/target and full JSON payload for debugging

### Belief Review Surface — COMPLETE (March 9, 2026)
- **BeliefReview.jsx** — NEW page at `/review/beliefs`: two-mode view (Needs Attention / Recent Movement)
- **BeliefCard** — expandable evidence drill-down (linked claims with quotes, source conversations), status-specific action buttons (confirm/refine/qualify/mark contested/mark stale/mark under_review)
- **Status family grouping** — Solid (Active, Refined), Shifting (Provisional, Qualified, Time-bounded), Contested, Stale, Under Review — color-coded chips per spec confidence cues
- **belief_transitions table** — tracks all status changes with source type (new_evidence, correction, user_action), old/new status, reasoning
- **6 new API endpoints** — beliefs stats, recent beliefs, recent transitions, belief evidence, per-belief transitions, enhanced list with status/person/topic filters
- **Transition writes from pipeline** — new_evidence (extraction), correction (claim corrections), user_action (manual review actions)
- **Integration** — route at `/review/beliefs`, Beliefs section on Review page links to BeliefReview when beliefs exist (total > 0), shows only actionable items (under_review/contested/stale) plus recent movement
- **Browse All Beliefs** — NOT on Review page per design decision; belongs on Search page (Beliefs tab, not yet built)

### Conversation Discard — COMPLETE (March 9, 2026)
- Discard is a terminal pipeline status available from `awaiting_speaker_review`, `triage_rejected`, and `awaiting_claim_review`
- Logs `conversation_discarded` error_type in correction_events table for pattern tracking
- Discard buttons available on SpeakerReview page, Review page cards (speaker + triage), and ConversationDetail header

### Not Yet Built (Later Phases per spec)
- EMA decay weighting for correction recency
- Confidence calibration (empirical correction rates per claim_type x modality x source)
- Outcome-based learning for recommendations
- Recommendation feedback UI
- Belief re-synthesis engine (recompute beliefs from corrected claims)
- Quick Pass review mode (swipeable claim card stream)
- Daily "what changed" review
