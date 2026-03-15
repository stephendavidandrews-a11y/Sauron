"""Text claim review policy — assigns tiers to claims for review routing.

Tiers:
  auto_route  — Explicit high-confidence facts/preferences. Routed without review.
  quick_review — Commitments, positions, explicit observations. Human glances.
  hold         — Inferred, ambiguous, relationship, low-confidence. Full review.

Policy rules are evaluated in priority order (highest first). First match wins.
Rules are hardcoded for Phase 1 (not DB-driven) per plan decision.
"""

import logging

logger = logging.getLogger(__name__)


# Priority-ordered rules. First match wins.
# Each rule: (priority, claim_type_match, condition_fn, tier, rationale)
POLICY_RULES = [
    # --- HOLD rules (highest priority) ---
    (100, "*", lambda c: bool(getattr(c, "_creates_new_contact", False)),
     "hold", "Never auto-create contacts"),

    (95, "*", lambda c: (c.confidence or 0) < 0.5,
     "hold", "Unreliable extraction (confidence < 0.5)"),

    (90, "*", lambda c: getattr(c, "evidence_quality", None) == "ambiguous",
     "hold", "Ambiguous evidence needs human validation"),

    (85, "*", lambda c: getattr(c, "evidence_quality", None) == "inferred",
     "hold", "Inferred claims always need human validation"),

    (80, "relationship", lambda c: True,
     "hold", "Relationship claims are sensitive — hold in Phase 1"),

    (75, "tactical", lambda c: getattr(c, "evidence_quality", None) != "explicit",
     "hold", "Non-explicit tactical reads held"),

    (70, "observation", lambda c: getattr(c, "evidence_quality", None) != "explicit",
     "hold", "Non-explicit observations held"),

    # --- QUICK_REVIEW rules ---
    (65, "commitment", lambda c: True,
     "quick_review", "ALL commitments get human review in Phase 1"),

    (60, "position", lambda c: True,
     "quick_review", "Positions deserve a sanity check"),

    (55, "tactical", lambda c: getattr(c, "evidence_quality", None) == "explicit",
     "quick_review", "Explicit tactical advice worth a glance"),

    (50, "observation", lambda c: getattr(c, "evidence_quality", None) == "explicit",
     "quick_review", "Explicit observations usually reliable"),

    # --- AUTO_ROUTE rules ---
    (45, "fact", lambda c: (
        getattr(c, "evidence_quality", None) == "explicit"
        and (c.confidence or 0) > 0.85
    ), "auto_route", "High-confidence explicit facts are safe"),

    (40, "preference", lambda c: (
        getattr(c, "evidence_quality", None) == "explicit"
        and (c.confidence or 0) > 0.80
    ), "auto_route", "Clear explicit preferences are safe"),

    # --- DEFAULT ---
    (10, "*", lambda c: True,
     "quick_review", "Default: human glances at it"),
]


def assign_review_tier(claim, modality: str = "text") -> str:
    """Evaluate a claim against policy rules and return its review tier.

    Args:
        claim: A Claim object (Pydantic model) or dict with claim fields
        modality: 'text', 'voice', 'email'

    Returns:
        'auto_route', 'quick_review', or 'hold'
    """
    claim_type = getattr(claim, "claim_type", None) or claim.get("claim_type", "")

    for priority, type_match, condition_fn, tier, rationale in POLICY_RULES:
        # Check type match
        if type_match != "*" and type_match != claim_type:
            continue

        # Check condition
        try:
            if condition_fn(claim):
                logger.debug(
                    "Claim %s → %s (priority %d: %s)",
                    getattr(claim, "id", "?"), tier, priority, rationale,
                )
                return tier
        except Exception:
            continue

    return "quick_review"


def assign_tiers_batch(claims: list, modality: str = "text") -> dict:
    """Assign review tiers to a batch of claims.

    Returns:
        dict with tier → list of claim IDs
    """
    result = {"auto_route": [], "quick_review": [], "hold": []}

    for claim in claims:
        tier = assign_review_tier(claim, modality)
        claim_id = getattr(claim, "id", None) or claim.get("id", "?")
        result[tier].append(claim_id)

    logger.info(
        "Review tier assignment: auto_route=%d, quick_review=%d, hold=%d",
        len(result["auto_route"]),
        len(result["quick_review"]),
        len(result["hold"]),
    )
    return result
