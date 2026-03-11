"""File watcher for Sauron inbox directories.

Monitors inbox/pi/, inbox/plaud/, inbox/iphone/, and inbox/email/
for new audio files. Creates processing jobs in sauron.db when files appear.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from watchdog.events import FileSystemEventHandler, FileCreatedEvent
from watchdog.observers import Observer

from sauron.config import (
    INBOX_PI, INBOX_PLAUD, INBOX_IPHONE_DIR, INBOX_EMAIL_DIR,
    INBOX_METADATA, SUPPORTED_FORMATS,
)
from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)


class AudioInboxHandler(FileSystemEventHandler):
    """Handles new audio files appearing in inbox directories."""

    def __init__(self, source: str, on_new_file=None):
        self.source = source  # 'pi', 'plaud', 'iphone', or 'email'
        self.on_new_file = on_new_file

    def on_created(self, event: FileCreatedEvent):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() not in SUPPORTED_FORMATS:
            return
        logger.info(f"New {self.source} audio file: {path.name}")
        self._register_file(path)

    def _register_file(self, path: Path):
        """Register the audio file in sauron.db and queue for processing."""
        conn = get_connection()
        try:
            # Guard against duplicate registration (upload endpoint may have already registered)
            existing = conn.execute(
                "SELECT id FROM audio_files WHERE original_path = ?", (str(path),)
            ).fetchone()
            if existing:
                logger.info(f"Skipping {path.name} — already registered")
                return

            conversation_id = str(uuid.uuid4())
            audio_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()

            # Check for metadata sidecar
            metadata = self._load_metadata(path)
            captured_at = metadata.get("captured_at", now)
            manual_note = metadata.get("manual_note")
            duration = metadata.get("duration_seconds")

            file_size = path.stat().st_size if path.exists() else None

            conn.execute(
                """INSERT INTO audio_files (id, conversation_id, original_path, current_path,
                   file_size_bytes, format, duration_seconds, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (audio_id, conversation_id, str(path), str(path),
                 file_size, path.suffix.lstrip("."), duration, now),
            )

            conn.execute(
                """INSERT INTO conversations (id, source, captured_at, duration_seconds,
                   processing_status, audio_file_id, manual_note, created_at)
                   VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)""",
                (conversation_id, self.source, captured_at, duration,
                 audio_id, manual_note, now),
            )

            conn.commit()
            logger.info(f"Registered conversation {conversation_id} from {path.name}")

            if self.on_new_file:
                self.on_new_file(conversation_id, path)

        except Exception:
            conn.rollback()
            logger.exception(f"Failed to register {path.name}")
        finally:
            conn.close()

    def _load_metadata(self, audio_path: Path) -> dict:
        """Load JSON sidecar metadata if it exists."""
        # Check for sidecar next to audio file first (Pi sends them together)
        sidecar = audio_path.with_suffix('.json')
        if not sidecar.exists():
            sidecar = INBOX_METADATA / f"{audio_path.stem}.json"
        if sidecar.exists():
            try:
                return json.loads(sidecar.read_text())
            except (json.JSONDecodeError, OSError):
                logger.warning(f"Failed to parse metadata sidecar: {sidecar}")
        return {}


# All inbox directories and their source labels
INBOX_SOURCES = [
    (INBOX_PI, "pi"),
    (INBOX_PLAUD, "plaud"),
    (INBOX_IPHONE_DIR, "iphone"),
    (INBOX_EMAIL_DIR, "email"),
]


class InboxWatcher:
    """Watches all inbox directories for new audio files."""

    def __init__(self, on_new_file=None):
        self.observer = Observer()
        self.on_new_file = on_new_file

    def start(self):
        """Start watching inbox directories."""
        for inbox_dir, source in INBOX_SOURCES:
            inbox_dir.mkdir(parents=True, exist_ok=True)
            handler = AudioInboxHandler(source=source, on_new_file=self.on_new_file)
            self.observer.schedule(handler, str(inbox_dir), recursive=False)
            logger.info(f"Watching {inbox_dir} for {source} audio files")

        self.observer.start()

    def stop(self):
        """Stop the file watcher."""
        self.observer.stop()
        self.observer.join()
