"""Sauron configuration — paths, ports, and settings."""

from pathlib import Path

# ── Paths ──
BASE_DIR = Path("/Users/stephen/Documents/Website/Sauron")
DATA_DIR = BASE_DIR / "data"
INBOX_DIR = BASE_DIR / "inbox"
INBOX_PI = INBOX_DIR / "pi"
INBOX_PLAUD = INBOX_DIR / "plaud"
INBOX_IPHONE_DIR = INBOX_DIR / "iphone"
INBOX_EMAIL_DIR = INBOX_DIR / "email"
INBOX_METADATA = INBOX_DIR / "metadata"
LOGS_DIR = BASE_DIR / "logs"
MODELS_DIR = BASE_DIR / "models"

DB_PATH = DATA_DIR / "sauron.db"

# External drive for cold storage
ARCHIVE_DIR = Path("/Volumes/External/sauron/archive")

# Obsidian journal output
JOURNAL_DIR = BASE_DIR / "journal"

# ── Service Ports ──
SAURON_PORT = 8003
AUDIO_ANALYZER_PORT = 5050

# ── Downstream Services ──
NETWORKING_APP_URL = "http://localhost:3000"
CFTC_APP_URL = "http://localhost:8000"

# ── Whisper ──
WHISPER_MODEL = "medium.en"
WHISPER_LANGUAGE = "en"

# ── pyannote ──
PYANNOTE_PIPELINE = "pyannote/speaker-diarization-3.1"

# ── Vocal Analysis ──
BASELINE_EMA_ALPHA = 0.1  # Exponential moving average smoothing
DEVIATION_SIGNIFICANT = 0.50  # >=50% above/below baseline
DEVIATION_MODERATE = 0.20     # 20-50%

# ── Conversation Boundaries (Pi continuous recording) ──
SILENCE_BOUNDARY_SECONDS = 180  # 3 minutes silence = new conversation
MAX_RECORDING_SECONDS = 7200    # 2 hours max

# ── Storage Retention ──
HOT_RETENTION_DAYS = 30  # Keep raw audio on SSD for 30 days
COLD_BITRATE = "64k"     # 64kbps MP3 for archive

# ── Audio Formats ──
SUPPORTED_FORMATS = {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus"}

# ── Claude API ──
TRIAGE_MODEL = "claude-haiku-4-5-20251001"
EXTRACTION_MODEL = "claude-opus-4-6"
CLAIMS_MODEL = "claude-sonnet-4-6"

# ── Embedding / Semantic Search ──
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

# ── Morning Brief / Email ──
MORNING_EMAIL_RECIPIENT = "stephen@stephenandrews.org"
MORNING_EMAIL_TIME = "06:30"

# ── Google Calendar ──
GOOGLE_CALENDAR_ID = "stephen@stephenandrews.org"
