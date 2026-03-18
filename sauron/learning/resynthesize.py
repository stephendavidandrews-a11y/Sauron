"""
sauron/learning/resynthesize.py

Belief re-synthesis from corrected evidence sets.

When claim corrections mark beliefs as under_review, this module
re-evaluates each affected belief using Opus and stores the result
as a proposed update for human review.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

import anthropic

from sauron.config import EXTRACTION_MODEL
from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)

_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def resynthesize_belief(belief_id: str) -> dict | None:
    """Re-synthesize a single belief from its current evidence set.

    Gathers all claims linked via belief_evidence, sends them to Opus
    with the belief's current state, and returns a proposed update.
    Does NOT auto-apply — stores proposal for human review.

    Returns dict with proposed_summary, proposed_status, proposed_confidence,
    reasoning, or None if insufficient evidence.
    """
    conn = get_connection()
    try:
        # 1. Get the belief's current state
        belief = conn.execute(
            """SELECT b.*, uc.canonical_name as entity_name
               FROM beliefs b
               LEFT JOIN unified_contacts uc ON b.entity_id = uc.id
               WHERE b.id = ?""",
            (belief_id,),
        ).fetchone()

        if not belief:
            logger.warning("Belief %s not found for re-synthesis", belief_id)
            return None

        belief = dict(belief)

        # 2. Get all linked claims with evidence details
        evidence_rows = conn.execute(
            """SELECT be.evidence_role, be.weight,
                      ec.id as claim_id, ec.claim_text, ec.claim_type,
                      ec.evidence_quote, ec.confidence as claim_confidence,
                      ec.subject_name, ec.modality, ec.review_status,
                      ec.conversation_id
               FROM belief_evidence be
               JOIN event_claims ec ON be.claim_id = ec.id
               WHERE be.belief_id = ?
               ORDER BY be.evidence_role, ec.confidence DESC""",
            (belief_id,),
        ).fetchall()

        if not evidence_rows:
            logger.info("No evidence found for belief %s, skipping re-synthesis", belief_id)
            return None

        evidence = [dict(r) for r in evidence_rows]

        # 3. Get belief transition history
        transitions = conn.execute(
            """SELECT old_status, new_status, driver, cause_summary, created_at
               FROM belief_transitions
               WHERE belief_id = ?
               ORDER BY created_at DESC
               LIMIT 10""",
            (belief_id,),
        ).fetchall()

        transition_history = [dict(t) for t in transitions]

        # 4. Build prompt for Opus
        supporting = [e for e in evidence if e["evidence_role"] == "support"]
        contradicting = [e for e in evidence if e["evidence_role"] == "contradiction"]
        other = [e for e in evidence if e["evidence_role"] not in ("support", "contradiction")]

        def format_claim(c: dict) -> str:
            parts = [f"  - [{c['claim_type']}] {c['claim_text']}"]
            if c.get("modality"):
                parts.append(f"    Modality: {c['modality']}")
            if c.get("claim_confidence"):
                parts.append(f"    Confidence: {c['claim_confidence']:.0%}")
            if c.get("evidence_quote"):
                parts.append(f'    Quote: "{c["evidence_quote"]}"')
            if c.get("review_status") and c["review_status"] != "unreviewed":
                parts.append(f"    Review status: {c['review_status']}")
            return "\n".join(parts)

        supporting_text = "\n".join(format_claim(c) for c in supporting) or "(none)"
        contradicting_text = "\n".join(format_claim(c) for c in contradicting) or "(none)"

        history_text = ""
        if transition_history:
            history_lines = []
            for t in transition_history[:5]:
                old = t.get("old_status") or "(new)"
                new = t["new_status"]
                driver = t.get("driver", "unknown")
                date = t.get("created_at", "")[:10]
                history_lines.append(f"  {old} → {new} [{driver}] {date}")
            history_text = "\n".join(history_lines)
        else:
            history_text = "(no transitions recorded)"

        prompt = f"""You are re-evaluating a belief based on its corrected evidence set.

CURRENT BELIEF:
  Key: {belief.get('belief_key', '')}
  Summary: {belief.get('belief_summary', '')}
  Status: {belief.get('status', '')}
  Confidence: {belief.get('confidence', 0):.0%}
  Entity: {belief.get('entity_name', belief.get('entity_type', 'unknown'))}

SUPPORTING EVIDENCE ({len(supporting)} claims):
{supporting_text}

CONTRADICTING EVIDENCE ({len(contradicting)} claims):
{contradicting_text}

BELIEF HISTORY:
{history_text}

NOTE: This belief was marked under_review because one or more supporting claims were corrected by the user. Re-evaluate whether the belief is still warranted given the corrected evidence.

Respond with JSON:
{{
  "proposed_summary": "Updated belief text based on corrected evidence",
  "proposed_status": "active|provisional|refined|qualified|contested|stale|superseded",
  "proposed_confidence": 0.0-1.0,
  "reasoning": "Brief explanation of what changed and why",
  "should_supersede": false,
  "insufficient_evidence": false
}}

If the corrected evidence no longer supports ANY version of this belief, set insufficient_evidence: true and proposed_status: "superseded"."""

        # 5. Call Opus
        client = _get_client()
        response = client.messages.create(
            model=EXTRACTION_MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = response.content[0].text.strip() if response.content else ""
        if not response_text:
            logger.error("Empty response from Opus for belief %s", belief_id)
            return None

        # Parse JSON from response (handle markdown code fences)
        json_text = response_text
        if "```json" in json_text:
            json_text = json_text.split("```json")[1].split("```")[0].strip()
        elif "```" in json_text:
            json_text = json_text.split("```")[1].split("```")[0].strip()

        try:
            proposal = json.loads(json_text)
        except json.JSONDecodeError:
            logger.error("Failed to parse Opus response as JSON for belief %s: %s",
                         belief_id, response_text[:200])
            return None

        # 6. Store proposal
        proposal_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO belief_resynthesis_proposals
               (id, belief_id, trigger_correction_id, current_summary,
                current_status, proposed_summary, proposed_status,
                proposed_confidence, reasoning, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
            (
                proposal_id,
                belief_id,
                None,  # trigger_correction_id set by caller if available
                belief.get("belief_summary", ""),
                belief.get("status", ""),
                proposal.get("proposed_summary", ""),
                proposal.get("proposed_status", ""),
                proposal.get("proposed_confidence"),
                proposal.get("reasoning", ""),
            ),
        )
        conn.commit()

        logger.info(
            "Created re-synthesis proposal %s for belief %s: %s → %s (%.0f%%)",
            proposal_id, belief_id,
            belief.get("status"), proposal.get("proposed_status"),
            (proposal.get("proposed_confidence") or 0) * 100,
        )

        return {
            "proposal_id": proposal_id,
            "belief_id": belief_id,
            **proposal,
        }

    except Exception:
        logger.exception("Failed to re-synthesize belief %s", belief_id)
        return None
    finally:
        conn.close()


def queue_resynthesis(belief_id: str, trigger_correction_id: str = None) -> None:
    """Queue a belief re-synthesis to run in a background thread.

    Does not block the calling thread. Failures are logged but don't
    propagate to the caller.
    """
    def _run():
        try:
            result = resynthesize_belief(belief_id)
            if result and trigger_correction_id:
                # Update the proposal with the trigger correction ID
                conn = get_connection()
                try:
                    conn.execute(
                        """UPDATE belief_resynthesis_proposals
                           SET trigger_correction_id = ?
                           WHERE id = ?""",
                        (trigger_correction_id, result["proposal_id"]),
                    )
                    conn.commit()
                finally:
                    conn.close()
        except Exception:
            logger.exception("Background re-synthesis failed for belief %s", belief_id)

    from sauron.executor import submit_background_job
    submit_background_job(_run)
    logger.info("Queued re-synthesis for belief %s (trigger: %s)", belief_id, trigger_correction_id)
