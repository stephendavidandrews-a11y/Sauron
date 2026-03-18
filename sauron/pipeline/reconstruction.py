"""DB reconstruction helpers — rebuild pipeline artefacts from stored data.

Functions:
  reconstruct_from_db — rebuild AlignedTranscript + speaker_map
  load_stored_embeddings — load voice embeddings as numpy arrays
  get_vocal_summary — reconstruct vocal summary string
  load_existing_beliefs — load participant beliefs for Opus context
  format_transcript — format transcript for Claude input
"""
import json
import logging

from sauron.db.connection import get_connection
from sauron.pipeline.aligner import AlignedTranscript, AlignedSegment, AlignedWord

logger = logging.getLogger(__name__)


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

