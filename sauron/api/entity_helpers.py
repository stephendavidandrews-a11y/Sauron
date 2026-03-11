"""Shared entity name helpers used by conversations.py and corrections.py.

Extracted to avoid circular imports between those modules.
"""

import re


# ═══════════════════════════════════════════════════════
# HELPERS — confirmed name replacement
# ═══════════════════════════════════════════════════════

def _has_ambiguous_name_ref(claim_text: str, from_name: str, to_name: str) -> bool:
    """Check if claim_text contains ambiguous single-name references.

    Returns True if the text mentions a first name shared between from and to
    entities without using either full name.
    """
    from_first = from_name.split()[0].lower() if from_name else ""
    to_first = to_name.split()[0].lower() if to_name else ""

    if not from_first or from_first != to_first:
        return False

    text_lower = claim_text.lower()
    from_full_lower = from_name.lower()
    to_full_lower = to_name.lower()

    has_first_name = from_first in text_lower
    has_from_full = from_full_lower in text_lower
    has_to_full = to_full_lower in text_lower

    return has_first_name and not has_from_full and not has_to_full


def replace_confirmed_name(claim_text: str, canonical_name: str,
                           other_names: list[str] | None = None) -> str | None:
    """Replace standalone first-name references with the full canonical name.

    Called after a confirmed entity assignment (bulk reassign or entity link).
    The user has confirmed the identity, so it is safe to update the actual text.

    Args:
        claim_text: The original claim text.
        canonical_name: The confirmed full name (e.g., "Stephen Weber").
        other_names: Optional list of other entity names in this claim.
                     If another name shares the same first name, returns None
                     (ambiguous — flag for manual review).

    Returns:
        Updated claim text with full names, or None if ambiguous
        (multiple people with same first name in the claim).
    """
    if not canonical_name or " " not in canonical_name:
        return claim_text  # Single-name entity, no disambiguation possible

    first_name = canonical_name.split()[0]
    if not first_name:
        return claim_text

    # Ambiguity check: does another entity in this claim share the first name?
    if other_names:
        for other in other_names:
            if not other:
                continue
            other_first = other.split()[0]
            if other_first.lower() == first_name.lower() and other.lower() != canonical_name.lower():
                return None  # Two different people with same first name — flag for manual

    # Find standalone first-name references (not already part of a full name)
    pattern = re.compile(r"\b" + re.escape(first_name) + r"\b", re.IGNORECASE)

    def _replace_match(m):
        end_pos = m.end()
        remaining = claim_text[end_pos:end_pos + 50]
        # Skip if already followed by a capitalized surname (already a full name)
        if remaining and re.match(r"\s+[A-Z][a-z]+", remaining):
            return m.group()
        return canonical_name

    result = pattern.sub(_replace_match, claim_text)
    return result



def replace_name_in_text(text: str, old_name: str, new_name: str) -> str | None:
    """Replace an old entity name with a new one in claim text.

    Handles:
    - Full name -> full name: "Stephen Andrews" -> "Stephen Weber"
    - First name only -> full name: "Stephen" -> "Stephen Weber"
    - Word-boundary matching to avoid partial replacements

    Returns updated text, or None if no change was needed.
    """
    if not text or not old_name or not new_name:
        return None
    if old_name == new_name:
        return None

    # Try full name replacement first
    pattern_full = re.compile(r"\b" + re.escape(old_name) + r"\b", re.IGNORECASE)
    if pattern_full.search(text):
        result = pattern_full.sub(new_name, text)
        if result != text:
            return result

    # Try first-name-only replacement if full name didn't match
    old_first = old_name.split()[0] if " " in old_name else old_name
    new_first = new_name.split()[0] if " " in new_name else new_name

    if old_first.lower() == new_first.lower():
        # Same first name, different last name (e.g., both "Stephen")
        # Use the full old name match which already failed above
        # Try replacing standalone first name with new full name
        return replace_confirmed_name(text, new_name, [old_name])
    else:
        # Different first names entirely
        pattern_first = re.compile(r"\b" + re.escape(old_first) + r"\b", re.IGNORECASE)
        if pattern_first.search(text):
            result = pattern_first.sub(new_name, text)
            if result != text:
                return result

    return None
