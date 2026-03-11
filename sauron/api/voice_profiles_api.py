"""Voice profile API endpoints."""

from fastapi import APIRouter, HTTPException

from sauron.speakers.profiles import list_profiles, get_profile
from sauron.db.connection import get_connection

router = APIRouter(prefix="/voice-profiles", tags=["voice-profiles"])


@router.get("")
def list_all_profiles():
    """List all enrolled speaker profiles."""
    return list_profiles()


@router.get("/{profile_id}")
def get_profile_detail(profile_id: str):
    """Get a specific voice profile."""
    profile = get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    # Don't return raw embedding bytes in API
    profile.pop("mean_embedding", None)
    return profile
