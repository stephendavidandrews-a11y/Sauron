"""Pass 2.5: Claims Deduplication.

After Sonnet extraction, merge near-duplicate claims that say the same thing
in different words. Uses embedding-based cosine similarity.

One conversation often produces near-duplicates like:
  - "Heath is skeptical of the draft"
  - "Heath expressed concern about the draft"
  - "Heath may not support the draft fully"
These are the same claim. Keep the strongest wording, preserve all evidence spans,
and take the highest confidence.

Threshold: cosine similarity > 0.85 on claim_text embeddings -> merge candidates.
"""

import logging
from collections import defaultdict

import numpy as np

from sauron.extraction.schemas import Claim, ClaimsResult

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.85


def dedup_claims(claims_result: ClaimsResult) -> ClaimsResult:
    """Deduplicate near-identical claims using embedding similarity.

    Groups claims by (subject_name, claim_type), then within each group
    computes pairwise cosine similarity on claim_text embeddings and merges
    clusters above the threshold.

    Merge strategy:
    - Keep the longest/most detailed claim_text
    - Take the highest confidence
    - Take the highest importance
    - Preserve all unique evidence_quotes (pick best one for primary)
    - Keep all unique evidence spans

    Returns:
        New ClaimsResult with deduplicated claims (memory_writes and new_contacts unchanged).
    """
    claims = claims_result.claims
    if len(claims) < 2:
        return claims_result

    try:
        from sentence_transformers import SentenceTransformer
        import os
        from sauron.config import MODELS_DIR

        os.environ["HF_HOME"] = str(MODELS_DIR / "huggingface")
        model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    except Exception:
        logger.warning("Embedding model unavailable for dedup — skipping")
        return claims_result

    # Group claims by (subject_name_lower, claim_type) to narrow comparisons
    groups = defaultdict(list)
    for i, c in enumerate(claims):
        key = (c.subject_name.lower().strip() if c.subject_name else "", c.claim_type)
        groups[key].append(i)

    # Track which claims get merged away
    merged_into = {}  # claim_index -> surviving_claim_index

    for key, indices in groups.items():
        if len(indices) < 2:
            continue

        # Encode claim texts for this group
        texts = [claims[i].claim_text for i in indices]
        embeddings = model.encode(texts, normalize_embeddings=True)

        # Find clusters above similarity threshold
        for a in range(len(indices)):
            if indices[a] in merged_into:
                continue
            for b in range(a + 1, len(indices)):
                if indices[b] in merged_into:
                    continue

                sim = float(np.dot(embeddings[a], embeddings[b]))
                if sim >= SIMILARITY_THRESHOLD:
                    # Merge b into a
                    merged_into[indices[b]] = indices[a]

    if not merged_into:
        logger.info(f"Dedup: no duplicates found in {len(claims)} claims")
        return claims_result

    # Build merged claims
    # For each surviving claim, collect all claims merged into it
    merge_groups = defaultdict(list)
    for victim, survivor in merged_into.items():
        # Follow chain
        while survivor in merged_into:
            survivor = merged_into[survivor]
        merge_groups[survivor].append(victim)

    # Create new claim list
    deduped = []
    for i, claim in enumerate(claims):
        if i in merged_into:
            continue  # Skip merged-away claims

        if i in merge_groups:
            # This is a survivor — merge in data from victims
            merged_claims = [claims[j] for j in merge_groups[i]]
            claim = _merge_claims(claim, merged_claims)

        deduped.append(claim)

    # Re-number claim IDs
    for idx, c in enumerate(deduped):
        c.id = f"claim_{idx + 1:03d}"

    pre_count = len(claims)
    post_count = len(deduped)
    logger.info(f"Dedup: {pre_count} -> {post_count} claims ({pre_count - post_count} merged)")

    return ClaimsResult(
        claims=deduped,
        memory_writes=claims_result.memory_writes,
        new_contacts_mentioned=claims_result.new_contacts_mentioned,
    )


def _merge_claims(survivor: Claim, victims: list[Claim]) -> Claim:
    """Merge victim claims into the survivor.

    Strategy:
    - Keep longest claim_text (most detailed)
    - Take highest confidence
    - Take highest importance
    - Keep best evidence_quote (longest)
    - Preserve earliest evidence_start, latest evidence_end
    """
    all_claims = [survivor] + victims

    # Pick the longest claim_text
    best_text = max(all_claims, key=lambda c: len(c.claim_text))
    survivor.claim_text = best_text.claim_text

    # Highest confidence
    survivor.confidence = max(c.confidence for c in all_claims)

    # Highest importance
    survivor.importance = max(c.importance for c in all_claims)

    # Best evidence_quote (longest)
    best_evidence = max(all_claims, key=lambda c: len(c.evidence_quote) if c.evidence_quote else 0)
    if best_evidence.evidence_quote:
        survivor.evidence_quote = best_evidence.evidence_quote

    # Prefer "quote" > "paraphrase" > "interaction_derived"
    evidence_rank = {"quote": 3, "paraphrase": 2, "interaction_derived": 1}
    best_et = max(all_claims, key=lambda c: evidence_rank.get(c.evidence_type, 0))
    survivor.evidence_type = best_et.evidence_type

    # Widest evidence span
    starts = [c.evidence_start for c in all_claims if c.evidence_start is not None]
    ends = [c.evidence_end for c in all_claims if c.evidence_end is not None]
    if starts:
        survivor.evidence_start = min(starts)
    if ends:
        survivor.evidence_end = max(ends)

    return survivor
