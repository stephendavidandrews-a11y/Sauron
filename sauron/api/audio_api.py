"""Audio serving API endpoints.

Provides endpoints to serve audio files and clips for the speaker review
workbench and transcript playback.
"""

import logging
import shutil
import subprocess
import hashlib
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, FileResponse

from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/audio", tags=["audio"])

# Clip cache directory
CLIP_CACHE_DIR = Path(tempfile.gettempdir()) / "sauron_clips"
CLIP_CACHE_DIR.mkdir(exist_ok=True)


def _find_ffmpeg() -> str:
    """Find ffmpeg binary, checking Homebrew fallback."""
    path = shutil.which("ffmpeg")
    if path:
        return path
    brew_path = "/opt/homebrew/bin/ffmpeg"
    if Path(brew_path).exists():
        return brew_path
    raise FileNotFoundError(
        "ffmpeg not found in PATH or /opt/homebrew/bin/. "
        "Install with: brew install ffmpeg"
    )


def _get_audio_path(conversation_id: str) -> Path:
    """Look up the audio file path for a conversation."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT current_path FROM audio_files WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, f"No audio file for conversation {conversation_id}")
        path = Path(row["current_path"])
        if not path.exists():
            raise HTTPException(404, f"Audio file not found on disk: {path}")
        return path
    finally:
        conn.close()


def _detect_media_type(path: Path) -> str:
    """Detect media type from file extension."""
    ext = path.suffix.lower()
    return {
        ".wav": "audio/wav",
        ".flac": "audio/flac",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".opus": "audio/opus",
    }.get(ext, "audio/octet-stream")


@router.get("/{conversation_id}")
def serve_full_audio(conversation_id: str):
    """Serve the full audio file for a conversation."""
    path = _get_audio_path(conversation_id)
    media_type = _detect_media_type(path)
    return FileResponse(
        path=str(path),
        media_type=media_type,
        filename=path.name,
    )


@router.get("/{conversation_id}/clip")
def serve_audio_clip(conversation_id: str, start: float, end: float):
    """Serve an audio clip extracted between start and end seconds.

    Uses ffmpeg to extract the segment and returns WAV audio.
    Clips are cached in /tmp/sauron_clips/ for repeat requests.
    """
    if start < 0 or end <= start:
        raise HTTPException(400, "Invalid time range: start must be >= 0 and end > start")
    if end - start > 300:
        raise HTTPException(400, "Clip too long (max 5 minutes)")

    audio_path = _get_audio_path(conversation_id)

    # Check cache
    cache_key = hashlib.md5(
        f"{conversation_id}:{start}:{end}".encode()
    ).hexdigest()
    cache_path = CLIP_CACHE_DIR / f"{cache_key}.wav"

    if cache_path.exists():
        return FileResponse(
            path=str(cache_path),
            media_type="audio/wav",
            filename=f"clip_{start:.1f}_{end:.1f}.wav",
        )

    # Extract clip with ffmpeg
    try:
        ffmpeg = _find_ffmpeg()
        cmd = [
            ffmpeg,
            "-i", str(audio_path),
            "-ss", str(start),
            "-to", str(end),
            "-ac", "1",
            "-ar", "16000",
            "-f", "wav",
            "-y",
            str(cache_path),
        ]
        result = subprocess.run(
            cmd, capture_output=True, timeout=30,
        )
        if result.returncode != 0:
            logger.error(f"ffmpeg failed: {result.stderr.decode()[:500]}")
            raise HTTPException(500, "Failed to extract audio clip")

        return FileResponse(
            path=str(cache_path),
            media_type="audio/wav",
            filename=f"clip_{start:.1f}_{end:.1f}.wav",
        )
    except FileNotFoundError:
        raise HTTPException(500, "ffmpeg not available on this system")
    except subprocess.TimeoutExpired:
        raise HTTPException(500, "Audio extraction timed out")


@router.get("/{conversation_id}/speaker-sample/{speaker_label}")
def serve_speaker_sample(conversation_id: str, speaker_label: str):
    """Serve a representative audio clip for a speaker.

    Finds the longest transcript segment for this speaker (between 3-15 seconds)
    and returns that audio clip.
    """
    conn = get_connection()
    try:
        # Find the best representative segment (longest between 3-15 seconds)
        segments = conn.execute(
            """SELECT start_time, end_time,
                      (end_time - start_time) as duration
               FROM transcripts
               WHERE conversation_id = ? AND speaker_label = ?
                 AND (end_time - start_time) >= 3.0
               ORDER BY
                 CASE WHEN (end_time - start_time) BETWEEN 3.0 AND 15.0 THEN 0 ELSE 1 END,
                 (end_time - start_time) DESC
               LIMIT 1""",
            (conversation_id, speaker_label),
        ).fetchone()

        if not segments:
            # Fall back to any segment > 1 second
            segments = conn.execute(
                """SELECT start_time, end_time
                   FROM transcripts
                   WHERE conversation_id = ? AND speaker_label = ?
                     AND (end_time - start_time) >= 1.0
                   ORDER BY (end_time - start_time) DESC
                   LIMIT 1""",
                (conversation_id, speaker_label),
            ).fetchone()

        if not segments:
            raise HTTPException(404, f"No suitable audio segment for speaker {speaker_label}")

        start = float(segments["start_time"])
        end = float(segments["end_time"])
        # Cap at 15 seconds
        if end - start > 15.0:
            end = start + 15.0

    finally:
        conn.close()

    # Delegate to the clip endpoint logic
    return serve_audio_clip(conversation_id, start, end)
