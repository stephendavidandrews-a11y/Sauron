"""Pipeline orchestrator — processes audio files end-to-end.

Coordinates: transcription -> diarization -> alignment -> vocal analysis
-> speaker ID -> (auto-advance gate) -> three-pass Claude extraction
-> storage -> routing -> embedding.

Split in Phase 7:
  processor.py          — public API + early pipeline stages
  extraction_runner.py  — extraction orchestration (passes 1-3)
  storage.py            — DB write helpers for extraction results
  reconstruction.py     — DB read helpers + transcript formatting
  calendar_integration.py — Google Calendar attendee resolution
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
from sauron.pipeline.reconstruction import (
    _reconstruct_from_db, _get_vocal_summary, _load_stored_embeddings,
    _format_transcript,
)
from sauron.pipeline.extraction_runner import (
    _run_full_extraction_pipeline, _run_deep_extraction_only,
    _try_extraction_comparison,
)
from sauron.pipeline.calendar_integration import _get_calendar_attendees
from sauron.pipeline.helpers import _update_status, _run_embedding

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

        # Stage 1: Transcription (use prepared audio for consistent quality)
        logger.info(f"[{conversation_id[:8]}] Stage 1: Transcribing...")
        transcription = transcribe(prepared_path)

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
                    # generate_title_from_transcript merged into generate_title
                    _transcript_segs = conn.execute(
                        "SELECT GROUP_CONCAT(text, ' ') as full_text FROM transcripts WHERE conversation_id = ?",
                        (conversation_id,),
                    ).fetchone()
                    if _transcript_segs and _transcript_segs["full_text"]:
                        _title = generate_title(transcript_text=_transcript_segs["full_text"])
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
    from sauron.extraction.triage import generate_title
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
                title = generate_title(triage_result=triage_data)
            elif row["transcript_text"]:
                title = generate_title(transcript_text=row["transcript_text"])
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
# PIPELINE STAGE HELPERS
# =====================================================

def _single_speaker_fallback(duration: float):
    """Create a minimal diarization result with a single speaker."""
    from sauron.pipeline.diarizer import DiarizationResult, SpeakerSegment
    return DiarizationResult(
        segments=[SpeakerSegment(speaker="SPEAKER_00", start=0.0, end=duration)],
        embeddings={},
        num_speakers=1,
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


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--backfill-titles":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
        backfill_titles()
    else:
        print("Usage: python -m sauron.pipeline.processor --backfill-titles")
