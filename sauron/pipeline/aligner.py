"""Transcript alignment — merge Whisper transcription with pyannote diarization.

Assigns each word/segment from Whisper to the speaker identified by pyannote.
"""

import logging
from dataclasses import dataclass, field

from sauron.pipeline.transcriber import TranscriptionResult, WordTimestamp
from sauron.pipeline.diarizer import DiarizationResult, SpeakerSegment

logger = logging.getLogger(__name__)


@dataclass
class AlignedWord:
    word: str
    start: float
    end: float
    speaker: str
    probability: float


@dataclass
class AlignedSegment:
    speaker: str
    start: float
    end: float
    text: str
    words: list[AlignedWord] = field(default_factory=list)


@dataclass
class AlignedTranscript:
    segments: list[AlignedSegment]
    speakers: list[str]
    duration: float


def align(
    transcription: TranscriptionResult,
    diarization: DiarizationResult,
) -> AlignedTranscript:
    """Merge Whisper transcript with pyannote diarization.

    Each Whisper word is assigned to the pyannote speaker whose segment
    overlaps most with the word's time span.

    Returns an AlignedTranscript with segments grouped by speaker turns.
    """
    # Build list of all words with speaker assignments
    aligned_words = []
    for seg in transcription.segments:
        for word in seg.words:
            speaker = _find_speaker(word, diarization.segments)
            aligned_words.append(AlignedWord(
                word=word.word,
                start=word.start,
                end=word.end,
                speaker=speaker,
                probability=word.probability,
            ))

    # Group consecutive words by the same speaker into segments
    segments = _group_by_speaker(aligned_words)
    speakers = sorted(set(s.speaker for s in segments))

    logger.info(
        f"Alignment complete: {len(segments)} segments, "
        f"{len(speakers)} speakers, {len(aligned_words)} words"
    )

    return AlignedTranscript(
        segments=segments,
        speakers=speakers,
        duration=transcription.duration,
    )


def _find_speaker(word: WordTimestamp, diar_segments: list[SpeakerSegment]) -> str:
    """Find which speaker a word belongs to based on maximum overlap."""
    word_mid = (word.start + word.end) / 2
    best_speaker = "UNKNOWN"
    best_overlap = 0.0

    for seg in diar_segments:
        overlap_start = max(word.start, seg.start)
        overlap_end = min(word.end, seg.end)
        overlap = max(0.0, overlap_end - overlap_start)

        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = seg.speaker

    # Fallback: if no overlap found, use midpoint containment
    if best_overlap == 0.0:
        for seg in diar_segments:
            if seg.start <= word_mid <= seg.end:
                return seg.speaker

    return best_speaker


def _group_by_speaker(words: list[AlignedWord]) -> list[AlignedSegment]:
    """Group consecutive words by the same speaker into segments."""
    if not words:
        return []

    segments = []
    current_speaker = words[0].speaker
    current_words = [words[0]]

    for word in words[1:]:
        if word.speaker == current_speaker:
            current_words.append(word)
        else:
            # Flush current segment
            segments.append(AlignedSegment(
                speaker=current_speaker,
                start=current_words[0].start,
                end=current_words[-1].end,
                text=" ".join(w.word for w in current_words),
                words=current_words,
            ))
            current_speaker = word.speaker
            current_words = [word]

    # Flush last segment
    if current_words:
        segments.append(AlignedSegment(
            speaker=current_speaker,
            start=current_words[0].start,
            end=current_words[-1].end,
            text=" ".join(w.word for w in current_words),
            words=current_words,
        ))

    return segments
