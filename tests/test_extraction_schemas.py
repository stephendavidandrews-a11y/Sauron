"""Test extraction Pydantic schemas — pure unit tests, no DB."""

import pytest
from pydantic import ValidationError

from sauron.extraction.schemas import (
    Claim,
    TriageResult,
    SynthesisResult,
    GraphEdge,
    BeliefUpdate,
    ClaimsResult,
    SoloExtractionResult,
    FullExtractionResult,
)


def test_claim_minimal_valid():
    """Claim with minimal fields uses correct defaults."""
    c = Claim(id="c1", claim_type="fact", claim_text="Test claim")
    assert c.confidence == 0.8
    assert c.importance == 0.5
    assert c.modality == "stated"
    assert c.polarity == "neutral"


def test_claim_confidence_out_of_range():
    """Confidence > 1 raises ValidationError."""
    with pytest.raises(ValidationError):
        Claim(id="c1", claim_type="fact", claim_text="x", confidence=1.5)


def test_claim_importance_out_of_range():
    """Importance < 0 raises ValidationError."""
    with pytest.raises(ValidationError):
        Claim(id="c1", claim_type="fact", claim_text="x", importance=-0.1)


def test_triage_result_defaults():
    """TriageResult defaults: is_solo=False, episodes=[]."""
    t = TriageResult(
        context_classification="professional_network",
        speaker_count=2,
        value_assessment="high",
        value_reasoning="important",
        summary="Test summary",
    )
    assert t.is_solo is False
    assert t.episodes == []
    assert t.topic_tags == []


def test_synthesis_result_defaults():
    """SynthesisResult list fields default to empty."""
    s = SynthesisResult(summary="Test")
    assert s.graph_edges == []
    assert s.belief_updates == []
    assert s.my_commitments == []
    assert s.topics_discussed == []
    assert s.policy_positions == []


def test_graph_edge_defaults():
    """GraphEdge strength defaults to 0.5."""
    e = GraphEdge(
        from_entity="Alice",
        to_entity="Bob",
        edge_type="knows",
    )
    assert e.strength == 0.5
    assert e.from_type == "person"
    assert e.to_type == "person"


def test_belief_update_confidence_bounds():
    """BeliefUpdate confidence > 1 raises ValidationError."""
    with pytest.raises(ValidationError):
        BeliefUpdate(
            entity_type="person",
            belief_key="test",
            belief_summary="test",
            confidence=1.1,
        )


def test_claims_result_mixed_new_contacts():
    """ClaimsResult accepts union list[str | NewContactMention]."""
    from sauron.extraction.schemas import NewContactMention
    cr = ClaimsResult(
        new_contacts_mentioned=[
            "John Doe",
            NewContactMention(name="Jane Smith", organization="CFTC"),
        ]
    )
    assert len(cr.new_contacts_mentioned) == 2
    assert cr.new_contacts_mentioned[0] == "John Doe"
    assert cr.new_contacts_mentioned[1].name == "Jane Smith"


def test_solo_extraction_result_minimal():
    """SoloExtractionResult accepts solo_mode."""
    s = SoloExtractionResult(summary="Quick note", solo_mode="debrief")
    assert s.solo_mode == "debrief"
    assert s.tasks == []
    assert s.ideas == []


def test_full_extraction_result_composition():
    """FullExtractionResult composes triage + claims + synthesis."""
    triage = TriageResult(
        context_classification="personal",
        speaker_count=2,
        value_assessment="medium",
        value_reasoning="ok",
        summary="test",
    )
    claims = ClaimsResult()
    synthesis = SynthesisResult(summary="test synthesis")

    full = FullExtractionResult(triage=triage, claims=claims, synthesis=synthesis)
    assert full.triage.speaker_count == 2
    assert full.synthesis.summary == "test synthesis"
    assert full.claims.claims == []
