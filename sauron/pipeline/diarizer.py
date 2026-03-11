"""pyannote speaker diarization module.

Uses pyannote/speaker-diarization-3.1 for speaker segmentation.
Extracts speaker embeddings as byproduct for voice print enrollment.

pyannote 4.x returns DiarizeOutput with:
  .speaker_diarization  — Annotation object (itertracks)
  .speaker_embeddings   — ndarray (num_speakers, embedding_dim)
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

logger = logging.getLogger(__name__)

# Lazy-load pipeline
_diarization_pipeline = None


def _get_pipeline():
    global _diarization_pipeline
    if _diarization_pipeline is None:
        from pyannote.audio import Pipeline
        from sauron.config import PYANNOTE_PIPELINE

        logger.info(f"Loading pyannote pipeline: {PYANNOTE_PIPELINE}")

        # Requires HF_TOKEN env var for gated model access
        import os
        hf_token = os.environ.get("HF_TOKEN")
        if not hf_token:
            raise RuntimeError(
                "HF_TOKEN not set. pyannote/speaker-diarization-3.1 is a gated model. "
                "1) Accept terms at https://huggingface.co/pyannote/speaker-diarization-3.1 "
                "2) Create token at https://huggingface.co/settings/tokens "
                "3) Set HF_TOKEN in .env or environment"
            )
        _diarization_pipeline = Pipeline.from_pretrained(PYANNOTE_PIPELINE, token=hf_token)

        # Use MPS (Metal) if available on Apple Silicon
        if torch.backends.mps.is_available():
            _diarization_pipeline.to(torch.device("mps"))
            logger.info("pyannote using Metal (MPS) acceleration")
        else:
            logger.info("pyannote using CPU")

    return _diarization_pipeline


@dataclass
class SpeakerSegment:
    speaker: str  # SPEAKER_00, SPEAKER_01, etc.
    start: float
    end: float


@dataclass
class SpeakerEmbedding:
    speaker: str
    embedding: np.ndarray  # pyannote speaker embedding vector


@dataclass
class DiarizationResult:
    segments: list[SpeakerSegment]
    embeddings: dict[str, np.ndarray]  # speaker_label -> mean embedding
    num_speakers: int


def diarize(
    audio_path: Path,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
) -> DiarizationResult:
    """Run speaker diarization on audio file.

    Args:
        audio_path: Path to audio file (should be 16kHz mono WAV from audio_prep).
        min_speakers: Minimum expected speakers (from calendar context).
        max_speakers: Maximum expected speakers (from calendar context).

    Returns:
        DiarizationResult with speaker segments and embeddings.
    """
    pipeline = _get_pipeline()

    logger.info(f"Diarizing: {audio_path.name}")
    kwargs = {}
    if min_speakers is not None:
        kwargs["min_speakers"] = min_speakers
    if max_speakers is not None:
        kwargs["max_speakers"] = max_speakers

    result = pipeline(str(audio_path), **kwargs)

    # pyannote 4.x returns DiarizeOutput with .speaker_diarization (Annotation)
    # and .speaker_embeddings (ndarray). Earlier versions returned Annotation directly.
    if hasattr(result, "speaker_diarization"):
        annotation = result.speaker_diarization
    else:
        annotation = result  # fallback for older pyannote

    # Extract segments
    segments = []
    for turn, _, speaker in annotation.itertracks(yield_label=True):
        segments.append(SpeakerSegment(
            speaker=speaker,
            start=turn.start,
            end=turn.end,
        ))

    # Extract embeddings — pyannote 4.x provides them directly
    embeddings = _extract_embeddings(result, segments)

    speakers = set(s.speaker for s in segments)
    logger.info(f"Diarization complete: {len(speakers)} speakers, {len(segments)} segments")

    return DiarizationResult(
        segments=segments,
        embeddings=embeddings,
        num_speakers=len(speakers),
    )


def _extract_embeddings(
    result, segments: list[SpeakerSegment]
) -> dict[str, np.ndarray]:
    """Extract per-speaker embeddings from diarization result.

    pyannote 4.x provides speaker_embeddings directly as an ndarray
    with shape (num_speakers, embedding_dim). We map these to speaker labels.
    Falls back gracefully if embeddings aren't available.
    """
    try:
        if hasattr(result, "speaker_embeddings") and result.speaker_embeddings is not None:
            emb_array = result.speaker_embeddings
            # Get unique speaker labels in order
            speaker_labels = sorted(set(s.speaker for s in segments))
            embeddings = {}
            for i, label in enumerate(speaker_labels):
                if i < len(emb_array):
                    embeddings[label] = emb_array[i]
            logger.info(f"Speaker embeddings extracted: {len(embeddings)} speakers, dim={emb_array.shape[1]}")
            return embeddings
        else:
            logger.warning("No speaker embeddings available from diarization result")
            return {}
    except Exception:
        logger.exception("Failed to extract speaker embeddings")
        return {}
