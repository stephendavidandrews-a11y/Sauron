"""Vocal baselines API endpoint."""

from fastapi import APIRouter, HTTPException

from sauron.db.connection import get_connection

router = APIRouter(prefix="/baselines", tags=["baselines"])


@router.get("/{contact_id}")
def get_baseline(contact_id: str):
    """Get vocal baseline data for a contact."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM vocal_baselines WHERE contact_id = ?", (contact_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="No baseline for this contact")
        return dict(row)
    finally:
        conn.close()
