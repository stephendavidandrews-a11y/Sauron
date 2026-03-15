"""Conversational alias learning.

When any entity resolution confirms a name → contact mapping, the resolved
name is added as an alias to unified_contacts.aliases so future lookups
resolve instantly via Strategy 3 (direct alias match).

Called from:
  - synthesis_linker.py  (auto-synthesis resolution)
  - entity_resolver.py   (pipeline entity resolution)
  - corrections.py       (user manual entity linking)
  - conversations.py     (bulk reassign)

See: docs/specs/entity_resolution_review_plan.md, Phase 2.
"""

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)


def _normalize_quotes(s: str) -> str:
    """Normalize smart/curly quotes to straight quotes for comparison."""
    return (
        s.replace("\u201c", '"')   # left double smart quote
        .replace("\u201d", '"')    # right double smart quote
        .replace("\u2018", "'")    # left single smart quote
        .replace("\u2019", "'")    # right single smart quote
        .replace("\u00ab", '"')    # left guillemet
        .replace("\u00bb", '"')    # right guillemet
    )


# ═══════════════════════════════════════════════════════════════
# Title abbreviation/expansion lookup (bidirectional)
# ═══════════════════════════════════════════════════════════════

TITLE_MAP = {
    "senator": "Sen.",
    "sen.": "Senator",
    "commissioner": "Comm.",
    "comm.": "Commissioner",
    "representative": "Rep.",
    "rep.": "Representative",
    "secretary": "Sec.",
    "sec.": "Secretary",
    "professor": "Prof.",
    "prof.": "Professor",
    "doctor": "Dr.",
    "dr.": "Doctor",
}

# ═══════════════════════════════════════════════════════════════
# Skip patterns
# ═══════════════════════════════════════════════════════════════

_BARE_TITLE_RE = re.compile(
    r"^(the|a|an|my|his|her|their|stephen'?s?)\s+\w+$",
    re.IGNORECASE,
)

_RELATIONAL_RE = re.compile(
    r"^(my|his|her|their|stephen'?s?)\s+"
    r"(brother|sister|wife|husband|spouse|partner|"
    r"mom|mother|dad|father|son|daughter|boss|assistant|colleague|friend|"
    r"uncle|aunt|cousin|nephew|niece|grandfather|grandmother|grandpa|grandma|"
    r"fianc[eé]e?|roommate|mentor|intern)$",
    re.IGNORECASE,
)


# ═══════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════

def learn_alias(conn, entity_id: str, resolved_name: str, canonical_name: str) -> bool:
    """Add resolved_name as an alias to unified_contacts if it passes filtering rules.

    Args:
        conn: SQLite connection (caller manages transaction).
        entity_id: The unified_contacts.id of the resolved contact.
        resolved_name: The name that was matched (e.g., "Senator Hawley").
        canonical_name: The contact's canonical_name (e.g., "Josh Hawley").

    Returns:
        True if one or more aliases were added, False if all were skipped/dupes.
    """
    if not resolved_name or not canonical_name or not entity_id:
        return False

    resolved_clean = resolved_name.strip()
    canonical_clean = canonical_name.strip()

    # ── Skip rule: same as canonical name (normalize quotes for comparison) ──
    if _normalize_quotes(resolved_clean).lower() == _normalize_quotes(canonical_clean).lower():
        return False

    # ── Skip rule: alias is another contact's canonical name ──
    # Prevents cross-contamination (e.g., "Will Simpson" as alias for "Daniel Park")
    other = conn.execute(
        "SELECT id FROM unified_contacts "
        "WHERE LOWER(TRIM(canonical_name)) = ? AND id != ? LIMIT 1",
        (_normalize_quotes(resolved_clean).lower(), entity_id),
    ).fetchone()
    if other:
        logger.debug(
            f"Alias skip (other contact's canonical name): '{resolved_clean}' "
            f"belongs to {other['id'][:8]}, not adding to {canonical_clean}"
        )
        return False

    # ── Skip rule: bare title / possessive reference ──
    if _BARE_TITLE_RE.match(resolved_clean):
        logger.debug(f"Alias skip (bare title): '{resolved_clean}'")
        return False

    # ── Skip rule: relational reference ──
    if _RELATIONAL_RE.match(resolved_clean):
        logger.debug(f"Alias skip (relational): '{resolved_clean}'")
        return False

    words = resolved_clean.split()

    # ── Skip rule: bare first name ──
    # Single word that matches the first name of the canonical name
    if len(words) == 1:
        canonical_first = canonical_clean.split()[0].lower()
        if words[0].lower() == canonical_first:
            logger.debug(f"Alias skip (bare first name): '{resolved_clean}'")
            return False

    # ── Build candidate aliases ──
    candidates = [resolved_clean]

    # Generate title variants for multi-word names
    if len(words) >= 2:
        variants = _generate_title_variants(resolved_clean)
        candidates.extend(variants)

    # ── Read current aliases ──
    row = conn.execute(
        "SELECT aliases FROM unified_contacts WHERE id = ?",
        (entity_id,),
    ).fetchone()

    if not row:
        logger.warning(f"Alias learn: entity {entity_id[:8]} not found in unified_contacts")
        return False

    current_aliases_raw = row["aliases"] or ""
    # Parse existing aliases — handle both semicolon and comma separators
    if ";" in current_aliases_raw:
        current_set = set(a.strip() for a in current_aliases_raw.split(";") if a.strip())
    elif "," in current_aliases_raw:
        current_set = set(a.strip() for a in current_aliases_raw.split(",") if a.strip())
    elif current_aliases_raw.strip():
        current_set = {current_aliases_raw.strip()}
    else:
        current_set = set()

    # Case-insensitive dedup: build a lowercase set for comparison (normalize quotes)
    current_lower = {_normalize_quotes(a).lower() for a in current_set}
    # Also skip if candidate matches canonical name (case-insensitive)
    current_lower.add(_normalize_quotes(canonical_clean).lower())

    # ── Filter candidates against existing ──
    new_aliases = []
    for candidate in candidates:
        if _normalize_quotes(candidate.strip()).lower() not in current_lower:
            new_aliases.append(candidate.strip())

    if not new_aliases:
        return False

    # ── Merge and write ──
    merged = current_set | set(new_aliases)
    alias_str = "; ".join(sorted(merged))

    conn.execute(
        "UPDATE unified_contacts SET aliases = ? WHERE id = ?",
        (alias_str, entity_id),
    )

    logger.info(
        f"Alias learned for '{canonical_clean}': "
        f"{', '.join(new_aliases)} (total aliases: {len(merged)})"
    )
    return True


# ═══════════════════════════════════════════════════════════════
# Title variant generation
# ═══════════════════════════════════════════════════════════════

def _generate_title_variants(name: str) -> list[str]:
    """Generate abbreviated/expanded title variants of a name.

    Examples:
        "Senator Hawley"  → ["Sen. Hawley"]
        "Sen. Hawley"     → ["Senator Hawley"]
        "Dr. Smith"       → ["Doctor Smith"]
        "Professor Jones" → ["Prof. Jones"]
        "John Smith"      → []  (no title, no variants)
    """
    words = name.strip().split()
    if len(words) < 2:
        return []

    first_word = words[0]
    rest = " ".join(words[1:])

    # Check if the first word is a known title (case-insensitive)
    key = first_word.lower().rstrip(".")

    # Try with and without trailing period
    variant_title = TITLE_MAP.get(first_word.lower())
    if variant_title is None:
        # Try with period added (e.g., "Sen" → lookup "sen.")
        variant_title = TITLE_MAP.get(first_word.lower() + ".")

    if variant_title:
        return [f"{variant_title} {rest}"]

    return []


# ═══════════════════════════════════════════════════════════════
# Entity alias learning (for unified_entities — orgs, legislation, topics)
# ═══════════════════════════════════════════════════════════════

def learn_entity_alias(conn, entity_id: str, resolved_name: str, canonical_name: str) -> bool:
    """Add resolved_name as alias to unified_entities. Mirrors learn_alias() for contacts.

    Simpler than person alias learning:
    - No bare-title or relational-reference skips (not relevant for objects)
    - No bare-first-name skip (not relevant for objects)
    - Generates abbreviation variants for organizations

    Args:
        conn: SQLite connection (caller manages transaction).
        entity_id: The unified_entities.id.
        resolved_name: The name that was matched (e.g., "CFTC").
        canonical_name: The entity's canonical_name (e.g., "Commodity Futures Trading Commission").

    Returns:
        True if one or more aliases were added, False if all were skipped/dupes.
    """
    if not resolved_name or not canonical_name or not entity_id:
        return False

    resolved_clean = resolved_name.strip()
    canonical_clean = canonical_name.strip()

    # Skip: same as canonical name
    if _normalize_quotes(resolved_clean).lower() == _normalize_quotes(canonical_clean).lower():
        return False

    # Skip: alias is another entity's canonical name
    other = conn.execute(
        "SELECT id FROM unified_entities "
        "WHERE LOWER(TRIM(canonical_name)) = ? AND id != ? LIMIT 1",
        (_normalize_quotes(resolved_clean).lower(), entity_id),
    ).fetchone()
    if other:
        logger.debug(
            f"Entity alias skip (other entity's canonical name): '{resolved_clean}' "
            f"belongs to {other['id'][:8]}, not adding to {canonical_clean}"
        )
        return False

    # Build candidates
    candidates = [resolved_clean]

    # Read current aliases
    row = conn.execute(
        "SELECT aliases FROM unified_entities WHERE id = ?",
        (entity_id,),
    ).fetchone()

    if not row:
        logger.warning(f"Entity alias learn: entity {entity_id[:8]} not found")
        return False

    current_aliases_raw = row["aliases"] or ""
    if ";" in current_aliases_raw:
        current_set = set(a.strip() for a in current_aliases_raw.split(";") if a.strip())
    elif current_aliases_raw.strip():
        current_set = {current_aliases_raw.strip()}
    else:
        current_set = set()

    current_lower = {_normalize_quotes(a).lower() for a in current_set}
    current_lower.add(_normalize_quotes(canonical_clean).lower())

    # Filter candidates
    new_aliases = []
    for candidate in candidates:
        if _normalize_quotes(candidate.strip()).lower() not in current_lower:
            new_aliases.append(candidate.strip())

    if not new_aliases:
        return False

    # Merge and write
    merged = current_set | set(new_aliases)
    alias_str = "; ".join(sorted(merged))

    conn.execute(
        "UPDATE unified_entities SET aliases = ? WHERE id = ?",
        (alias_str, entity_id),
    )

    logger.info(
        f"Entity alias learned for '{canonical_clean}': "
        f"{', '.join(new_aliases)} (total aliases: {len(merged)})"
    )
    return True
