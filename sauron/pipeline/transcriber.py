"""Whisper transcription module.

Uses whisper large-v3 with Metal acceleration on Apple Silicon.
Produces word-level timestamps for alignment with diarization.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Lazy-load whisper to avoid slow import at startup
_whisper_model = None


def _get_device():
    """Select best available device for Whisper.
    
    Note: MPS (Apple Silicon Metal) disabled for Whisper because the DTW
    word-timestamp alignment requires float64 which MPS does not support.
    medium.en on CPU is still ~3-4x faster than large-v3 was.
    """
    import torch
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _get_model():
    global _whisper_model
    if _whisper_model is None:
        import whisper
        from sauron.config import WHISPER_MODEL, MODELS_DIR
        download_root = MODELS_DIR / "whisper"
        download_root.mkdir(parents=True, exist_ok=True)
        device = _get_device()
        logger.info(f"Loading Whisper model: {WHISPER_MODEL} on {device} (cache: {download_root})")
        _whisper_model = whisper.load_model(WHISPER_MODEL, device=device, download_root=str(download_root))
        logger.info(f"Whisper model loaded on {device}")
    return _whisper_model


@dataclass
class WordTimestamp:
    word: str
    start: float
    end: float
    probability: float


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    words: list[WordTimestamp] = field(default_factory=list)


@dataclass
class TranscriptionResult:
    segments: list[TranscriptSegment]
    language: str
    duration: float


def transcribe(audio_path: Path) -> TranscriptionResult:
    """Transcribe audio file using Whisper large-v3.

    Args:
        audio_path: Path to audio file (wav, flac, mp3, etc.)

    Returns:
        TranscriptionResult with segments and word-level timestamps.
    """
    model = _get_model()

    logger.info(f"Transcribing: {audio_path.name}")
    result = model.transcribe(
        str(audio_path),
        language="en",
        word_timestamps=True,
        condition_on_previous_text=True,
        verbose=False,
    )

    segments = []
    for seg in result["segments"]:
        words = []
        for w in seg.get("words", []):
            words.append(WordTimestamp(
                word=w["word"].strip(),
                start=w["start"],
                end=w["end"],
                probability=w.get("probability", 0.0),
            ))
        segments.append(TranscriptSegment(
            start=seg["start"],
            end=seg["end"],
            text=seg["text"].strip(),
            words=words,
        ))

    # Get duration from the last segment end time
    duration = segments[-1].end if segments else 0.0

    logger.info(f"Transcription complete: {len(segments)} segments, {duration:.1f}s")
    return TranscriptionResult(
        segments=segments,
        language=result.get("language", "en"),
        duration=duration,
    )
