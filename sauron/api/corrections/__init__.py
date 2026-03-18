"""Correction API package — split from monolith corrections.py.

Re-exports:
  router — merged APIRouter for main.py mount
  sync_claim_entities_subject — used by bulk_reassign, people_endpoints, cascade
  _detect_relational_reference — used by extraction/cascade.py
"""
from fastapi import APIRouter

from sauron.api.corrections.helpers import (
    sync_claim_entities_subject,
    _detect_relational_reference,
)
from sauron.api.corrections.claim_endpoints import router as _claim_router
from sauron.api.corrections.review_endpoints import router as _review_router
from sauron.api.corrections.speaker_endpoints import router as _speaker_router

router = APIRouter(prefix="/correct", tags=["corrections"])
router.include_router(_claim_router)
router.include_router(_review_router)
router.include_router(_speaker_router)

__all__ = [
    "router",
    "sync_claim_entities_subject",
    "_detect_relational_reference",
]
