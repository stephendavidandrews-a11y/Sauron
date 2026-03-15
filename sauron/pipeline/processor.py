"""Pipeline orchestrator — processes audio files end-to-end.

Coordinates: transcription -> diarization -> alignment -> vocal analysis
-> speaker ID -> (auto-advance gate) -> three-pass Claude extraction
-> storage -> routing -> embedding.

UPDATED (v6):
  - Three-pass extraction: Haiku triage+episodes -> Sonnet claims -> Opus synthesis
  - Claims and episodes stored in new tables (event_episodes, event_claims)
  - Belief updates stored in beliefs/belief_evidence tables
  - Amendment context integrated into all extraction passes
  - Meeting intentions auto-linked when target contact participates

UPDATED (v7 — pipeline redesign):
  - Split into process_through_speaker_id() + process_extraction()
  - Auto-advance gate after speaker ID (skip speaker review if high confidence)
  - New statuses: transcribing, awaiting_speaker_review, triaging,
    triage_rejected, extracting, awaiting_claim_review
  - Calendar attendee integration for speaker resolution
  - Annotation-enriched transcript formatting for Claude
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sauron.config import DB_PATH
from sauron.db.connection import get_connection
from sauron.pipeline.transcriber import transcribe
from sauron.pipeline.diarizer import diarize
from sauron.pipeline.aligner import align, AlignedTranscript, AlignedSegment, AlignedWord
from sauron.pipeline.audio_prep import prepare_audio

logger = logging.getLogger(__name__)


# =====================================================
# PUBLIC API
# =====================================================

def process_conversation(conversation_id: str) -> bool:
    """Process a single conversation through the full pipeline.

    Backward-compatible wrapper: calls process_through_speaker_id(),
    and if the auto-advance gate passes, continues to process_extraction().

    Returns True on success, False on failure.
    """
    result = process_through_speaker_id(conversation_id)
    if not result:
        return False
    conn = get_connection()
    try:
        status = conn.execute(
            "SELECT processing_status FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if status and status["processing_status"] == "awaiting_speaker_review":
            logger.info(f"[{conversation_id[:8]}] Paused at speaker review — human review needed")
            return True
    finally:
        conn.close()
    return True


def process_through_speaker_id(conversation_id: str) -> bool:
    """Process Stages 0-6: audio prep through speaker identification.

    After Stage 6, runs the auto-advance gate:
    - If all speakers resolved at high confidence -> calls _continue_to_extraction()
    - If any speaker unresolved -> sets status to awaiting_speaker_review and stops
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if not row:
            logger.error(f"Conversation not found: {conversation_id}")
            return False

        audio_row = conn.execute(
            "SELECT * FROM audio_files WHERE conversation_id = ?", (conversation_id,)
        ).fetchone()
        if not audio_row:
            logger.error(f"No audio file for conversation: {conversation_id}")
            return False

        audio_path = Path(audio_row["current_path"])
        if not audio_path.exists():
            logger.error(f"Audio file not found: {audio_path}")
            _update_status(conn, conversation_id, "error")
            return False

        _update_status(conn, conversation_id, "transcribing")

        # Check for existing transcripts (skip Stages 0-4 if found)
        existing_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM transcripts WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()["cnt"]

        if existing_count > 0:
            logger.info(
                f"[{conversation_id[:8]}] Reusing {existing_count} existing transcript segments — skipping Stages 0-4"
            )
            aligned, speaker_map = _reconstruct_from_db(conn, conversation_id)
            if aligned is None:
                logger.error(f"[{conversation_id[:8]}] Failed to reconstruct transcript from DB")
                _update_status(conn, conversation_id, "error")
                return False

            speakers_already_identified = any(v for v in speaker_map.values())

            logger.info(f"[{conversation_id[:8]}] Stage 5: Vocal analysis...")
            vocal_summary = _run_vocal_analysis(conversation_id, audio_path, aligned)

            if not speakers_already_identified:
                logger.info(f"[{conversation_id[:8]}] Stage 6: Speaker identification...")
                # Load stored voice embeddings from DB (saved during original processing)
                stored_embeddings = _load_stored_embeddings(conn, conversation_id)
                from sauron.pipeline.diarizer import DiarizationResult, SpeakerSegment
                diarization = DiarizationResult(
                    segments=[SpeakerSegment(speaker=s, start=0.0, end=aligned.duration) for s in aligned.speakers],
                    embeddings=stored_embeddings,
                    num_speakers=len(aligned.speakers),
                )
                speaker_map = _run_speaker_identification(conn, conversation_id, diarization, aligned)
                conn.commit()
            else:
                logger.info(f"[{conversation_id[:8]}] Stage 6: Speakers already identified — skipping")

            conn.commit()

            # Auto-advance gate (same check as fresh-processing path)
            if _check_auto_advance(conn, conversation_id):
                logger.info(f"[{conversation_id[:8]}] Auto-advance gate PASSED (transcript reuse) — proceeding to extraction")
                return _continue_to_extraction(conn, conversation_id, aligned, speaker_map, vocal_summary)
            else:
                logger.info(f"[{conversation_id[:8]}] Auto-advance gate FAILED (transcript reuse) — pausing for speaker review")
                _update_status(conn, conversation_id, "awaiting_speaker_review")
                conn.commit()
                return True

        # Stage 0: Audio preprocessing
        try:
            cache_dir = audio_path.parent / ".prepared"
            prepared_path = prepare_audio(audio_path, cache_dir=cache_dir)
        except Exception as e:
            logger.warning(f"Audio preprocessing failed ({type(e).__name__}: {e}) — using original file")
            prepared_path = audio_path

        # Stage 1: Transcription
        logger.info(f"[{conversation_id[:8]}] Stage 1: Transcribing...")
        transcription = transcribe(audio_path)

        conn.execute(
            "UPDATE conversations SET duration_seconds = ? WHERE id = ?",
            (transcription.duration, conversation_id),
        )

        # Stage 2: Diarization
        logger.info(f"[{conversation_id[:8]}] Stage 2: Diarizing...")
        try:
            diarization = diarize(prepared_path)
        except Exception as e:
            logger.warning(f"[{conversation_id[:8]}] Diarization failed ({type(e).__name__}: {e}) — falling back to single-speaker mode")
            diarization = _single_speaker_fallback(transcription.duration)
            # Try to recover stored embeddings from a previous processing run
            stored_emb = _load_stored_embeddings(conn, conversation_id)
            if stored_emb:
                diarization = DiarizationResult(
                    segments=diarization.segments,
                    embeddings=stored_emb,
                    num_speakers=len(stored_emb),
                )
                logger.info(f"[{conversation_id[:8]}] Recovered {len(stored_emb)} stored embeddings after diarization failure")

        # Stage 3: Alignment
        logger.info(f"[{conversation_id[:8]}] Stage 3: Aligning transcript with speakers...")
        aligned = align(transcription, diarization)

        # Stage 4: Store transcript
        logger.info(f"[{conversation_id[:8]}] Storing {len(aligned.segments)} transcript segments...")
        _store_transcript(conn, conversation_id, aligned)
        _store_voice_samples(conn, conversation_id, diarization, row["source"])
        conn.commit()

        # Stage 5: Vocal analysis
        logger.info(f"[{conversation_id[:8]}] Stage 5: Vocal analysis...")
        vocal_summary = _run_vocal_analysis(conversation_id, audio_path, aligned)

        # Stage 6: Speaker identification
        logger.info(f"[{conversation_id[:8]}] Stage 6: Speaker identification...")
        speaker_map = _run_speaker_identification(
            conn, conversation_id, diarization, aligned
        )
        conn.commit()

        # Auto-advance gate
        if _check_auto_advance(conn, conversation_id):
            logger.info(f"[{conversation_id[:8]}] Auto-advance gate PASSED — proceeding to extraction")
            return _continue_to_extraction(conn, conversation_id, aligned, speaker_map, vocal_summary)
        else:
            logger.info(f"[{conversation_id[:8]}] Auto-advance gate FAILED — pausing for speaker review")
            _update_status(conn, conversation_id, "awaiting_speaker_review")
            conn.commit()
            # Generate title from transcript so speaker review page shows meaningful names
            try:
                _title_check = conn.execute(
                    "SELECT title FROM conversations WHERE id = ?", (conversation_id,)
                ).fetchone()
                if not _title_check or not _title_check["title"]:
                    from sauron.extraction.triage import generate_title_from_transcript
                    _transcript_segs = conn.execute(
                        "SELECT GROUP_CONCAT(text, ' ') as full_text FROM transcripts WHERE conversation_id = ?",
                        (conversation_id,),
                    ).fetchone()
                    if _transcript_segs and _transcript_segs["full_text"]:
                        _title = generate_title_from_transcript(_transcript_segs["full_text"])
                        if _title:
                            conn.execute(
                                "UPDATE conversations SET title = ? WHERE id = ?",
                                (_title, conversation_id),
                            )
                            conn.commit()
                            logger.info(f"[{conversation_id[:8]}] Title from transcript: {_title}")
            except Exception as e:
                logger.warning(f"[{conversation_id[:8]}] Title gen failed (non-fatal): {e}")
            logger.info(
                f"[{conversation_id[:8]}] Pipeline paused at speaker review: "
                f"{len(aligned.speakers)} speakers, "
                f"{len(aligned.segments)} segments, "
                f"{transcription.duration:.0f}s"
            )
            return True

    except Exception:
        conn.rollback()
        logger.exception(f"Pipeline failed for conversation {conversation_id}")
        try:
            _update_status(conn, conversation_id, "error")
            conn.commit()
        except Exception:
            pass
        return False
    finally:
        conn.close()


def _continue_to_extraction(conn, conversation_id, aligned, speaker_map, vocal_summary):
    """Continue from speaker ID to extraction (used by both auto-advance and transcript reuse)."""
    try:
        transcript_text = _format_transcript(aligned, speaker_map, conversation_id)
        return _run_full_extraction_pipeline(
            conn, conversation_id, transcript_text, vocal_summary, speaker_map
        )
    except Exception:
        conn.rollback()
        logger.exception(f"Pipeline failed during extraction for {conversation_id}")
        try:
            _update_status(conn, conversation_id, "error")
            conn.commit()
        except Exception:
            pass
        return False


def _try_extraction_comparison(conversation_id: str, new_extraction_id: str = None):
    """Compare new extraction against previous if exists (Feature 5)."""
    try:
        conn = get_connection()
        try:
            # Find the latest extraction for this conversation
            if new_extraction_id:
                prev = conn.execute(
                    """SELECT id FROM extractions
                       WHERE conversation_id = ? AND id != ?
                       ORDER BY created_at DESC LIMIT 1""",
                    (conversation_id, new_extraction_id),
                ).fetchone()
            else:
                # Get the two most recent extractions
                rows = conn.execute(
                    """SELECT id FROM extractions
                       WHERE conversation_id = ?
                       ORDER BY created_at DESC LIMIT 2""",
                    (conversation_id,),
                ).fetchall()
                if len(rows) < 2:
                    return
                new_extraction_id = rows[0]["id"]
                prev = rows[1]

            if prev:
                from sauron.learning.compare import compare_extractions
                comparison = compare_extractions(
                    conversation_id, prev["id"], new_extraction_id
                )
                if comparison:
                    logger.info(
                        "Reprocessing comparison: %d reproduced, %d missed, "
                        "%d new, %d corrections resolved",
                        comparison.get("claims_reproduced", 0),
                        comparison.get("claims_missed", 0),
                        comparison.get("claims_new", 0),
                        comparison.get("corrections_resolved", 0),
                    )
        finally:
            conn.close()
    except Exception:
        logger.exception("Extraction comparison failed (non-fatal)")


def process_extraction(conversation_id: str) -> bool:
    """Process Stages 7-9: triage, extraction, embedding.

    Called after speaker review confirms speakers, or after auto-advance.
    Sets status through triaging -> extracting -> awaiting_claim_review.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if not row:
            logger.error(f"Conversation not found: {conversation_id}")
            return False

        aligned, speaker_map = _reconstruct_from_db(conn, conversation_id)
        if aligned is None:
            logger.error(f"[{conversation_id[:8]}] No transcript found for extraction")
            _update_status(conn, conversation_id, "error")
            return False

        vocal_summary = _get_vocal_summary(conn, conversation_id)
        transcript_text = _format_transcript(aligned, speaker_map, conversation_id)

        return _run_full_extraction_pipeline(
            conn, conversation_id, transcript_text, vocal_summary, speaker_map
        )

    except Exception:
        conn.rollback()
        logger.exception(f"Extraction pipeline failed for {conversation_id}")
        try:
            _update_status(conn, conversation_id, "error")
            conn.commit()
        except Exception:
            pass
        return False
    finally:
        conn.close()


def process_extraction_skip_triage(conversation_id: str) -> bool:
    """Run extraction Stages 7.2-9 only, skipping triage (already ran).

    Called when user promotes a triage_rejected conversation.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if not row:
            logger.error(f"Conversation not found: {conversation_id}")
            return False

        aligned, speaker_map = _reconstruct_from_db(conn, conversation_id)
        if aligned is None:
            logger.error(f"[{conversation_id[:8]}] No transcript for extraction")
            _update_status(conn, conversation_id, "error")
            return False

        vocal_summary = _get_vocal_summary(conn, conversation_id)
        transcript_text = _format_transcript(aligned, speaker_map, conversation_id)

        _update_status(conn, conversation_id, "extracting")
        conn.commit()

        # Load existing triage result
        triage_row = conn.execute(
            """SELECT extraction_json FROM extractions
               WHERE conversation_id = ? AND pass_number = 1
               ORDER BY rowid DESC LIMIT 1""",
            (conversation_id,),
        ).fetchone()
        if not triage_row:
            logger.error(f"[{conversation_id[:8]}] No triage result found for promoted conversation")
            _update_status(conn, conversation_id, "error")
            return False

        from sauron.extraction.schemas import TriageResult
        triage = TriageResult.model_validate_json(triage_row["extraction_json"])

        extraction_result = _run_deep_extraction_only(
            conn, conversation_id, transcript_text, vocal_summary,
            speaker_map, triage
        )
        conn.commit()

        logger.info(f"[{conversation_id[:8]}] Stage 9: Semantic embedding...")
        _run_embedding(conversation_id)

        _update_status(conn, conversation_id, "awaiting_claim_review")
        conn.commit()

        logger.info(f"[{conversation_id[:8]}] Promoted extraction complete")
        return True

    except Exception:
        conn.rollback()
        logger.exception(f"Promoted extraction failed for {conversation_id}")
        try:
            _update_status(conn, conversation_id, "error")
            conn.commit()
        except Exception:
            pass
        return False
    finally:
        conn.close()


def process_pending():
    """Process all pending conversations."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id FROM conversations WHERE processing_status = 'pending' ORDER BY captured_at"
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        logger.info("No pending conversations to process")
        return

    logger.info(f"Processing {len(rows)} pending conversations...")
    for row in rows:
        process_through_speaker_id(row["id"])


def backfill_titles():
    """Backfill titles for conversations that have triage data or transcripts but no title."""
    import time
    from sauron.extraction.triage import generate_title, generate_title_from_transcript
    from sauron.extraction.schemas import TriageResult

    conn = get_connection()
    try:
        # Conversations with triage data
        triage_rows = conn.execute(
            """SELECT c.id, e.extraction_json, NULL as raw_text
               FROM conversations c
               JOIN extractions e ON e.conversation_id = c.id AND e.pass_number = 1
               WHERE (c.title IS NULL OR c.title = '')
               ORDER BY c.captured_at"""
        ).fetchall()
        # Conversations with transcripts but no triage
        transcript_rows = conn.execute(
            """SELECT c.id, NULL as extraction_json,
                      GROUP_CONCAT(t.text, ' ') as transcript_text
               FROM conversations c
               JOIN transcripts t ON t.conversation_id = c.id
               LEFT JOIN extractions e ON e.conversation_id = c.id AND e.pass_number = 1
               WHERE (c.title IS NULL OR c.title = '') AND e.id IS NULL
               GROUP BY c.id
               ORDER BY c.captured_at"""
        ).fetchall()
    finally:
        conn.close()

    rows = list(triage_rows) + list(transcript_rows)
    if not rows:
        logger.info("No conversations need title backfill")
        return

    logger.info(f"Backfilling titles for {len(rows)} conversations ({len(triage_rows)} with triage, {len(transcript_rows)} transcript-only)...")
    success = 0
    for row in rows:
        try:
            if row["extraction_json"]:
                triage_data = json.loads(row["extraction_json"])
                title = generate_title(triage_data)
            elif row["transcript_text"]:
                title = generate_title_from_transcript(row["transcript_text"])
            else:
                continue
            if title:
                conn2 = get_connection()
                try:
                    conn2.execute(
                        "UPDATE conversations SET title = ? WHERE id = ?",
                        (title, row["id"]),
                    )
                    conn2.commit()
                    success += 1
                    logger.info(f"  [{row['id'][:8]}] -> {title}")
                finally:
                    conn2.close()
            time.sleep(0.5)  # rate limiting
        except Exception as e:
            logger.warning(f"  [{row['id'][:8]}] backfill failed: {e}")

    logger.info(f"Backfill complete: {success}/{len(rows)} titles generated")


# =====================================================
# AUTO-ADVANCE GATE
# =====================================================

def _check_auto_advance(conn, conversation_id: str) -> bool:
    """Check if all speakers are resolved at high confidence.

    Gate passes if every speaker has match_method in (anchor, voiceprint, calendar)
    AND similarity_score > 0.85 (except calendar matches which don't need score).
    """
    matches = conn.execute(
        "SELECT speaker_label, similarity_score, match_method FROM voice_match_log WHERE conversation_id = ?",
        (conversation_id,),
    ).fetchall()

    if not matches:
        return False

    for m in matches:
        method = m["match_method"]
        score = m["similarity_score"]

        if method not in ("anchor", "voiceprint", "calendar"):
            logger.debug(f"Gate fail: {m['speaker_label']} method={method}")
            return False
        if method != "calendar" and (score is None or score < 0.85):
            logger.debug(f"Gate fail: {m['speaker_label']} score={score}")
            return False

    return True


# =====================================================
# CALENDAR INTEGRATION
# =====================================================

def _get_calendar_attendees(conn, conversation_id: str) -> list[dict]:
    """Match conversation timestamp to Google Calendar events and resolve attendees.

    Returns list of {"matched_contact_id": id, "email": email} or empty list.
    Non-fatal: returns empty list on any failure.
    """
    try:
        conv = conn.execute(
            "SELECT captured_at FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if not conv or not conv["captured_at"]:
            return []

        from datetime import datetime as dt, timedelta
        import os

        captured_at_str = conv["captured_at"]
        try:
            captured_at = dt.fromisoformat(captured_at_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            logger.debug(f"Could not parse captured_at: {captured_at_str}")
            return []

        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError:
            logger.debug("Google API client not available — skipping calendar")
            return []

        token_path = os.environ.get(
            "GOOGLE_CALENDAR_TOKEN",
            os.path.expanduser("~/.config/sauron/calendar_token.json"),
        )
        if not os.path.exists(token_path):
            return []

        import json as _json
        with open(token_path) as f:
            token_data = _json.load(f)
        creds = Credentials.from_authorized_user_info(token_data)

        service = build("calendar", "v3", credentials=creds)

        from sauron.config import GOOGLE_CALENDAR_ID
        time_min = (captured_at - timedelta(minutes=30)).isoformat()
        time_max = (captured_at + timedelta(minutes=30)).isoformat()

        calendar_id = GOOGLE_CALENDAR_ID or "primary"
        events_result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = events_result.get("items", [])

        if not events:
            return []

        event = events[0]
        attendees_emails = [
            a.get("email", "") for a in event.get("attendees", [])
            if a.get("email")
        ]

        if not attendees_emails:
            return []

        event_id = event.get("id", "")
        if event_id:
            conn.execute(
                "UPDATE conversations SET calendar_event_id = ? WHERE id = ?",
                (event_id, conversation_id),
            )

        matched = []
        for email in attendees_emails:
            contact = conn.execute(
                "SELECT id FROM unified_contacts WHERE LOWER(email) = LOWER(?)",
                (email,),
            ).fetchone()
            if contact:
                matched.append({
                    "matched_contact_id": contact["id"],
                    "email": email,
                })

        logger.info(
            f"[{conversation_id[:8]}] Calendar: event '{event.get('summary', '?')}' — "
            f"{len(attendees_emails)} attendees, {len(matched)} resolved to contacts"
        )
        return matched

    except Exception as exc:
        logger.warning(f"Calendar attendee lookup failed (non-fatal): {exc}")
        return []


# =====================================================
# INTERNAL PIPELINE HELPERS
# =====================================================

def _run_full_extraction_pipeline(
    conn, conversation_id, transcript_text, vocal_summary, speaker_map
):
    """Run the complete extraction pipeline: triage -> extract -> embed.

    Handles the triage gate: low-value -> triage_rejected, high/medium -> full extraction.
    """
    _update_status(conn, conversation_id, "triaging")
    conn.commit()

    logger.info(f"[{conversation_id[:8]}] Stage 7: Three-pass Claude extraction...")
    extraction_result = _run_three_pass_extraction(
        conn, conversation_id, transcript_text, vocal_summary,
        speaker_map=speaker_map,
    )
    conn.commit()

    # Check if triage rejected (status set inside _run_three_pass_extraction)
    status = conn.execute(
        "SELECT processing_status FROM conversations WHERE id = ?",
        (conversation_id,),
    ).fetchone()
    if status and status["processing_status"] == "triage_rejected":
        logger.info(f"[{conversation_id[:8]}] Pipeline stopped at triage_rejected")
        return True

    if extraction_result:
        logger.info(f"[{conversation_id[:8]}] Stage 8: Routing deferred until review")

    # Stage 9: Semantic embedding
    logger.info(f"[{conversation_id[:8]}] Stage 9: Semantic embedding...")
    _run_embedding(conversation_id)

    # Mark as awaiting claim review (NOT completed)
    _update_status(conn, conversation_id, "awaiting_claim_review")
    conn.commit()

    # Feature 5: Compare with previous extraction if this is a reprocessing
    _try_extraction_comparison(conversation_id)

    logger.info(f"[{conversation_id[:8]}] Pipeline complete — awaiting claim review")
    return True


def _reconstruct_from_db(conn, conversation_id: str):
    """Reconstruct AlignedTranscript and speaker_map from existing DB transcripts."""
    rows = conn.execute(
        """SELECT speaker_label, speaker_id, start_time, end_time, text, word_timestamps
           FROM transcripts WHERE conversation_id = ?
           ORDER BY start_time""",
        (conversation_id,),
    ).fetchall()

    if not rows:
        return None, None

    segments = []
    speakers_set = set()
    speaker_map = {}
    max_end = 0.0

    for row in rows:
        speaker = row["speaker_label"] or "SPEAKER_00"
        speakers_set.add(speaker)

        if row["speaker_id"] and speaker not in speaker_map:
            speaker_map[speaker] = row["speaker_id"]

        words = []
        if row["word_timestamps"]:
            try:
                word_data = json.loads(row["word_timestamps"])
                for w in word_data:
                    words.append(AlignedWord(
                        word=w["word"],
                        start=w["start"],
                        end=w["end"],
                        speaker=speaker,
                        probability=w.get("probability", 1.0),
                    ))
            except (json.JSONDecodeError, KeyError):
                pass

        start = float(row["start_time"] or 0)
        end = float(row["end_time"] or 0)
        max_end = max(max_end, end)

        segments.append(AlignedSegment(
            speaker=speaker,
            start=start,
            end=end,
            text=row["text"] or "",
            words=words,
        ))

    dur_row = conn.execute(
        "SELECT duration_seconds FROM conversations WHERE id = ?",
        (conversation_id,),
    ).fetchone()
    duration = float(dur_row["duration_seconds"]) if dur_row and dur_row["duration_seconds"] else max_end

    aligned = AlignedTranscript(
        segments=segments,
        speakers=sorted(speakers_set),
        duration=duration,
    )

    return aligned, speaker_map



def _load_stored_embeddings(conn, conversation_id: str) -> dict:
    """Load speaker embeddings from voice_samples table.

    Used when reprocessing (transcript reuse) or recovering from diarization failure.
    Returns dict of speaker_label -> numpy embedding, same format as diarization.embeddings.
    """
    import numpy as np
    rows = conn.execute(
        "SELECT speaker_label, embedding FROM voice_samples WHERE source_conversation_id = ? AND embedding IS NOT NULL",
        (conversation_id,),
    ).fetchall()
    embeddings = {}
    for row in rows:
        label = row["speaker_label"]
        emb = np.frombuffer(row["embedding"], dtype=np.float32)
        embeddings[label] = emb
    if embeddings:
        logger.info(f"[{conversation_id[:8]}] Loaded {len(embeddings)} stored voice embeddings from DB")
    return embeddings


def _single_speaker_fallback(duration: float):
    """Create a minimal diarization result with a single speaker."""
    from sauron.pipeline.diarizer import DiarizationResult, SpeakerSegment
    return DiarizationResult(
        segments=[SpeakerSegment(speaker="SPEAKER_00", start=0.0, end=duration)],
        embeddings={},
        num_speakers=1,
    )


def _update_status(conn, conversation_id: str, status: str):
    """Update conversation processing status with timestamp for terminal-ish statuses.
    Also writes the unified stage model (current_stage, stage_detail, run_status).
    """
    from sauron.pipeline.stage_model import stage_for_voice_status

    terminal_statuses = (
        "transcribed", "completed", "error",
        "awaiting_speaker_review", "triage_rejected", "awaiting_claim_review",
    )
    now = datetime.now(timezone.utc).isoformat() if status in terminal_statuses else None
    current_stage, stage_detail, run_status = stage_for_voice_status(status)
    conn.execute(
        """UPDATE conversations
           SET processing_status = ?,
               processed_at = COALESCE(?, processed_at),
               current_stage = ?,
               stage_detail = ?,
               run_status = ?
           WHERE id = ?""",
        (status, now, current_stage, stage_detail, run_status, conversation_id),
    )


def _store_transcript(conn, conversation_id: str, aligned: AlignedTranscript):
    for seg in aligned.segments:
        word_timestamps = json.dumps([
            {"word": w.word, "start": w.start, "end": w.end, "probability": w.probability}
            for w in seg.words
        ])
        conn.execute(
            """INSERT INTO transcripts (id, conversation_id, speaker_label, start_time, end_time, text, word_timestamps)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), conversation_id, seg.speaker,
             seg.start, seg.end, seg.text, word_timestamps),
        )


def _store_voice_samples(conn, conversation_id: str, diarization, source: str):
    for speaker_label, embedding in diarization.embeddings.items():
        conn.execute(
            """INSERT INTO voice_samples (id, voice_profile_id, embedding, source_conversation_id,
               source_type, speaker_label, confirmation_method, created_at)
               VALUES (?, NULL, ?, ?, ?, ?, 'unmatched', datetime('now'))""",
            (str(uuid.uuid4()), embedding.tobytes(), conversation_id, source, speaker_label),
        )


def _run_vocal_analysis(conversation_id: str, audio_path: Path, aligned: AlignedTranscript) -> str | None:
    """Run Parselmouth + librosa analysis on each speaker segment."""
    try:
        from sauron.vocal.analyzer import extract_vocal_features, store_vocal_features

        summaries = []
        for seg in aligned.segments:
            if seg.end - seg.start < 1.0:
                continue
            features = extract_vocal_features(audio_path, seg.start, seg.end)
            if features:
                store_vocal_features(conversation_id, None, seg.start, seg.end, features)
                if isinstance(features.get('pitch_mean'), (int, float)):
                    summaries.append(
                        f"[{seg.speaker} {seg.start:.0f}-{seg.end:.0f}s] "
                        f"pitch={features['pitch_mean']:.0f}Hz, "
                        f"jitter={features.get('jitter', 'N/A')}, "
                        f"energy={features.get('rms_mean', 0):.4f}, "
                        f"rate={features.get('speaking_rate_wpm', 0):.0f}wpm"
                    )
                else:
                    summaries.append(f"[{seg.speaker} {seg.start:.0f}-{seg.end:.0f}s] partial features")

        return "\n".join(summaries) if summaries else None
    except Exception:
        logger.exception("Vocal analysis failed (non-fatal)")
        return None


def _get_vocal_summary(conn, conversation_id: str) -> str | None:
    """Reconstruct vocal summary from stored vocal features."""
    rows = conn.execute(
        """SELECT vf.speaker_id, vf.segment_start, vf.segment_end,
                  vf.pitch_mean, vf.jitter, vf.rms_mean, vf.speaking_rate_wpm
           FROM vocal_features vf
           WHERE vf.conversation_id = ?
           ORDER BY vf.segment_start""",
        (conversation_id,),
    ).fetchall()

    if not rows:
        return None

    summaries = []
    for r in rows:
        speaker = r["speaker_id"] or "UNKNOWN"
        start = float(r["segment_start"] or 0)
        end = float(r["segment_end"] or 0)
        pitch = r["pitch_mean"]
        if pitch is not None:
            summaries.append(
                f"[{speaker} {start:.0f}-{end:.0f}s] "
                f"pitch={float(pitch):.0f}Hz, "
                f"jitter={r['jitter'] or 'N/A'}, "
                f"energy={float(r['rms_mean'] or 0):.4f}, "
                f"rate={float(r['speaking_rate_wpm'] or 0):.0f}wpm"
            )
    return "\n".join(summaries) if summaries else None


def _run_speaker_identification(conn, conversation_id, diarization, aligned):
    """Run speaker identification with calendar attendee integration."""
    try:
        from sauron.speakers.resolver import resolve_speakers

        calendar_attendees = _get_calendar_attendees(conn, conversation_id)

        speaker_map = resolve_speakers(
            conversation_id, diarization.embeddings,
            calendar_attendees=calendar_attendees if calendar_attendees else None,
            conn=conn,
        )
        for label, contact_id in speaker_map.items():
            if contact_id:
                conn.execute(
                    "UPDATE transcripts SET speaker_id = ? WHERE conversation_id = ? AND speaker_label = ?",
                    (contact_id, conversation_id, label),
                )
        return speaker_map
    except Exception as e:
        logger.exception(f"Speaker identification failed (non-fatal): {type(e).__name__}: {e}")
        # Log the failure so it's visible in voice_match_log
        try:
            for label in diarization.embeddings:
                conn.execute(
                    """INSERT INTO voice_match_log
                       (id, conversation_id, speaker_label, matched_profile_id, similarity_score, match_method)
                       VALUES (?, ?, ?, NULL, 0.0, ?)""",
                    (str(uuid.uuid4()), conversation_id, label, f"error:{type(e).__name__}"),
                )
            conn.commit()
        except Exception:
            pass  # Don't fail the pipeline over logging
        return {}


def _format_transcript(aligned: AlignedTranscript, speaker_map: dict, conversation_id: str = None) -> str:
    """Format aligned transcript with speaker names for Claude.

    If conversation_id is provided, also applies transcript annotations
    (name/phrase -> contact resolution) from the speaker review step.
    """
    # Build name cache to avoid per-segment DB lookups
    name_cache = {}
    conn = get_connection()
    try:
        for label, contact_id in speaker_map.items():
            if contact_id and contact_id not in name_cache:
                row = conn.execute(
                    "SELECT canonical_name FROM unified_contacts WHERE id = ?",
                    (contact_id,),
                ).fetchone()
                name_cache[contact_id] = row["canonical_name"] if row else label

        # Load annotations if conversation_id provided
        annotations_by_segment = {}
        if conversation_id:
            ann_rows = conn.execute(
                """SELECT transcript_segment_id, start_char, end_char,
                          original_text, resolved_name
                   FROM transcript_annotations
                   WHERE conversation_id = ?
                   ORDER BY transcript_segment_id, start_char DESC""",
                (conversation_id,),
            ).fetchall()
            for ar in ann_rows:
                seg_id = ar["transcript_segment_id"]
                annotations_by_segment.setdefault(seg_id, []).append(dict(ar))
    finally:
        conn.close()

    # Build segment ID mapping for annotations
    segment_ids = {}
    if conversation_id and annotations_by_segment:
        conn2 = get_connection()
        try:
            id_rows = conn2.execute(
                """SELECT id, start_time, end_time, speaker_label
                   FROM transcripts WHERE conversation_id = ?
                   ORDER BY start_time""",
                (conversation_id,),
            ).fetchall()
            for ir in id_rows:
                key = (float(ir["start_time"] or 0), float(ir["end_time"] or 0), ir["speaker_label"])
                segment_ids[key] = ir["id"]
        finally:
            conn2.close()

    lines = []
    for seg in aligned.segments:
        contact_id = speaker_map.get(seg.speaker)
        name = name_cache.get(contact_id, seg.speaker) if contact_id else seg.speaker

        text = seg.text

        # Apply annotations (reverse order by start_char to preserve positions)
        if conversation_id and annotations_by_segment:
            seg_key = (seg.start, seg.end, seg.speaker)
            seg_id = segment_ids.get(seg_key)
            if seg_id and seg_id in annotations_by_segment:
                for ann in annotations_by_segment[seg_id]:
                    start_c = ann["start_char"]
                    end_c = ann["end_char"]
                    resolved = ann["resolved_name"]
                    if start_c < len(text) and end_c <= len(text):
                        text = text[:start_c] + resolved + text[end_c:]

        lines.append(f"[{seg.start:.0f}-{seg.end:.0f}s] {name}: {text}")

    return "\n".join(lines)


def _run_three_pass_extraction(
    conn,
    conversation_id: str,
    transcript_text: str,
    vocal_summary: str | None,
    speaker_map: dict | None = None,
) -> dict | None:
    """Run three-pass Claude extraction: Haiku -> Sonnet -> Opus.

    Low-value conversations now get status triage_rejected
    instead of completing silently.
    """
    try:
        from sauron.extraction.triage import triage_conversation, should_run_deep_extraction, generate_title
        from sauron.extraction.claims import extract_claims
        from sauron.extraction.dedup import dedup_claims
        from sauron.extraction.deep import synthesize, solo_extract

        amendment_context = ""
        try:
            from sauron.learning.amendments import build_extraction_context
            amendment_context = build_extraction_context(conversation_id)
        except Exception:
            logger.debug("Amendment context unavailable (non-fatal)")

        # Pass 1: Haiku triage + episode segmentation
        triage, triage_usage = triage_conversation(
            transcript_text, amendment_context=amendment_context
        )

        conn.execute(
            """INSERT INTO extractions (id, conversation_id, pass_number, extraction_json,
               extraction_version, model_used, input_tokens, output_tokens)
               VALUES (?, ?, 1, ?, 'v6.0', ?, ?, ?)""",
            (str(uuid.uuid4()), conversation_id,
             triage.model_dump_json(), "haiku-4.5",
             triage_usage.input_tokens, triage_usage.output_tokens),
        )

        _store_episodes(conn, conversation_id, triage)

        conn.execute(
            "UPDATE conversations SET context_classification = ? WHERE id = ?",
            (triage.context_classification, conversation_id),
        )

        # Generate conversation title from triage data
        try:
            title = generate_title(triage)
            if title:
                conn.execute(
                    "UPDATE conversations SET title = ? WHERE id = ?",
                    (title, conversation_id),
                )
                logger.info(f"[{conversation_id[:8]}] Title: {title}")
        except Exception as e:
            logger.warning(f"[{conversation_id[:8]}] Title generation failed (non-fatal): {e}")

        if not should_run_deep_extraction(triage):
            logger.info(f"Skipping deep extraction (value={triage.value_assessment})")
            # NEW: Set triage_rejected instead of letting it fall through to completed
            _update_status(conn, conversation_id, "triage_rejected")
            conn.commit()
            return triage.model_dump()

        # Update status to extracting (triage passed)
        _update_status(conn, conversation_id, "extracting")
        conn.commit()

        return _run_deep_extraction_only(
            conn, conversation_id, transcript_text, vocal_summary,
            speaker_map, triage, amendment_context
        )

    except Exception:
        logger.exception("Claude extraction failed (non-fatal)")
        return None


def _run_deep_extraction_only(
    conn,
    conversation_id: str,
    transcript_text: str,
    vocal_summary: str | None,
    speaker_map: dict | None,
    triage,
    amendment_context: str = "",
) -> dict | None:
    """Run Sonnet claims + Opus synthesis (Passes 2-3).

    Separated so it can be called independently when promoting triage-rejected conversations.
    """
    try:
        from sauron.extraction.claims import extract_claims
        from sauron.extraction.dedup import dedup_claims
        from sauron.extraction.deep import synthesize, solo_extract

        if not amendment_context:
            try:
                from sauron.learning.amendments import build_extraction_context
                amendment_context = build_extraction_context(conversation_id)
            except Exception:
                pass

        # Solo capture — simplified single-pass
        if triage.is_solo:
            result, usage = solo_extract(
                transcript_text, triage,
                amendment_context=amendment_context,
            )
            conn.execute(
                """INSERT INTO extractions (id, conversation_id, pass_number, extraction_json,
                   extraction_version, model_used, input_tokens, output_tokens)
                   VALUES (?, ?, 2, ?, 'v6.0', ?, ?, ?)""",
                (str(uuid.uuid4()), conversation_id,
                 result.model_dump_json(), "opus-4.6",
                 usage["input_tokens"], usage["output_tokens"]),
            )
            extraction_result = result.model_dump()
        else:
            # Pass 2: Sonnet claims extraction
            claims_result, claims_usage = extract_claims(
                transcript_text, triage.episodes,
                amendment_context=amendment_context,
                speaker_map=speaker_map,
                conversation_id=conversation_id,
            )

            conn.execute(
                """INSERT INTO extractions (id, conversation_id, pass_number, extraction_json,
                   extraction_version, model_used, input_tokens, output_tokens)
                   VALUES (?, ?, 2, ?, 'v6.0', ?, ?, ?)""",
                (str(uuid.uuid4()), conversation_id,
                 claims_result.model_dump_json(), "sonnet-4.6",
                 claims_usage["input_tokens"], claims_usage["output_tokens"]),
            )

            # Pass 2.5: Dedup
            pre_dedup_count = len(claims_result.claims)
            claims_result = dedup_claims(claims_result)
            post_dedup_count = len(claims_result.claims)

            # Store claims
            _store_claims(conn, conversation_id, claims_result)

            # Create provisional contacts
            _create_provisional_contacts(conn, conversation_id, claims_result)

            # Pass 2.7: Entity resolution
            try:
                from sauron.extraction.entity_resolver import resolve_claim_entities
                conn.commit()
                entity_stats = resolve_claim_entities(conversation_id)

                # Resolve non-person entities (orgs, legislation, topics)
                try:
                    from sauron.extraction.object_resolver import resolve_object_entities
                    obj_stats = resolve_object_entities(conversation_id)
                    if obj_stats.get("resolved") or obj_stats.get("created"):
                        logger.info(f"[{conversation_id[:8]}] Object resolution: {obj_stats}")
                except Exception:
                    logger.exception("Object resolution failed (non-fatal)")
                logger.info(f"[{conversation_id[:8]}] Entity resolution: {entity_stats}")
            except Exception:
                logger.exception("Entity resolution failed (non-fatal)")

            # Pass 3: Opus synthesis
            existing_beliefs = _load_existing_beliefs(conn, speaker_map)

            synthesis_result, synthesis_usage = synthesize(
                transcript_text, claims_result,
                vocal_summary=vocal_summary,
                triage=triage,
                existing_beliefs=existing_beliefs,
                amendment_context=amendment_context,
                conversation_id=conversation_id,
            )

            conn.execute(
                """INSERT INTO extractions (id, conversation_id, pass_number, extraction_json,
                   extraction_version, model_used, input_tokens, output_tokens)
                   VALUES (?, ?, 3, ?, 'v6.0', ?, ?, ?)""",
                (str(uuid.uuid4()), conversation_id,
                 synthesis_result.model_dump_json(), "opus-4.6",
                 synthesis_usage["input_tokens"], synthesis_usage["output_tokens"]),
            )

            _store_belief_updates(conn, conversation_id, synthesis_result, claims_result)
            _store_graph_edges(conn, conversation_id, synthesis_result)

            # Pass 3.5: Synthesis entity auto-linking
            try:
                from sauron.extraction.synthesis_linker import link_synthesis_entities
                conn.commit()  # Commit current work so linker gets its own connection
                linking_stats = link_synthesis_entities(conversation_id)
                logger.info(
                    f"[{conversation_id[:8]}] Synthesis entity linking: "
                    f"{linking_stats.get('resolved', 0)} resolved, "
                    f"{linking_stats.get('provisional', 0)} provisional"
                )
            except Exception:
                logger.exception("Synthesis entity linking failed (non-fatal)")

            extraction_result = {
                "triage": triage.model_dump(),
                "claims": claims_result.model_dump(),
                "synthesis": synthesis_result.model_dump(),
            }

        # Auto-link meeting intentions
        if speaker_map:
            _link_meeting_intentions(conn, conversation_id, speaker_map, extraction_result)

        return extraction_result

    except Exception:
        logger.exception("Deep extraction failed (non-fatal)")
        return None


# =====================================================
# STORAGE HELPERS
# =====================================================

def _store_episodes(conn, conversation_id: str, triage):
    """Store episode segments from Haiku triage."""
    for i, ep in enumerate(triage.episodes):
        ep_id = f"{conversation_id}_ep_{i+1:03d}"
        conn.execute(
            """INSERT OR IGNORE INTO event_episodes
               (id, conversation_id, title, episode_type, start_time, end_time, summary)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (ep_id, conversation_id, ep.title, ep.episode_type,
             ep.start_time, ep.end_time, ep.summary),
        )


def _store_claims(conn, conversation_id: str, claims_result):
    """Store atomic claims from Sonnet extraction."""
    for claim in claims_result.claims:
        claim_id = f"{conversation_id}_{claim.id}"
        episode_id = None
        if claim.episode_id:
            try:
                ep_num = int(claim.episode_id.split("_")[-1])
                episode_id = f"{conversation_id}_ep_{ep_num:03d}"
            except (ValueError, IndexError):
                episode_id = None

        conn.execute(
            """INSERT OR IGNORE INTO event_claims
               (id, conversation_id, episode_id, claim_type, claim_text,
                subject_entity_id, subject_name, subject_type, target_entity, speaker_id,
                modality, polarity, confidence, stability,
                evidence_quote, evidence_start, evidence_end, review_after,
                importance, evidence_type,
                firmness, has_specific_action, has_deadline, has_condition,
                condition_text, direction, time_horizon)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, ?, ?)""",
            (claim_id, conversation_id, episode_id,
             claim.claim_type, claim.claim_text,
             claim.subject_entity_id, claim.subject_name,
             getattr(claim, 'subject_type', 'person'), claim.target_entity,
             claim.speaker, claim.modality, claim.polarity,
             claim.confidence, claim.stability,
             claim.evidence_quote, claim.evidence_start, claim.evidence_end,
             claim.review_after, claim.importance, claim.evidence_type,
             getattr(claim, 'firmness', None),
             getattr(claim, 'has_specific_action', None),
             getattr(claim, 'has_deadline', None),
             getattr(claim, 'has_condition', None),
             getattr(claim, 'condition_text', None),
             getattr(claim, 'direction', None),
             getattr(claim, 'time_horizon', None)),
        )

        # B3: Store additional entity links from multi-entity claims
        additional = getattr(claim, 'additional_entities', None)
        if additional:
            for ae in additional:
                ae_name = (ae.get("name") or "").strip()
                ae_role = ae.get("role", "target")
                if not ae_name:
                    continue
                # Quick lookup against unified_contacts
                contact = conn.execute(
                    "SELECT id, canonical_name FROM unified_contacts "
                    "WHERE LOWER(TRIM(canonical_name)) = ?",
                    (ae_name.lower(),)
                ).fetchone()
                if not contact:
                    contact = conn.execute(
                        "SELECT id, canonical_name FROM unified_contacts "
                        "WHERE LOWER(aliases) LIKE ?",
                        (f"%{ae_name.lower()}%",)
                    ).fetchone()
                if contact:
                    conn.execute(
                        """INSERT OR IGNORE INTO claim_entities
                           (id, claim_id, entity_id, entity_name, role, confidence,
                            link_source, entity_table)
                           VALUES (?, ?, ?, ?, ?, ?, 'model', 'unified_contacts')""",
                        (str(uuid.uuid4()), claim_id, dict(contact)["id"],
                         dict(contact)["canonical_name"], ae_role, claim.confidence),
                    )
                else:
                    logger.debug(
                        f"Additional entity '{ae_name}' not found in contacts — "
                        f"deferred to entity resolver"
                    )


def _create_provisional_contacts(conn, conversation_id: str, claims_result):
    """Create provisional unified_contacts for unrecognized people mentioned in claims."""
    if not claims_result.new_contacts_mentioned:
        return

    import re as _re

    RELATIONAL_PATTERNS = [
        _re.compile(r"^(my|his|her|their|stephen'?s?)\s+(brother|sister|wife|husband|spouse|partner|"
                    r"mom|mother|dad|father|son|daughter|boss|assistant|colleague|friend|uncle|aunt|"
                    r"cousin|nephew|niece|grandfather|grandmother|grandpa|grandma|fianc[ee]e?|"
                    r"roommate|mentor|intern)$", _re.IGNORECASE),
        _re.compile(r"^(a|the|some)\s+\w+$", _re.IGNORECASE),
    ]

    created = 0
    linked = 0

    for mention in claims_result.new_contacts_mentioned:
        # Handle both string and structured NewContactMention
        if isinstance(mention, str):
            name = mention.strip()
        else:
            # Structured NewContactMention object
            name = (getattr(mention, 'name', '') or '').strip()
        if not name:
            continue

        is_relational = False
        for pattern in RELATIONAL_PATTERNS:
            if pattern.match(name):
                is_relational = True
                break
        if is_relational:
            logger.debug(f"Skipping relational reference: '{name}'")
            continue

        if len(name) < 2:
            continue

        name_lower = name.lower().strip()
        existing = conn.execute(
            """SELECT id, canonical_name FROM unified_contacts
               WHERE LOWER(canonical_name) = ?
                  OR LOWER(aliases) LIKE ?""",
            (name_lower, f"%{name_lower}%"),
        ).fetchone()

        if existing:
            logger.debug(f"Contact already exists for '{name}': {existing['canonical_name']}")
            continue

        contact_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO unified_contacts
               (id, canonical_name, is_confirmed, source_conversation_id, created_at)
               VALUES (?, ?, 0, ?, datetime('now'))""",
            (contact_id, name, conversation_id),
        )
        created += 1
        logger.info(f"Created provisional contact: '{name}' (id={contact_id[:8]})")

        matching_claims = conn.execute(
            """SELECT id, subject_name FROM event_claims
               WHERE conversation_id = ?
                 AND LOWER(subject_name) = ?
                 AND subject_entity_id IS NULL""",
            (conversation_id, name_lower),
        ).fetchall()

        for claim in matching_claims:
            claim_dict = dict(claim)
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO claim_entities
                       (id, claim_id, entity_id, entity_name, role, confidence, link_source)
                       VALUES (?, ?, ?, ?, 'subject', 0.5, 'model')""",
                    (str(uuid.uuid4()), claim_dict["id"], contact_id, name),
                )
                conn.execute(
                    "UPDATE event_claims SET subject_entity_id = ? WHERE id = ? AND subject_entity_id IS NULL",
                    (contact_id, claim_dict["id"]),
                )
                linked += 1
            except Exception:
                pass

    if created:
        logger.info(
            f"Provisional contacts for {conversation_id[:8]}: "
            f"{created} created, {linked} claim links"
        )


def _store_belief_updates(conn, conversation_id, synthesis, claims_result):
    """Store belief updates and evidence links from Opus synthesis."""
    now = datetime.now(timezone.utc).isoformat()

    for bu in synthesis.belief_updates:
        belief_id = str(uuid.uuid4())

        existing = conn.execute(
            "SELECT id, support_count, contradiction_count FROM beliefs WHERE belief_key = ? AND entity_id = ?",
            (bu.belief_key, bu.entity_id),
        ).fetchone()

        if existing:
            if bu.evidence_role == "support":
                _old_status = conn.execute(
                    "SELECT status FROM beliefs WHERE id = ?", (existing["id"],)
                ).fetchone()["status"]
                conn.execute(
                    """UPDATE beliefs SET
                       belief_summary = ?, status = ?, confidence = ?,
                       support_count = support_count + 1,
                       last_confirmed_at = ?, last_changed_at = ?
                       WHERE id = ?""",
                    (bu.belief_summary, bu.status, bu.confidence, now, now, existing["id"]),
                )
                belief_id = existing["id"]
                if _old_status != bu.status:
                    conn.execute(
                        """INSERT INTO belief_transitions
                           (id, belief_id, old_status, new_status, driver, source_conversation_id)
                           VALUES (?, ?, ?, ?, 'new_evidence', ?)""",
                        (str(uuid.uuid4()), existing["id"], _old_status, bu.status, conversation_id),
                    )
            elif bu.evidence_role == "contradiction":
                _old_status = conn.execute(
                    "SELECT status FROM beliefs WHERE id = ?", (existing["id"],)
                ).fetchone()["status"]
                conn.execute(
                    """UPDATE beliefs SET
                       status = 'contested', contradiction_count = contradiction_count + 1,
                       last_changed_at = ?
                       WHERE id = ?""",
                    (now, existing["id"]),
                )
                belief_id = existing["id"]
                if _old_status != 'contested':
                    conn.execute(
                        """INSERT INTO belief_transitions
                           (id, belief_id, old_status, new_status, driver, source_conversation_id)
                           VALUES (?, ?, ?, 'contested', 'new_evidence', ?)""",
                        (str(uuid.uuid4()), existing["id"], _old_status, conversation_id),
                    )
            elif bu.evidence_role in ("refinement", "qualification"):
                _old_status = conn.execute(
                    "SELECT status FROM beliefs WHERE id = ?", (existing["id"],)
                ).fetchone()["status"]
                conn.execute(
                    """UPDATE beliefs SET
                       belief_summary = ?, status = ?, confidence = ?,
                       last_changed_at = ?
                       WHERE id = ?""",
                    (bu.belief_summary, bu.status, bu.confidence, now, existing["id"]),
                )
                belief_id = existing["id"]
                if _old_status != bu.status:
                    conn.execute(
                        """INSERT INTO belief_transitions
                           (id, belief_id, old_status, new_status, driver, source_conversation_id)
                           VALUES (?, ?, ?, ?, 'new_evidence', ?)""",
                        (str(uuid.uuid4()), existing["id"], _old_status, bu.status, conversation_id),
                    )
        else:
            conn.execute(
                """INSERT INTO beliefs
                   (id, entity_type, entity_id, belief_key, belief_summary,
                    status, confidence, support_count, contradiction_count,
                    first_observed_at, last_confirmed_at, last_changed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (belief_id, bu.entity_type, bu.entity_id, bu.belief_key,
                 bu.belief_summary, bu.status, bu.confidence,
                 1 if bu.evidence_role == "support" else 0,
                 1 if bu.evidence_role == "contradiction" else 0,
                 now, now, now),
            )
            conn.execute(
                """INSERT INTO belief_transitions
                   (id, belief_id, old_status, new_status, driver, source_conversation_id)
                   VALUES (?, ?, NULL, ?, 'new_evidence', ?)""",
                (str(uuid.uuid4()), belief_id, bu.status, conversation_id),
            )

        for claim_ref in bu.supporting_claim_ids:
            claim_db_id = f"{conversation_id}_{claim_ref}"
            conn.execute(
                """INSERT OR IGNORE INTO belief_evidence
                   (id, belief_id, claim_id, weight, evidence_role)
                   VALUES (?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), belief_id, claim_db_id,
                 bu.confidence, bu.evidence_role),
            )

        # C8: Resolve entity_id for beliefs
        if bu.entity_type and bu.entity_type != 'person' and bu.entity_name and not bu.entity_id:
            entity_row = conn.execute(
                "SELECT id FROM unified_entities WHERE LOWER(canonical_name) = ?",
                (bu.entity_name.strip().lower(),),
            ).fetchone()
            if entity_row:
                conn.execute(
                    "UPDATE beliefs SET entity_id = ? WHERE id = ?",
                    (entity_row["id"], belief_id),
                )
        elif bu.entity_type == 'person' and bu.entity_name and not bu.entity_id:
            contact_row = conn.execute(
                "SELECT id FROM unified_contacts WHERE LOWER(canonical_name) = ?",
                (bu.entity_name.strip().lower(),),
            ).fetchone()
            if contact_row:
                conn.execute(
                    "UPDATE beliefs SET entity_id = ? WHERE id = ?",
                    (contact_row["id"], belief_id),
                )


def _resolve_graph_entity(conn, name: str, entity_type: str):
    """Resolve graph edge entity name to (id, table) tuple."""
    if not name:
        return None, None
    name_lower = name.strip().lower()
    if entity_type == "person":
        row = conn.execute(
            "SELECT id FROM unified_contacts WHERE LOWER(canonical_name) = ?",
            (name_lower,),
        ).fetchone()
        if not row:
            row = conn.execute(
                "SELECT id FROM unified_contacts WHERE LOWER(aliases) LIKE ?",
                (f"%{name_lower}%",),
            ).fetchone()
        return (row["id"], "unified_contacts") if row else (None, None)
    else:
        row = conn.execute(
            "SELECT id FROM unified_entities WHERE LOWER(canonical_name) = ?",
            (name_lower,),
        ).fetchone()
        if not row:
            row = conn.execute(
                "SELECT id FROM unified_entities WHERE LOWER(aliases) LIKE ?",
                (f"%{name_lower}%",),
            ).fetchone()
        return (row["id"], "unified_entities") if row else (None, None)


def _store_graph_edges(conn, conversation_id, synthesis):
    """Store graph edges from Opus synthesis.

    Clears any existing edges for this conversation first to prevent
    accumulation across reprocessing runs.
    """
    deleted = conn.execute(
        "DELETE FROM graph_edges WHERE source_conversation_id = ?",
        (conversation_id,),
    ).rowcount
    if deleted:
        logger.info(f"[{conversation_id[:8]}] Cleared {deleted} old graph edges before storing new ones")

    now = datetime.now(timezone.utc).isoformat()
    for edge in synthesis.graph_edges:
        edge_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO graph_edges
               (id, from_entity, from_type, to_entity, to_type,
                edge_type, strength, source_conversation_id, observed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (edge_id, edge.from_entity, edge.from_type,
             edge.to_entity, edge.to_type, edge.edge_type,
             edge.strength, conversation_id, now),
        )

        # Resolve entity IDs for this edge
        from_id, from_table = _resolve_graph_entity(conn, edge.from_entity, edge.from_type)
        to_id, to_table = _resolve_graph_entity(conn, edge.to_entity, edge.to_type)
        if from_id or to_id:
            conn.execute(
                """UPDATE graph_edges
                   SET from_entity_id=?, from_entity_table=?,
                       to_entity_id=?, to_entity_table=?
                   WHERE id=?""",
                (from_id, from_table, to_id, to_table, edge_id),
            )


def _load_existing_beliefs(conn, speaker_map: dict | None) -> list[dict]:
    """Load existing beliefs about people in this conversation."""
    if not speaker_map:
        return []

    beliefs = []
    for label, contact_id in speaker_map.items():
        if not contact_id:
            continue
        rows = conn.execute(
            """SELECT belief_key, belief_summary, status, confidence
               FROM beliefs
               WHERE entity_id = ? AND status NOT IN ('stale', 'superseded')
               ORDER BY last_confirmed_at DESC LIMIT 20""",
            (contact_id,),
        ).fetchall()
        if rows:
            name_row = conn.execute(
                "SELECT canonical_name FROM unified_contacts WHERE id = ?",
                (contact_id,),
            ).fetchone()
            name = name_row["canonical_name"] if name_row else contact_id

            for r in rows:
                beliefs.append({
                    "person": name,
                    "belief_key": r["belief_key"],
                    "belief_summary": r["belief_summary"],
                    "status": r["status"],
                    "confidence": r["confidence"],
                })

    return beliefs


def _link_meeting_intentions(conn, conversation_id, speaker_map, extraction_result):
    """Auto-link meeting intentions when target contact participates."""
    try:
        from sauron.jobs.intentions import (
            find_unlinked_intention,
            link_intention_to_conversation,
            assess_goals,
        )
        for label, contact_id in speaker_map.items():
            if contact_id:
                intention_id = find_unlinked_intention(contact_id)
                if intention_id:
                    link_intention_to_conversation(intention_id, conversation_id)
                    if extraction_result:
                        assess_goals(intention_id, extraction_result)
                    break
    except Exception:
        logger.exception("Intention linking failed (non-fatal)")


# DEAD CODE: _run_routing() is never called. Routing fires only via
# mark_reviewed() in review_actions.py -> route_extraction() in router.py.
# Retained temporarily for reference; safe to delete in a future cleanup.
def _run_routing(conversation_id: str, extraction: dict):
    """Route extraction results to downstream apps."""
    try:
        from sauron.routing.router import route_extraction
        route_extraction(conversation_id, extraction)
    except Exception:
        logger.exception("Routing failed (non-fatal)")


def _run_embedding(conversation_id: str):
    """Run semantic embedding for all conversation artefacts."""
    try:
        from sauron.embeddings.embedder import embed_conversation
        embed_conversation(conversation_id)
    except Exception:
        logger.exception("Embedding failed (non-fatal)")



if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--backfill-titles":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
        backfill_titles()
    else:
        print("Usage: python -m sauron.pipeline.processor --backfill-titles")
