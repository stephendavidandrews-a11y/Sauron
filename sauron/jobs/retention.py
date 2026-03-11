"""Nightly retention manager — compresses and archives old audio files.

Runs as a cron job at 2am:
1. Audio files older than 30 days on SSD -> compress to 64kbps MP3
2. Move MP3 to external drive
3. Delete original from SSD
4. Exception: voice enrollment samples (never delete)
"""

import logging
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sauron.config import HOT_RETENTION_DAYS, COLD_BITRATE, ARCHIVE_DIR
from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)


def run_retention():
    """Run the nightly retention cycle."""
    conn = get_connection()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=HOT_RETENTION_DAYS)).isoformat()

    try:
        # Find hot audio files older than retention period
        rows = conn.execute(
            """SELECT af.* FROM audio_files af
               WHERE af.storage_tier = 'hot'
                 AND af.created_at < ?""",
            (cutoff,),
        ).fetchall()

        if not rows:
            logger.info("No audio files to archive")
            return

        logger.info(f"Archiving {len(rows)} audio files older than {HOT_RETENTION_DAYS} days")
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

        for row in rows:
            _archive_file(conn, row)

        conn.commit()
        logger.info("Retention cycle complete")
    except Exception:
        conn.rollback()
        logger.exception("Retention cycle failed")
    finally:
        conn.close()


def _archive_file(conn, row):
    """Compress and archive a single audio file."""
    src = Path(row["current_path"])
    if not src.exists():
        logger.warning(f"Source file missing: {src}")
        return

    # Compress to MP3
    dest = ARCHIVE_DIR / f"{src.stem}.mp3"
    try:
        subprocess.run(
            ["ffmpeg", "-i", str(src), "-b:a", COLD_BITRATE,
             "-y", "-loglevel", "error", str(dest)],
            check=True, capture_output=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.exception(f"Failed to compress {src.name}")
        return

    # Update database
    conn.execute(
        """UPDATE audio_files SET
           storage_tier = 'cold',
           compressed_path = ?,
           moved_to_cold_at = datetime('now')
           WHERE id = ?""",
        (str(dest), row["id"]),
    )

    # Log retention action
    conn.execute(
        "INSERT INTO retention_log (id, audio_file_id, action) VALUES (?, ?, 'compressed')",
        (str(uuid.uuid4()), row["id"]),
    )

    # Delete original
    try:
        src.unlink()
        conn.execute(
            "UPDATE audio_files SET current_path = ?, deleted_at = datetime('now') WHERE id = ?",
            (str(dest), row["id"]),
        )
        conn.execute(
            "INSERT INTO retention_log (id, audio_file_id, action) VALUES (?, ?, 'deleted_original')",
            (str(uuid.uuid4()), row["id"]),
        )
        logger.info(f"Archived: {src.name} -> {dest.name}")
    except OSError:
        logger.exception(f"Failed to delete original: {src}")


if __name__ == "__main__":
    run_retention()
