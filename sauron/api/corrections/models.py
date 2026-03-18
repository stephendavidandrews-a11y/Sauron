"""Pydantic request models and constants for the corrections API."""
from typing import Optional

from pydantic import BaseModel, field_validator


# --- Error taxonomy ---
ERROR_TYPES = [
    "speaker_resolution",
    "bad_episode_segmentation",
    "missed_claim",
    "hallucinated_claim",
    "wrong_claim_type",
    "wrong_modality",
    "wrong_polarity",
    "wrong_confidence",
    "wrong_stability",
    "bad_entity_linking",
    "bad_commitment_extraction",
    "bad_belief_synthesis",
    "overstated_position",
    "bad_recommendation",
    "claim_text_edited",
    "provisional_contact_merged",
    "wrong_commitment_firmness",
    "wrong_commitment_direction",
    "wrong_commitment_deadline",
    "wrong_commitment_condition",
    "wrong_commitment_time_horizon",
    "wrong_commitment_action",
]

# Generalization gating thresholds
FAST_GENERALIZE = {
    "wrong_modality", "wrong_claim_type", "wrong_confidence",
    "bad_commitment_extraction", "overstated_position", "wrong_commitment_firmness",
    "wrong_commitment_direction", "wrong_commitment_deadline",
    "wrong_commitment_condition", "wrong_commitment_time_horizon", "wrong_commitment_action",
}  # 3 corrections to generalize
SLOW_GENERALIZE = ERROR_TYPES  # everything else: 5 corrections

FIELD_ERROR_MAP = {
    "firmness": "wrong_commitment_firmness",
    "direction": "wrong_commitment_direction",
    "has_deadline": "wrong_commitment_deadline",
    "time_horizon": "wrong_commitment_deadline",
    "has_condition": "wrong_commitment_condition",
    "condition_text": "wrong_commitment_condition",
    "has_specific_action": "wrong_commitment_action",
    "claim_type": "wrong_claim_type",
    "confidence": "wrong_confidence",
    "modality": "wrong_modality",
    "polarity": "wrong_polarity",
    "stability": "wrong_stability",
    "claim_text": "claim_text_edited",
}

# Columns that can be batch-edited
BATCH_EDITABLE_COLUMNS = {
    "firmness", "direction", "has_deadline", "time_horizon",
    "has_condition", "condition_text", "has_specific_action",
    "claim_type", "confidence", "modality", "polarity", "stability",
    "claim_text",
}


class CorrectionEvent(BaseModel):
    conversation_id: str
    error_type: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    episode_id: Optional[str] = None
    claim_id: Optional[str] = None
    belief_id: Optional[str] = None
    user_feedback: Optional[str] = None
    correction_source: str = "manual_ui"

    @field_validator("error_type")
    @classmethod
    def validate_error_type(cls, v):
        if v not in ERROR_TYPES:
            raise ValueError(f"Invalid error_type: {v}. Must be one of: {ERROR_TYPES}")
        return v


class ClaimCorrection(BaseModel):
    """Convenience model for common claim corrections."""
    conversation_id: str
    claim_id: str
    error_type: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    user_feedback: Optional[str] = None

    @field_validator("error_type")
    @classmethod
    def validate_error_type(cls, v):
        if v not in ERROR_TYPES:
            raise ValueError(f"Invalid error_type: {v}. Must be one of: {ERROR_TYPES}")
        return v



class BatchClaimCorrection(BaseModel):
    """Batch correction for multiple fields on a single claim."""
    conversation_id: str
    claim_id: str
    corrections: dict  # field_name -> new_value
    user_feedback: Optional[str] = None



class AddClaimRequest(BaseModel):
    """Create a new user-authored claim."""
    conversation_id: str
    episode_id: Optional[str] = None
    claim_type: str
    claim_text: str
    subject_name: Optional[str] = None
    subject_entity_id: Optional[str] = None
    direction: Optional[str] = None
    firmness: Optional[str] = None
    has_specific_action: Optional[bool] = None
    has_deadline: Optional[bool] = None
    time_horizon: Optional[str] = None
    has_condition: Optional[bool] = None
    condition_text: Optional[str] = None
    evidence_quote: Optional[str] = None


class ReassignClaimRequest(BaseModel):
    """Reassign a claim to a different episode."""
    claim_id: str
    conversation_id: str
    episode_id: Optional[str] = None  # None = orphan



class SpeakerCorrection(BaseModel):
    conversation_id: str
    speaker_label: str
    correct_contact_id: str


class BeliefCorrection(BaseModel):
    belief_id: str
    new_status: str
    user_feedback: Optional[str] = None


class EntityLink(BaseModel):
    """Link a claim's subject to a unified_contacts record."""
    conversation_id: str
    claim_id: str
    contact_id: str
    old_subject_name: Optional[str] = None
    user_feedback: Optional[str] = None

class SaveRelationshipRequest(BaseModel):
    """Save a learned relationship to a contact's relationships JSON."""
    anchor_contact_id: str
    relationship: str  # e.g., "son", "wife", "brother"
    target_contact_id: str
    target_name: str
    notes: Optional[str] = None


class ApproveClaimRequest(BaseModel):
    conversation_id: str
    claim_id: str


class ApproveClaimsBulkRequest(BaseModel):
    conversation_id: str
    claim_ids: list[str]


class DeferClaimRequest(BaseModel):
    conversation_id: str
    claim_id: str
    reason: Optional[str] = None


class DismissClaimRequest(BaseModel):
    conversation_id: str
    claim_id: str
    error_type: str
    user_feedback: Optional[str] = None


class CommitmentMetaRequest(BaseModel):
    conversation_id: str
    claim_id: str
    firmness: Optional[str] = None
    direction: Optional[str] = None
    has_specific_action: Optional[bool] = None
    has_deadline: Optional[bool] = None
    has_condition: Optional[bool] = None
    condition_text: Optional[str] = None
    time_horizon: Optional[str] = None


class ExtractionCorrection(BaseModel):
    conversation_id: str
    correction_type: str
    original_value: Optional[str] = None
    corrected_value: str


class MergeSpeakersRequest(BaseModel):
    conversation_id: str
    from_label: str
    to_label: str


class ReassignSegmentRequest(BaseModel):
    transcript_segment_id: str
    new_speaker_label: str
