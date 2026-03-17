"""Pipeline API — manual ingestion, processing controls, and status.

Endpoints:
  POST /pipeline/ingest           — ingest existing files from inbox dirs
  POST /pipeline/process/{id}     — manually trigger processing for a conversation
  POST /pipeline/process-pending  — process all pending conversations
  GET  /pipeline/status           — pipeline status summary
"""

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File, Form

from sauron.config import (
    INBOX_PI, INBOX_PLAUD, INBOX_IPHONE_DIR, INBOX_EMAIL_DIR,
    SUPPORTED_FORMATS,
)
from sauron.db.connection import get_connection
from sauron.pipeline.processor import process_conversation, process_pending

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

INBOX_SOURCES = {
    "pi": INBOX_PI,
    "plaud": INBOX_PLAUD,
    "iphone": INBOX_IPHONE_DIR,
    "email": INBOX_EMAIL_DIR,
}


@router.post("/ingest")
async def ingest_existing_files(source: str = None):
    """Scan inbox directories for unregistered audio files and register them.

    Args:
        source: Optional filter — 'pi', 'plaud', 'iphone', 'email'. If None, scan all.
    """
    if source and source not in INBOX_SOURCES:
        return {"error": f"Unknown source: {source}. Use: {list(INBOX_SOURCES.keys())}"}

    sources = {source: INBOX_SOURCES[source]} if source else INBOX_SOURCES
    registered = []
    skipped = 0

    conn = get_connection()
    try:
        # Get existing audio paths to avoid duplicates
        existing_paths = {
            row["original_path"]
            for row in conn.execute("SELECT original_path FROM audio_files").fetchall()
        }

        for src_name, inbox_dir in sources.items():
            if not inbox_dir.exists():
                continue

            for audio_file in sorted(inbox_dir.iterdir()):
                if audio_file.suffix.lower() not in SUPPORTED_FORMATS:
                    continue
                if str(audio_file) in existing_paths:
                    skipped += 1
                    continue

                # Register this file
                conversation_id = str(uuid.uuid4())
                audio_id = str(uuid.uuid4())
                now = datetime.now(timezone.utc).isoformat()

                # Load sidecar metadata
                metadata = _load_sidecar(audio_file)
                captured_at = metadata.get("captured_at", now)
                duration = metadata.get("duration_seconds")

                file_size = audio_file.stat().st_size

                conn.execute(
                    """INSERT INTO conversations (id, source, captured_at, duration_seconds,
                       processing_status, audio_file_id, created_at)
                       VALUES (?, ?, ?, ?, 'pending', ?, ?)""",
                    (conversation_id, src_name, captured_at, duration, audio_id, now),
                )

                conn.execute(
                    """INSERT INTO audio_files (id, conversation_id, original_path, current_path,
                       file_size_bytes, format, duration_seconds, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (audio_id, conversation_id, str(audio_file), str(audio_file),
                     file_size, audio_file.suffix.lstrip("."), duration, now),
                )

                registered.append({
                    "conversation_id": conversation_id,
                    "file": audio_file.name,
                    "source": src_name,
                    "size_bytes": file_size,
                })

        conn.commit()
    finally:
        conn.close()

    return {
        "registered": len(registered),
        "skipped": skipped,
        "files": registered,
    }




@router.post("/upload")
async def upload_recording(
    file: UploadFile = File(...),
    source: str = Form("iphone"),
    note: str = Form(None),
):
    """Upload an audio recording to the inbox and trigger processing.

    Args:
        file: Audio file (m4a, mp3, wav, flac, ogg, opus, webm)
        source: Source tag — 'iphone', 'plaud', or 'other'
        note: Optional title/note for the recording
    """
    # Validate source
    allowed_sources = {"iphone", "plaud", "other"}
    if source not in allowed_sources:
        raise HTTPException(400, f"Invalid source '{source}'. Use: {sorted(allowed_sources)}")

    # Validate file extension
    import os
    ext = os.path.splitext(file.filename or "")[1].lower()
    allowed_ext = {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus", ".webm"}
    if ext not in allowed_ext:
        raise HTTPException(400, f"Unsupported format '{ext}'. Allowed: {sorted(allowed_ext)}")

    # Validate file size (200MB max)
    max_size = 200 * 1024 * 1024
    contents = await file.read()
    if len(contents) > max_size:
        raise HTTPException(413, f"File too large ({len(contents) / 1024 / 1024:.1f}MB). Max: 200MB")

    # Determine inbox directory
    source_dirs = {
        "iphone": INBOX_SOURCES.get("iphone"),
        "plaud": INBOX_SOURCES.get("plaud"),
        "other": INBOX_SOURCES.get("iphone"),  # fallback to iphone dir
    }
    inbox_dir = source_dirs.get(source, INBOX_SOURCES.get("iphone"))
    inbox_dir.mkdir(parents=True, exist_ok=True)

    # Write file — use original filename, avoid collisions
    safe_name = file.filename.replace("/", "_").replace("\\", "_")
    dest = inbox_dir / safe_name
    if dest.exists():
        stem = dest.stem
        suffix = dest.suffix
        counter = 1
        while dest.exists():
            dest = inbox_dir / f"{stem}_{counter}{suffix}"
            counter += 1

    dest.write_bytes(contents)
    logger.info("Uploaded %s (%d bytes) to %s", safe_name, len(contents), dest)

    # Register in DB (same as watcher._register_file)
    conversation_id = str(uuid.uuid4())
    audio_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    conn = get_connection()
    try:
        # conversations first (audio_files.conversation_id FK references conversations.id)
        conn.execute(
            """INSERT INTO conversations (id, source, captured_at, duration_seconds,
               processing_status, audio_file_id, manual_note, created_at)
               VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)""",
            (conversation_id, source, now, None, audio_id, note, now),
        )

        conn.execute(
            """INSERT INTO audio_files (id, conversation_id, original_path, current_path,
               file_size_bytes, format, duration_seconds, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (audio_id, conversation_id, str(dest), str(dest),
             len(contents), ext.lstrip("."), None, now),
        )

        conn.commit()
    except Exception as e:
        conn.rollback()
        # Clean up the written file
        if dest.exists():
            dest.unlink()
        logger.exception("Upload DB registration failed")
        raise HTTPException(500, f"Failed to register upload: {e}")
    finally:
        conn.close()

    # Trigger processing in background thread (same as watcher)
    from sauron.pipeline.processor import process_through_speaker_id
    import threading
    t = threading.Thread(
        target=process_through_speaker_id,
        args=(conversation_id,),
        daemon=True,
    )
    t.start()

    return {
        "status": "uploaded",
        "conversation_id": conversation_id,
        "filename": safe_name,
        "source": source,
        "size_bytes": len(contents),
        "processing": "started",
    }

@router.post("/process/{conversation_id}")
async def process_single(conversation_id: str, background_tasks: BackgroundTasks):
    """Trigger processing for a specific conversation."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, processing_status FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return {"error": "Conversation not found"}

    background_tasks.add_task(process_conversation, conversation_id)
    return {
        "status": "processing_started",
        "conversation_id": conversation_id,
        "previous_status": row["processing_status"],
    }


@router.post("/process-pending")
async def process_all_pending(background_tasks: BackgroundTasks):
    """Process all pending conversations in background."""
    conn = get_connection()
    try:
        count = conn.execute(
            "SELECT count(*) as n FROM conversations WHERE processing_status = 'pending'"
        ).fetchone()["n"]
    finally:
        conn.close()

    if count == 0:
        return {"status": "no_pending_conversations"}

    background_tasks.add_task(process_pending)
    return {"status": "processing_started", "pending_count": count}


@router.get("/status")
async def pipeline_status():
    """Get pipeline processing status summary."""
    conn = get_connection()
    try:
        status_counts = {}
        for row in conn.execute(
            "SELECT processing_status, count(*) as n FROM conversations GROUP BY processing_status"
        ).fetchall():
            status_counts[row["processing_status"]] = row["n"]

        total_claims = conn.execute("SELECT count(*) as n FROM event_claims").fetchone()["n"]
        total_episodes = conn.execute("SELECT count(*) as n FROM event_episodes").fetchone()["n"]
        total_beliefs = conn.execute("SELECT count(*) as n FROM beliefs").fetchone()["n"]
        total_embeddings = conn.execute("SELECT count(*) as n FROM embeddings").fetchone()["n"]

        return {
            "conversations": status_counts,
            "total_claims": total_claims,
            "total_episodes": total_episodes,
            "total_beliefs": total_beliefs,
            "total_embeddings": total_embeddings,
        }
    finally:
        conn.close()


def _load_sidecar(audio_path: Path) -> dict:
    """Load JSON sidecar metadata from next to the audio file."""
    sidecar = audio_path.with_suffix(".json")
    if sidecar.exists():
        try:
            return json.loads(sidecar.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


# =====================================================
# PIPELINE REDESIGN ENDPOINTS
# =====================================================

@router.post("/confirm-speakers/{conversation_id}")
def confirm_speakers(conversation_id: str):
    """Confirm speaker assignments and trigger extraction pipeline.

    Called after human speaker review. Validates status is awaiting_speaker_review,
    then runs triage + extraction.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT processing_status FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if row["processing_status"] != "awaiting_speaker_review":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot confirm speakers: status is {row['processing_status']}, expected awaiting_speaker_review",
            )
    finally:
        conn.close()

    # Run extraction pipeline (triage + Sonnet + Opus)
    from sauron.pipeline.processor import process_extraction
    import threading
    def _run():
        try:
            process_extraction(conversation_id)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception(f"Extraction failed for {conversation_id}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    return {"status": "ok", "message": "Speaker review confirmed, extraction started", "conversation_id": conversation_id}


@router.post("/promote-triage/{conversation_id}")
def promote_triage(conversation_id: str):
    """Promote a triage-rejected conversation to full extraction.

    Called when user decides a low-value conversation should be fully extracted.
    Skips triage (already ran), goes straight to Sonnet + Opus.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT processing_status FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if row["processing_status"] != "triage_rejected":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot promote: status is {row['processing_status']}, expected triage_rejected",
            )
    finally:
        conn.close()

    from sauron.pipeline.processor import process_extraction_skip_triage
    import threading
    def _run():
        try:
            process_extraction_skip_triage(conversation_id)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception(f"Promoted extraction failed for {conversation_id}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    return {"status": "ok", "message": "Triage promoted, extraction started", "conversation_id": conversation_id}


@router.post("/archive-triage/{conversation_id}")
def archive_triage(conversation_id: str):
    """Archive a triage-rejected conversation as completed (low value, accepted)."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT processing_status FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if row["processing_status"] != "triage_rejected":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot archive: status is {row['processing_status']}, expected triage_rejected",
            )

        conn.execute(
            """UPDATE conversations
               SET processing_status = 'completed',
                   reviewed_at = datetime('now')
               WHERE id = ?""",
            (conversation_id,),
        )
        conn.commit()
        return {"status": "ok", "message": "Archived as low value", "conversation_id": conversation_id}
    finally:
        conn.close()



# =====================================================
# ROUTING STATUS + RETRY ENDPOINTS (Phase C)
# =====================================================

@router.get("/routing-status")
async def routing_status():
    """Get routing log status summary.

    Returns counts of pending_entity, failed, and sent routes,
    plus conversation-level counts.
    """
    from sauron.routing.routing_log import get_routing_status
    from sauron.db.connection import get_connection
    conn = get_connection()
    try:
        status = get_routing_status(conn)
        return status
    finally:
        conn.close()


@router.post("/retry-failed-routes")
async def retry_failed_routes(background_tasks: BackgroundTasks):
    """Retry all failed routes that haven't exceeded max attempts.

    Re-sends the stored extraction payload through route_to_networking_app().
    Upsert on sourceSystem/sourceId makes re-sending safe.
    """
    from sauron.routing.routing_log import get_failed_routes
    from sauron.db.connection import get_connection
    import json

    conn = get_connection()
    try:
        failed = get_failed_routes(conn=conn)
    finally:
        conn.close()

    if not failed:
        return {"status": "no_failed_routes", "retried": 0}

    # Deduplicate by conversation_id — all-or-nothing means one entry per conversation
    seen_conversations = set()
    to_retry = []
    for route in failed:
        cid = route["conversation_id"]
        if cid not in seen_conversations:
            seen_conversations.add(cid)
            to_retry.append(route)

    def _retry_all():
        from sauron.routing.networking import route_to_networking_app
        from sauron.db.connection import get_connection as gc
        from datetime import datetime

        results = {"success": 0, "failed": 0}
        for route in to_retry:
            conn = gc()
            try:
                payload = json.loads(route["payload_json"]) if route["payload_json"] else {}
                cid = route["conversation_id"]

                success = route_to_networking_app(cid, payload)

                now = datetime.now(timezone.utc).isoformat()
                if success:
                    # Mark original failed entry as retried_success
                    conn.execute(
                        """UPDATE routing_log
                           SET status = 'sent',
                               attempts = attempts + 1,
                               last_attempt_at = ?
                           WHERE id = ?""",
                        (now, route["id"]),
                    )
                    # Set routed_at on the conversation
                    conn.execute(
                        "UPDATE conversations SET routed_at = datetime('now') WHERE id = ?",
                        (cid,),
                    )
                    conn.commit()
                    results["success"] += 1
                else:
                    # route_to_networking_app already logged a new failure;
                    # update attempt count on original entry
                    conn.execute(
                        """UPDATE routing_log
                           SET attempts = attempts + 1,
                               last_attempt_at = ?
                           WHERE id = ?""",
                        (now, route["id"]),
                    )
                    conn.commit()
                    results["failed"] += 1
            except Exception as e:
                import logging
                logging.getLogger(__name__).exception(
                    f"Retry failed for conversation {route['conversation_id'][:8]}"
                )
                results["failed"] += 1
            finally:
                conn.close()

        import logging
        logging.getLogger(__name__).info(
            f"Retry complete: {results['success']} succeeded, {results['failed']} failed"
        )

    background_tasks.add_task(_retry_all)

    return {
        "status": "retry_started",
        "conversations_to_retry": len(to_retry),
        "total_failed_entries": len(failed),
    }
