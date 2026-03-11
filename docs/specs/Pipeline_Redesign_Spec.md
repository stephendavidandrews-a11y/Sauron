# Pipeline Redesign — Stabilize Before Extract

*Reference document. Describes the system as built. Last updated March 9, 2026.*

---

## 1. Overview

The pipeline redesign splits Sauron's processing pipeline at the boundary between local computation and Claude API calls. All local stages (transcription, diarization, alignment, vocal analysis, speaker identification) run automatically on ingest. The pipeline then pauses for human review before invoking any LLM extraction.

Two human review points are inserted:

1. **Speaker Review** — after diarization and speaker identification, before triage. Confirms who said what.
2. **Triage Review** — after Haiku triage rejects a conversation as low-value. Prevents silent loss of potentially important recordings.

An auto-advance gate skips speaker review when all speakers are matched at high confidence, preserving the zero-friction path for well-known voices.

The design principle: do not let Claude build structured memory on top of unstable speaker identity. Stabilize audio truth first, then extract.

---

## 2. Pipeline Statuses

| Status | Description | Transition |
|--------|-------------|------------|
| `pending` | Audio file registered in DB, not yet processed | Auto-triggers transcription |
| `transcribing` | Whisper + pyannote + alignment + vocal analysis + speaker ID running | On completion: auto-advance gate decides next status |
| `awaiting_speaker_review` | Local processing complete, one or more speakers unresolved or low-confidence | User confirms speakers → triaging |
| `triaging` | Haiku triage running (classification, value assessment, episode segmentation) | High/medium value → `extracting`; low value → `triage_rejected` |
| `triage_rejected` | Haiku assessed as low value, awaiting user decision | User promotes → `extracting`; user archives → `completed` |
| `extracting` | Sonnet claims extraction + Opus synthesis running | On completion → `awaiting_claim_review` |
| `awaiting_claim_review` | Fully extracted, awaiting human claim review | User marks reviewed → `completed` |
| `completed` | Reviewed and routed to downstream apps | Terminal state |
| `discarded` | User discarded from any review queue | Terminal state |
| `error` | Processing failed at any stage | Retry returns to appropriate stage |

---

## 3. Auto-Advance Gate

After local processing (stages 0-6) completes, the system evaluates whether speaker review can be skipped:

1. All speakers in `voice_match_log` have `match_method` in (`anchor`, `voiceprint`, `calendar`)
2. All non-calendar matches have `similarity_score` > 0.85
3. At least one match exists (no matches = gate fails)

If all checks pass: auto-advance to `triaging` (skip speaker review).
If any check fails: set status to `awaiting_speaker_review`.

```python
def _check_auto_advance(conn, conversation_id: str) -> bool:
    matches = conn.execute(
        "SELECT speaker_label, similarity_score, match_method FROM voice_match_log WHERE conversation_id = ?",
        (conversation_id,)
    ).fetchall()
    if not matches:
        return False
    for m in matches:
        if m["match_method"] not in ("anchor", "voiceprint", "calendar"):
            return False
        if m["match_method"] != "calendar" and (m["similarity_score"] or 0) < 0.85:
            return False
    return True
```

---

## 4. Backend Changes

### Modified Files

| File | Changes |
|------|---------|
| `sauron/pipeline/processor.py` | Split `process_conversation` into `process_through_speaker_id()` (stages 0-6) and `process_extraction()` (stages 7-9). Added `_check_auto_advance()` gate. Triage sets `triage_rejected` instead of silently completing. `_format_transcript()` now applies annotations from `transcript_annotations` table. |
| `sauron/api/pipeline_api.py` | New endpoints: `confirm-speakers`, `promote-triage`, `archive-triage`. Added `HTTPException` import. |
| `sauron/api/conversations.py` | New endpoints: `queue-counts`, `annotations` CRUD, `speaker-matches`, `triage` data. Updated `needs-review` filter to `awaiting_claim_review`. Route ordering fix (`/queue-counts` before `/{conversation_id}`). |
| `sauron/api/corrections.py` | New endpoints: `merge-speakers`, `reassign-segment`. |
| `sauron/db/schema.py` | Added `transcript_annotations` table DDL + indexes. |
| `sauron/db/migrate.py` | Added v10 pipeline redesign migration. |
| `sauron/main.py` | Registered `audio_api` router. Updated file watcher callback to use `process_through_speaker_id()`. |

### New Files

| File | Purpose |
|------|---------|
| `sauron/api/audio_api.py` | Audio serving — full file, ffmpeg clip extraction (`/clip?start=X&end=Y`), speaker sample (longest 3-15s segment). Cached clips in `/tmp/sauron_clips/`. Uses `_find_tool("ffmpeg")` pattern for Homebrew fallback. |

---

## 5. Frontend Changes

### Modified Files

| File | Changes |
|------|---------|
| `frontend/src/pages/Review.jsx` | Replaced with 6-section queue view: Speaker Review (purple), Triage Check (yellow, inline expand with promote/archive), Claim Review (blue), Processing, Pending, Recently Reviewed. |
| `frontend/src/pages/ConversationDetail.jsx` | "Confirm Speakers" link for `awaiting_speaker_review`. "Mark as Reviewed" accepts `awaiting_claim_review`. |
| `frontend/src/pages/Today.jsx` | `ProcessingChip` handles all 10 statuses. |
| `frontend/src/pages/Triage.jsx` | Includes `triage_rejected` conversations. |
| `frontend/src/components/NavBar.jsx` | Badge count on Review tab. Receives `badgeCounts` prop from App. |
| `frontend/src/App.jsx` | Route `/review/:id/speakers` → SpeakerReview. Badge polling (30s interval). |
| `frontend/src/api.js` | 15 new methods for pipeline queues, audio, annotations, speaker ops. |

### New Files

| File | Purpose |
|------|---------|
| `frontend/src/pages/SpeakerReview.jsx` | Speaker review workbench. Speaker summary cards with match confidence, audio sample playback, contact assignment, speaker merge. Full transcript with per-segment playback. "Confirm & Start Extraction" button. |

---

## 6. API Endpoints

### Pipeline API (`/api/pipeline/`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/confirm-speakers/{id}` | Validates `awaiting_speaker_review` status, starts `process_extraction()` in background thread. |
| `POST` | `/promote-triage/{id}` | Validates `triage_rejected` status, starts extraction (skipping triage) in background thread. |
| `POST` | `/archive-triage/{id}` | Validates `triage_rejected`, sets `completed` + `reviewed_at`. |

### Conversations API (`/api/conversations/`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/queue-counts` | Returns `{speaker_review, triage_review, claim_review, processing, pending}` counts. |
| `GET` | `/{id}/speaker-matches` | Voice match log entries (filtering `was_correct=0`) PLUS manual assignments from transcripts table. Returns both voiceprint-based and manually assigned speakers. |
| `GET` | `/{id}/triage` | Triage extraction JSON + episode list. |
| `GET` | `/{id}/annotations` | List transcript annotations for conversation. |
| `POST` | `/annotations` | Create transcript annotation. |
| `DELETE` | `/annotations/{id}` | Delete transcript annotation. |
| `PATCH` | `/{id}/discard` | Validates status is in allowed set (`awaiting_speaker_review`, `triage_rejected`, `awaiting_claim_review`), sets `discarded`, logs correction_event. |

### Audio API (`/api/audio/`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/{id}` | Serve full audio file. |
| `GET` | `/{id}/clip?start=X&end=Y` | FFmpeg clip extraction, cached WAV. |
| `GET` | `/{id}/speaker-sample/{label}` | Best representative clip for speaker (3-15s). |

### Corrections API (`/api/correct/`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/merge-speakers` | Bulk update speaker_label across transcripts + voice_match_log. |
| `POST` | `/reassign-segment` | Single transcript segment speaker_label change. |

---

## 7. File Watcher Flow

1. New audio file appears in `inbox/{pi,plaud,iphone,email}/` (via rsync, manual copy, etc.)
2. Watchdog `FileCreatedEvent` fires, `AudioInboxHandler._register_file()` creates conversation + audio_file records, status = `pending`
3. `on_new_file` callback fires `process_through_speaker_id(conversation_id)` in a daemon thread
4. Local processing runs: audio prep → Whisper → pyannote → alignment → store → vocal analysis → speaker ID
5. Auto-advance gate evaluates speaker matches:
   - **Gate passes** (all speakers resolved with high confidence): status advances to `triaging`, `process_extraction()` runs triage + extraction automatically
   - **Gate fails** (unmatched/low-confidence speakers): status set to `awaiting_speaker_review`, pipeline pauses
6. Conversation appears in Review page queue. User reviews speakers, clicks "Confirm & Start Extraction" to resume.

---

## 8. Implementation Status

All items **COMPLETE** as of March 9, 2026.

| Component | Status |
|-----------|--------|
| Pipeline split (`process_through_speaker_id` / `process_extraction`) | COMPLETE |
| 10-status processing model | COMPLETE |
| Auto-advance gate | COMPLETE |
| Audio clip serving (ffmpeg) | COMPLETE |
| Speaker sample endpoint | COMPLETE |
| Transcript annotations table + CRUD API | COMPLETE |
| Queue counts endpoint | COMPLETE |
| Confirm speakers / promote / archive triage endpoints | COMPLETE |
| Merge speakers / reassign segment endpoints | COMPLETE |
| Review.jsx — 6 queue sections | COMPLETE |
| SpeakerReview.jsx — speaker review workbench | COMPLETE |
| NavBar badge count with 30s polling | COMPLETE |
| api.js — 15 new methods | COMPLETE |
| ProcessingChip — all 10 statuses | COMPLETE |
| ConversationDetail — status-aware buttons | COMPLETE |
| File watcher → `process_through_speaker_id()` | COMPLETE |
| Discard endpoint (`PATCH /{id}/discard`) | COMPLETE |
| `discarded` terminal pipeline status (10th status) | COMPLETE |
| Speaker-matches includes manual assignments | COMPLETE |

---

## 9. Design Decisions

### Browse All Beliefs

Browse All Beliefs: Browsing healthy/active beliefs does not belong on the Review page (which is a work queue for actionable items). The right home for belief exploration is the Search page — add a 'Beliefs' tab to Search that queries by person, topic, or keyword. The Prep page should also surface per-person beliefs in game plan context. The Review page's Belief section always shows when beliefs exist (total > 0), but the BeliefReview page itself only shows beliefs needing attention (under_review/contested/stale) and recent movement.
