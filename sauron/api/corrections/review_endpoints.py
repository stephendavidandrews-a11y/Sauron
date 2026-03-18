"""Claim review status endpoints — approve, defer, dismiss, commitment meta."""
import logging
import uuid

from fastapi import APIRouter, HTTPException

from sauron.db.connection import get_connection
from sauron.api.corrections.models import (
    ApproveClaimRequest, ApproveClaimsBulkRequest,
    DeferClaimRequest, DismissClaimRequest, CommitmentMetaRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/approve-claim")
def approve_claim(req: ApproveClaimRequest):
    """Mark a claim as approved (persists to DB)."""
    conn = get_connection()
    try:
        claim = conn.execute(
            "SELECT id, review_status FROM event_claims WHERE id = ?", (req.claim_id,)
        ).fetchone()
        if not claim:
            raise HTTPException(404, "Claim not found")

        conn.execute(
            "UPDATE event_claims SET review_status = 'user_confirmed' WHERE id = ?",
            (req.claim_id,),
        )
        conn.commit()
        return {"status": "ok", "claim_id": req.claim_id, "review_status": "user_confirmed"}
    finally:
        conn.close()


@router.post("/approve-claims-bulk")
def approve_claims_bulk(req: ApproveClaimsBulkRequest):
    """Mark multiple claims as approved in one call."""
    conn = get_connection()
    try:
        updated = 0
        for claim_id in req.claim_ids:
            conn.execute(
                "UPDATE event_claims SET review_status = 'user_confirmed' WHERE id = ?",
                (claim_id,),
            )
            updated += 1
        conn.commit()
        return {"status": "ok", "updated": updated}
    finally:
        conn.close()


@router.post("/defer-claim")
def defer_claim(req: DeferClaimRequest):
    """Defer a claim for later review."""
    conn = get_connection()
    try:
        claim = conn.execute(
            "SELECT id FROM event_claims WHERE id = ?", (req.claim_id,)
        ).fetchone()
        if not claim:
            raise HTTPException(404, "Claim not found")

        conn.execute(
            "UPDATE event_claims SET review_status = 'deferred' WHERE id = ?",
            (req.claim_id,),
        )

        if req.reason:
            conn.execute(
                """INSERT INTO correction_events
                   (id, conversation_id, claim_id, error_type, old_value, new_value,
                    user_feedback, correction_source)
                   VALUES (?, ?, ?, 'claim_text_edited', NULL, 'deferred', ?, 'manual_ui')""",
                (str(uuid.uuid4()), req.conversation_id, req.claim_id, req.reason),
            )

        conn.commit()
        return {"status": "ok", "claim_id": req.claim_id, "review_status": "deferred"}
    finally:
        conn.close()


@router.post("/dismiss-claim")
def dismiss_claim(req: DismissClaimRequest):
    """Dismiss a claim — set confidence=0, append [DISMISSED], mark beliefs under_review."""
    conn = get_connection()
    try:
        claim = conn.execute(
            "SELECT id, claim_text FROM event_claims WHERE id = ?", (req.claim_id,)
        ).fetchone()
        if not claim:
            raise HTTPException(404, "Claim not found")

        # Dismiss: confidence=0, append [DISMISSED], review_status='dismissed'
        conn.execute(
            "UPDATE event_claims SET confidence = 0, claim_text = claim_text || ' [DISMISSED]', review_status = 'dismissed' WHERE id = ?",
            (req.claim_id,),
        )

        # Log correction event
        event_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO correction_events
               (id, conversation_id, claim_id, error_type, old_value, new_value,
                user_feedback, correction_source)
               VALUES (?, ?, ?, ?, ?, 'dismissed', ?, 'manual_ui')""",
            (event_id, req.conversation_id, req.claim_id, req.error_type,
             claim["claim_text"], req.user_feedback),
        )

        # Mark supporting beliefs as under_review
        _affected = conn.execute(
            """SELECT DISTINCT b.id, b.status FROM beliefs b
               JOIN belief_evidence be ON be.belief_id = b.id
               WHERE be.claim_id = ? AND b.status != 'under_review'""",
            (req.claim_id,),
        ).fetchall()
        conn.execute(
            """UPDATE beliefs SET status = 'under_review'
               WHERE id IN (
                   SELECT DISTINCT be.belief_id FROM belief_evidence be
                   WHERE be.claim_id = ?
               )""",
            (req.claim_id,),
        )
        for _ab in _affected:
            conn.execute(
                """INSERT INTO belief_transitions
                   (id, belief_id, old_status, new_status, driver, source_correction_id)
                   VALUES (?, ?, ?, 'under_review', 'correction', ?)""",
                (str(uuid.uuid4()), _ab["id"], _ab["status"], event_id),
            )

        conn.commit()
        return {"status": "ok", "claim_id": req.claim_id, "review_status": "dismissed", "error_type": req.error_type}
    finally:
        conn.close()


@router.post("/commitment-meta")
def update_commitment_meta(req: CommitmentMetaRequest):
    """Update commitment classification metadata on a claim."""
    conn = get_connection()
    try:
        claim = conn.execute(
            "SELECT * FROM event_claims WHERE id = ?", (req.claim_id,)
        ).fetchone()
        if not claim:
            raise HTTPException(404, "Claim not found")

        claim_dict = dict(claim)
        updates = []
        params = []

        if req.firmness is not None:
            old_firmness = claim_dict.get("firmness")
            updates.append("firmness = ?")
            params.append(req.firmness)
            # Log firmness change as correction event
            if old_firmness != req.firmness:
                conn.execute(
                    """INSERT INTO correction_events
                       (id, conversation_id, claim_id, error_type, old_value, new_value,
                        correction_source)
                       VALUES (?, ?, ?, 'wrong_commitment_firmness', ?, ?, 'manual_ui')""",
                    (str(uuid.uuid4()), req.conversation_id, req.claim_id,
                     old_firmness, req.firmness),
                )

        if req.direction is not None:
            updates.append("direction = ?")
            params.append(req.direction)
        if req.has_specific_action is not None:
            updates.append("has_specific_action = ?")
            params.append(req.has_specific_action)
        if req.has_deadline is not None:
            updates.append("has_deadline = ?")
            params.append(req.has_deadline)
        if req.has_condition is not None:
            updates.append("has_condition = ?")
            params.append(req.has_condition)
        if req.condition_text is not None:
            updates.append("condition_text = ?")
            params.append(req.condition_text)
        if req.time_horizon is not None:
            updates.append("time_horizon = ?")
            params.append(req.time_horizon)

        if updates:
            params.append(req.claim_id)
            conn.execute(
                f"UPDATE event_claims SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            conn.commit()

        return {"status": "ok", "claim_id": req.claim_id}
    finally:
        conn.close()
