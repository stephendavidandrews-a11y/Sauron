"""Audio preprocessing — normalize any input format to 16kHz mono WAV.

Compressed formats (AAC/m4a, MP3, OGG) can have sample count mismatches
when decoded, causing pyannote diarization to fail with chunk size errors.
Converting to WAV with a fixed sample rate guarantees clean PCM alignment.

This also normalizes across all ingestion sources:
- iPhone: m4a (AAC)
- Plaud: wav/mp3
- Pi: FLAC
- Email: any format
"""

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Target format for pipeline processing
TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1

# Formats that need conversion (anything not already clean WAV)
NEEDS_CONVERSION = {".m4a", ".mp4", ".aac", ".mp3", ".ogg", ".opus", ".flac", ".wma", ".webm"}

# Resolve ffmpeg/ffprobe paths — Homebrew on macOS puts them in /opt/homebrew/bin
# which may not be in PATH for background services or SSH sessions.
_HOMEBREW_BIN = "/opt/homebrew/bin"


def _find_tool(name: str) -> str:
    """Find ffmpeg/ffprobe, checking Homebrew path if not in PATH."""
    found = shutil.which(name)
    if found:
        return found
    homebrew_path = f"{_HOMEBREW_BIN}/{name}"
    if Path(homebrew_path).exists():
        return homebrew_path
    raise FileNotFoundError(f"{name} not found in PATH or {_HOMEBREW_BIN}")


def prepare_audio(audio_path: Path, cache_dir: Path | None = None) -> Path:
    """Convert audio to 16kHz mono WAV for pipeline processing.

    If the file is already a WAV at 16kHz mono, returns it as-is.
    Otherwise, converts using ffmpeg and caches the result alongside
    the original file (or in cache_dir if specified).

    Args:
        audio_path: Path to the original audio file.
        cache_dir: Optional directory for converted files.
                   Defaults to same directory as the original.

    Returns:
        Path to the 16kHz mono WAV file (may be the original if already WAV).
    """
    suffix = audio_path.suffix.lower()

    # Determine output path
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        wav_path = cache_dir / f"{audio_path.stem}.wav"
    else:
        wav_path = audio_path.with_suffix(".wav")

    # If converted file already exists and is newer than source, reuse it
    if wav_path.exists() and wav_path.stat().st_mtime >= audio_path.stat().st_mtime:
        logger.info(f"Using cached WAV: {wav_path.name}")
        return wav_path

    # If already WAV, check if it needs resampling
    if suffix == ".wav":
        if _is_target_format(audio_path):
            return audio_path
        # WAV but wrong sample rate — still needs conversion
        logger.info(f"Resampling WAV to {TARGET_SAMPLE_RATE}Hz mono: {audio_path.name}")
    else:
        logger.info(f"Converting {suffix} to {TARGET_SAMPLE_RATE}Hz mono WAV: {audio_path.name}")

    # Convert with ffmpeg
    try:
        ffmpeg_path = _find_tool("ffmpeg")
        cmd = [
            ffmpeg_path, "-y",        # overwrite
            "-i", str(audio_path),    # input
            "-ac", str(TARGET_CHANNELS),   # mono
            "-ar", str(TARGET_SAMPLE_RATE), # 16kHz
            "-sample_fmt", "s16",     # 16-bit PCM
            str(wav_path),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 min max for long files
        )
        if result.returncode != 0:
            logger.error(f"ffmpeg conversion failed: {result.stderr[-500:]}")
            raise RuntimeError(f"ffmpeg failed with code {result.returncode}")

        logger.info(f"Converted to WAV: {wav_path.name} ({wav_path.stat().st_size / 1024 / 1024:.1f} MB)")
        return wav_path

    except FileNotFoundError:
        raise RuntimeError(
            "ffmpeg not found in PATH or /opt/homebrew/bin. Install with: brew install ffmpeg"
        )


def _is_target_format(wav_path: Path) -> bool:
    """Check if a WAV file is already at the target sample rate and channels."""
    try:
        ffprobe_path = _find_tool("ffprobe")
        cmd = [
            ffprobe_path, "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            str(wav_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return False

        import json
        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "audio":
                sr = int(stream.get("sample_rate", 0))
                ch = int(stream.get("channels", 0))
                return sr == TARGET_SAMPLE_RATE and ch == TARGET_CHANNELS
        return False
    except Exception:
        return False
