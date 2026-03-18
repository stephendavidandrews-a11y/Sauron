"""Sauron configuration — paths, ports, and settings.

Every value can be overridden via environment variable.  Defaults match
the production Mac Mini layout so behaviour is unchanged when no env
vars are set.
"""

import os
from pathlib import Path

_env = os.environ.get


# ── Paths ──
BASE_DIR = Path(_env("SAURON_BASE_DIR", "/Users/stephen/Documents/Website/Sauron"))
DATA_DIR = Path(_env("SAURON_DATA_DIR", str(BASE_DIR / "data")))
INBOX_DIR = Path(_env("SAURON_INBOX_DIR", str(BASE_DIR / "inbox")))
INBOX_PI = INBOX_DIR / "pi"
INBOX_PLAUD = INBOX_DIR / "plaud"
INBOX_IPHONE_DIR = INBOX_DIR / "iphone"
INBOX_EMAIL_DIR = INBOX_DIR / "email"
INBOX_METADATA = INBOX_DIR / "metadata"
LOGS_DIR = Path(_env("SAURON_LOGS_DIR", str(BASE_DIR / "logs")))
MODELS_DIR = Path(_env("SAURON_MODELS_DIR", str(BASE_DIR / "models")))

DB_PATH = Path(_env("SAURON_DB_PATH", str(DATA_DIR / "sauron.db")))

# External drive for cold storage
ARCHIVE_DIR = Path(_env("SAURON_ARCHIVE_DIR", "/Volumes/External/sauron/archive"))

# Obsidian journal output
JOURNAL_DIR = Path(_env("SAURON_JOURNAL_DIR", str(BASE_DIR / "journal")))

# ── Service Ports ──
SAURON_PORT = int(_env("SAURON_PORT", "8003"))
AUDIO_ANALYZER_PORT = int(_env("AUDIO_ANALYZER_PORT", "5050"))

# ── Downstream Services ──
NETWORKING_APP_URL = _env("NETWORKING_APP_URL", "http://localhost:3000")

# ── Whisper ──
WHISPER_MODEL = _env("SAURON_WHISPER_MODEL", "medium.en")
WHISPER_LANGUAGE = _env("SAURON_WHISPER_LANGUAGE", "en")

# ── pyannote ──
PYANNOTE_PIPELINE = _env("SAURON_PYANNOTE_PIPELINE", "pyannote/speaker-diarization-3.1")

# ── Vocal Analysis ──
BASELINE_EMA_ALPHA = float(_env("SAURON_BASELINE_EMA_ALPHA", "0.1"))
DEVIATION_SIGNIFICANT = float(_env("SAURON_DEVIATION_SIGNIFICANT", "0.50"))
DEVIATION_MODERATE = float(_env("SAURON_DEVIATION_MODERATE", "0.20"))

# ── Conversation Boundaries (Pi continuous recording) ──
SILENCE_BOUNDARY_SECONDS = int(_env("SAURON_SILENCE_BOUNDARY", "180"))
MAX_RECORDING_SECONDS = int(_env("SAURON_MAX_RECORDING", "7200"))

# ── Storage Retention ──
HOT_RETENTION_DAYS = int(_env("SAURON_HOT_RETENTION_DAYS", "30"))
COLD_BITRATE = _env("SAURON_COLD_BITRATE", "64k")

# ── Audio Formats ──
SUPPORTED_FORMATS = {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus"}

# ── Claude API ──
TRIAGE_MODEL = _env("SAURON_TRIAGE_MODEL", "claude-haiku-4-5-20251001")
EXTRACTION_MODEL = _env("SAURON_EXTRACTION_MODEL", "claude-sonnet-4-6")
CLAIMS_MODEL = _env("SAURON_CLAIMS_MODEL", "claude-sonnet-4-6")

# ── Embedding / Semantic Search ──
EMBEDDING_MODEL = _env("SAURON_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBEDDING_DIM = int(_env("SAURON_EMBEDDING_DIM", "384"))

# ── Morning Brief / Email ──
MORNING_EMAIL_RECIPIENT = _env("SAURON_MORNING_EMAIL_RECIPIENT", "stephen@stephenandrews.org")
MORNING_EMAIL_TIME = _env("SAURON_MORNING_EMAIL_TIME", "06:30")

# ── Google Calendar ──
GOOGLE_CALENDAR_ID = _env("SAURON_GOOGLE_CALENDAR_ID", "stephen@stephenandrews.org")
