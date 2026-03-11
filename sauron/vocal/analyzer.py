"""Vocal analysis module — Parselmouth + librosa feature extraction.

Extracts 25+ acoustic features per speaker segment for emotional state
detection, stress analysis, and baseline comparison.
"""

import json
import logging
import uuid
from pathlib import Path

import numpy as np

from sauron.config import BASELINE_EMA_ALPHA, DEVIATION_SIGNIFICANT, DEVIATION_MODERATE
from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)


def extract_vocal_features(audio_path: Path, start: float, end: float) -> dict:
    """Extract vocal features from an audio segment using Parselmouth and librosa.

    Args:
        audio_path: Path to the full audio file.
        start: Segment start time in seconds.
        end: Segment end time in seconds.

    Returns:
        Dict of extracted features.
    """
    import parselmouth
    from parselmouth.praat import call
    import librosa
    import soundfile as sf

    # Load the segment
    y, sr = librosa.load(str(audio_path), sr=None, offset=start, duration=end - start)

    if len(y) < sr * 0.3:  # Skip segments shorter than 0.3s
        return {}

    features = {}

    # === Parselmouth features ===
    try:
        snd = parselmouth.Sound(y.astype(np.float64), sampling_frequency=sr)

        # Pitch
        pitch = call(snd, "To Pitch", 0.0, 75, 600)
        features["pitch_mean"] = call(pitch, "Get mean", 0, 0, "Hertz")
        features["pitch_std"] = call(pitch, "Get standard deviation", 0, 0, "Hertz")
        features["pitch_min"] = call(pitch, "Get minimum", 0, 0, "Hertz", "Parabolic")
        features["pitch_max"] = call(pitch, "Get maximum", 0, 0, "Hertz", "Parabolic")

        # Jitter and Shimmer
        point_process = call(snd, "To PointProcess (periodic, cc)", 75, 600)
        features["jitter"] = call(point_process, "Get jitter (local)", 0, 0, 0.0001, 0.02, 1.3)
        features["shimmer"] = call(
            [snd, point_process], "Get shimmer (local)", 0, 0, 0.0001, 0.02, 1.3, 1.6
        )

        # HNR
        harmonicity = call(snd, "To Harmonicity (cc)", 0.01, 75, 0.1, 1.0)
        features["hnr"] = call(harmonicity, "Get mean", 0, 0)

        # Intensity
        intensity = call(snd, "To Intensity", 75, 0, "yes")
        features["intensity_mean"] = call(intensity, "Get mean", 0, 0, "energy")

        # Formants F1-F3
        formant = call(snd, "To Formant (burg)", 0.0, 5, 5500, 0.025, 50)
        features["f1_mean"] = call(formant, "Get mean", 1, 0, 0, "Hertz")
        features["f2_mean"] = call(formant, "Get mean", 2, 0, 0, "Hertz")
        features["f3_mean"] = call(formant, "Get mean", 3, 0, 0, "Hertz")
    except Exception:
        logger.debug("Parselmouth extraction partially failed", exc_info=True)

    # === librosa features ===
    try:
        # MFCCs
        mfccs = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
        features["mfcc_means"] = json.dumps(np.mean(mfccs, axis=1).tolist())

        # RMS energy
        rms = librosa.feature.rms(y=y)
        features["rms_mean"] = float(np.mean(rms))

        # Spectral centroid
        sc = librosa.feature.spectral_centroid(y=y, sr=sr)
        features["spectral_centroid"] = float(np.mean(sc))

        # Zero-crossing rate
        zcr = librosa.feature.zero_crossing_rate(y)
        features["zcr_mean"] = float(np.mean(zcr))

        # Spectral rolloff
        rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr)
        features["spectral_rolloff"] = float(np.mean(rolloff))

        # Speaking rate (approximate via onset detection)
        onsets = librosa.onset.onset_detect(y=y, sr=sr)
        duration = end - start
        if duration > 0:
            features["speaking_rate_wpm"] = len(onsets) / duration * 60
    except Exception:
        logger.debug("librosa extraction partially failed", exc_info=True)

    # Replace NaN values with None
    for key, value in features.items():
        if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
            features[key] = None

    return features


def store_vocal_features(
    conversation_id: str,
    speaker_id: str | None,
    segment_start: float,
    segment_end: float,
    features: dict,
) -> str:
    """Store extracted vocal features in sauron.db."""
    conn = get_connection()
    try:
        feat_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO vocal_features (
                id, conversation_id, speaker_id, segment_start, segment_end,
                pitch_mean, pitch_std, pitch_min, pitch_max,
                jitter, shimmer, hnr, intensity_mean,
                f1_mean, f2_mean, f3_mean,
                mfcc_means, rms_mean, spectral_centroid, zcr_mean, spectral_rolloff,
                speaking_rate_wpm
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                feat_id, conversation_id, speaker_id, segment_start, segment_end,
                features.get("pitch_mean"), features.get("pitch_std"),
                features.get("pitch_min"), features.get("pitch_max"),
                features.get("jitter"), features.get("shimmer"),
                features.get("hnr"), features.get("intensity_mean"),
                features.get("f1_mean"), features.get("f2_mean"), features.get("f3_mean"),
                features.get("mfcc_means"), features.get("rms_mean"),
                features.get("spectral_centroid"), features.get("zcr_mean"),
                features.get("spectral_rolloff"), features.get("speaking_rate_wpm"),
            ),
        )
        conn.commit()
        return feat_id
    finally:
        conn.close()


def update_baseline(contact_id: str, features: dict):
    """Update vocal baseline for a contact using exponential moving average.

    EMA formula: new_baseline = alpha * new_value + (1 - alpha) * old_baseline
    """
    alpha = BASELINE_EMA_ALPHA
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM vocal_baselines WHERE contact_id = ?", (contact_id,)
        ).fetchone()

        baseline_fields = [
            "pitch_mean", "pitch_std", "jitter", "shimmer", "hnr",
            "speaking_rate_wpm", "spectral_centroid", "rms_mean",
            "f1_mean", "f2_mean", "f3_mean",
        ]

        if row is None:
            # First sample — initialize baseline directly
            conn.execute(
                """INSERT INTO vocal_baselines (
                    id, contact_id, pitch_mean, pitch_std, jitter, shimmer, hnr,
                    speaking_rate_wpm, spectral_centroid, rms_mean,
                    f1_mean, f2_mean, f3_mean, sample_count, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, datetime('now'))""",
                (
                    str(uuid.uuid4()), contact_id,
                    features.get("pitch_mean"), features.get("pitch_std"),
                    features.get("jitter"), features.get("shimmer"), features.get("hnr"),
                    features.get("speaking_rate_wpm"), features.get("spectral_centroid"),
                    features.get("rms_mean"),
                    features.get("f1_mean"), features.get("f2_mean"), features.get("f3_mean"),
                ),
            )
        else:
            # EMA update
            updates = {}
            for field in baseline_fields:
                new_val = features.get(field)
                old_val = row[field]
                if new_val is not None and old_val is not None:
                    updates[field] = alpha * new_val + (1 - alpha) * old_val
                elif new_val is not None:
                    updates[field] = new_val

            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                values = list(updates.values())
                conn.execute(
                    f"UPDATE vocal_baselines SET {set_clause}, "
                    "sample_count = sample_count + 1, last_updated = datetime('now') "
                    "WHERE contact_id = ?",
                    values + [contact_id],
                )

        conn.commit()
    finally:
        conn.close()


def compare_to_baseline(contact_id: str, features: dict) -> dict[str, str]:
    """Compare current features to baseline, return deviation levels.

    Returns dict of field -> deviation level ('SIGNIFICANT', 'MODERATE', 'normal').
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM vocal_baselines WHERE contact_id = ?", (contact_id,)
        ).fetchone()

        if row is None or row["sample_count"] < 3:
            return {}  # Not enough data for comparison

        deviations = {}
        for field in ["pitch_mean", "jitter", "shimmer", "hnr", "speaking_rate_wpm",
                       "spectral_centroid", "rms_mean"]:
            new_val = features.get(field)
            baseline_val = row[field]
            if new_val is not None and baseline_val is not None and baseline_val != 0:
                pct_change = abs(new_val - baseline_val) / abs(baseline_val)
                if pct_change >= DEVIATION_SIGNIFICANT:
                    deviations[field] = "SIGNIFICANT"
                elif pct_change >= DEVIATION_MODERATE:
                    deviations[field] = "MODERATE"
                else:
                    deviations[field] = "normal"

        return deviations
    finally:
        conn.close()
