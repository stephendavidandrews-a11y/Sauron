"""Unified stage model — maps processing_status to canonical stages.

Both voice and text pipelines write processing_status (the operational
state machine) AND the canonical stage model (modality-agnostic view).
This module provides the mapping so both stay in sync.

Canonical stages (from plan):
    ingest, preprocess, segmentation, identity_resolution,
    extraction, human_review, routing, completed, failed

run_status values:
    active, awaiting_review, completed, failed, skipped
"""

# Voice processing_status → (current_stage, stage_detail, run_status)
VOICE_STAGE_MAP = {
    "pending":                   ("ingest",               "file_registered",           "active"),
    "transcribing":              ("preprocess",            "transcribing",              "active"),
    "diarizing":                 ("preprocess",            "diarizing",                 "active"),
    "aligning":                  ("preprocess",            "aligning",                  "active"),
    "awaiting_speaker_review":   ("identity_resolution",   "awaiting_speaker_review",   "awaiting_review"),
    "triaging":                  ("extraction",            "triaging",                  "active"),
    "triage_rejected":           ("extraction",            "triage_rejected",           "awaiting_review"),
    "extracting":                ("extraction",            "extracting",                "active"),
    "awaiting_claim_review":     ("human_review",          "claim_review",              "awaiting_review"),
    "completed":                 ("completed",             "completed",                 "completed"),
    "discarded":                 ("completed",             "discarded",                 "completed"),
    "error":                     ("failed",                "error",                     "failed"),
}


def stage_for_voice_status(processing_status: str) -> tuple[str, str, str]:
    """Return (current_stage, stage_detail, run_status) for a voice processing_status."""
    return VOICE_STAGE_MAP.get(
        processing_status,
        ("ingest", processing_status, "active"),  # fallback
    )
