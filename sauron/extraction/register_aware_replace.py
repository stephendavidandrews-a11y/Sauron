"""Register-aware name replacement for contact rename cascades.

When a contact is renamed (e.g., Whisper mishearing corrected), this module
determines the appropriate replacement text based on the register of the
original reference:
  - Last-name reference ("Wieden") -> replace with new last name ("Wyden")
  - First-name reference ("Ryan") -> replace with full new name ("Ryan Ibarra")
  - Full-name reference ("Ron Wieden") -> replace with full new name ("Ron Wyden")
"""

import re
import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

try:
    import jellyfish
    HAS_JELLYFISH = True
except ImportError:
    HAS_JELLYFISH = False
    logger.warning("jellyfish not installed; fuzzy matching will use Levenshtein only")


class Register(str, Enum):
    FULL = "full"
    LAST_ONLY = "last_only"
    FIRST_ONLY = "first_only"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    SKIPPED = "skipped"


@dataclass
class Match:
    start: int
    end: int
    matched_text: str
    register: Register
    is_fuzzy: bool = False


@dataclass
class Change:
    original: str
    replacement: str
    register: Register
    position: int
    confidence: Confidence = Confidence.HIGH


# Common English words that are also names -- get MEDIUM confidence
COMMON_NAME_WORDS = frozenset({
    "park", "lee", "rice", "bell", "young", "long", "white", "black",
    "green", "brown", "king", "hill", "wood", "day", "ford", "lane",
    "field", "chase", "banks", "stone", "reed", "page", "cash", "cole",
    "dean", "duke", "grant", "hall", "hayes", "hunt", "mark", "marsh",
    "may", "miles", "price", "ray", "rose", "short", "sharp", "wade",
    "ward", "wells", "barr", "booth", "cross", "love", "little", "noble",
    "rush", "gold", "sage", "baker", "cook", "farmer", "mason", "potter",
    "summer", "winter", "spring", "grace", "hope", "joy", "faith",
})


def _levenshtein_ratio(s1: str, s2: str) -> float:
    """Simple Levenshtein similarity ratio."""
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    max_len = max(len(s1), len(s2))
    if max_len == 0:
        return 1.0
    if HAS_JELLYFISH:
        dist = jellyfish.levenshtein_distance(s1, s2)
    else:
        dist = _simple_levenshtein(s1, s2)
    return 1.0 - (dist / max_len)


def _simple_levenshtein(s1: str, s2: str) -> int:
    """Basic Levenshtein distance."""
    if len(s1) < len(s2):
        return _simple_levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (0 if c1 == c2 else 1)))
        prev = curr
    return prev[-1]


def is_fuzzy_match(candidate: str, target: str, threshold: float = 0.80) -> bool:
    """Check if candidate is a phonetic/spelling match for target."""
    c = candidate.strip().lower()
    t = target.strip().lower()
    if not c or not t:
        return False
    if c == t:
        return True
    if HAS_JELLYFISH:
        try:
            m_c = jellyfish.metaphone(c)
            m_t = jellyfish.metaphone(t)
            if m_c and m_t and m_c == m_t:
                return True
        except Exception:
            pass
        try:
            jw = jellyfish.jaro_winkler_similarity(c, t)
            if jw >= 0.85:
                return True
        except Exception:
            pass
    ratio = _levenshtein_ratio(c, t)
    return ratio >= threshold


def _split_name(name: str):
    """Split name into (first, last). Returns (None, None) for empty."""
    parts = name.strip().split()
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None  # mononym
    return parts[0], parts[-1]


def _word_boundary_findall(pattern: str, text: str):
    """Find all word-boundary matches of pattern in text."""
    regex = re.compile(r"\b(" + re.escape(pattern) + r")(\b)", re.IGNORECASE)
    return [(m.start(1), m.end(1), m.group(1)) for m in regex.finditer(text)]


def _fuzzy_token_scan(target: str, text: str, threshold: float = 0.80):
    """Scan text tokens for fuzzy matches to target."""
    results = []
    for m in re.finditer(r"\b(\w+)\b", text):
        token = m.group(1)
        if len(token) < 3:
            continue
        if is_fuzzy_match(token, target, threshold) and token.lower() != target.lower():
            results.append((m.start(), m.end(), token))
    return results


def detect_register(text: str, old_name: str):
    """Find all occurrences of old_name parts in text, classifying by register.

    Returns list of Match objects sorted reverse by position for safe replacement.
    """
    if not text or not old_name:
        return []
    old_first, old_last = _split_name(old_name)
    old_parts = old_name.strip().split()
    matches = []
    used_ranges = set()

    def overlaps(start, end):
        for (s, e) in used_ranges:
            if start < e and end > s:
                return True
        return False

    # 1. Full name match (highest priority)
    if len(old_parts) >= 2:
        for start, end, matched in _word_boundary_findall(old_name.strip(), text):
            if not overlaps(start, end):
                matches.append(Match(start, end, matched, Register.FULL, is_fuzzy=False))
                used_ranges.add((start, end))

    # 2. Last-name match
    if old_last:
        for start, end, matched in _word_boundary_findall(old_last, text):
            if not overlaps(start, end):
                matches.append(Match(start, end, matched, Register.LAST_ONLY, is_fuzzy=False))
                used_ranges.add((start, end))
        for start, end, matched in _fuzzy_token_scan(old_last, text):
            if not overlaps(start, end):
                matches.append(Match(start, end, matched, Register.LAST_ONLY, is_fuzzy=True))
                used_ranges.add((start, end))

    # 3. First-name match (only if different from last)
    if old_first and old_first.lower() != (old_last or "").lower():
        for start, end, matched in _word_boundary_findall(old_first, text):
            if not overlaps(start, end):
                matches.append(Match(start, end, matched, Register.FIRST_ONLY, is_fuzzy=False))
                used_ranges.add((start, end))
        for start, end, matched in _fuzzy_token_scan(old_first, text):
            if not overlaps(start, end):
                matches.append(Match(start, end, matched, Register.FIRST_ONLY, is_fuzzy=True))
                used_ranges.add((start, end))

    # 4. Mononym: reclassify first-name matches as FULL
    if len(old_parts) == 1 and old_first and not old_last:
        for m in matches:
            if m.register == Register.FIRST_ONLY:
                m.register = Register.FULL

    matches.sort(key=lambda m: m.start, reverse=True)
    return matches


def compute_replacement(match: Match, new_name: str, old_name: str = "") -> str:
    """Determine replacement text based on register.

    Special case: if old_name is a mononym (single word, likely a surname),
    FULL register uses just the new surname, not the full new name.
    E.g., "Wieden" -> "Wyden", not "Ron Wyden".
    """
    _, new_last = _split_name(new_name)
    old_parts = old_name.strip().split() if old_name else []
    is_mononym = len(old_parts) == 1

    if match.register == Register.FULL:
        if is_mononym and new_last:
            return new_last  # mononym = surname reference -> use new surname
        return new_name.strip()
    elif match.register == Register.LAST_ONLY:
        return new_last if new_last else new_name.strip()
    elif match.register == Register.FIRST_ONLY:
        return new_name.strip()  # disambiguate with full name
    return new_name.strip()


def classify_confidence(match: Match, is_entity_field: bool = False) -> Confidence:
    """Assign confidence tier to a match."""
    if is_entity_field:
        return Confidence.HIGH
    if match.matched_text.lower() in COMMON_NAME_WORDS:
        return Confidence.MEDIUM
    if match.is_fuzzy:
        return Confidence.MEDIUM
    return Confidence.HIGH


def register_aware_replace(text, old_name, new_name, is_entity_field=False):
    """Replace all occurrences of old_name in text with register-appropriate new_name.

    Args:
        text: The text to process.
        old_name: The old/incorrect name to find.
        new_name: The new/correct name.
        is_entity_field: If True, always use full new_name.

    Returns:
        (new_text, list_of_changes). If no changes, returns (text, []).
    """
    if not text or not old_name or not new_name:
        return text, []
    if old_name.strip().lower() == new_name.strip().lower():
        return text, []

    # Entity fields: simple full-name replacement for wholesale match only
    if is_entity_field:
        old_clean = old_name.strip()
        new_clean = new_name.strip()
        # Wholesale match: entire field IS the old name -> use full new name
        if text.strip().lower() == old_clean.lower():
            return new_clean, [Change(text.strip(), new_clean, Register.FULL, 0, Confidence.HIGH)]
        # Partial match in entity field: fall through to register-aware
        # replacement so "Wieden-Durbin Bill" -> "Wyden-Durbin Bill"
        # (not "Ron Wyden-Durbin Bill")

    # Free-text: register-aware replacement
    matches = detect_register(text, old_name)
    if not matches:
        return text, []

    changes = []
    result = text
    for match in matches:  # already reverse-sorted
        replacement = compute_replacement(match, new_name, old_name)
        confidence = classify_confidence(match)
        # Preserve case pattern
        if match.matched_text.isupper():
            replacement = replacement.upper()
        elif match.matched_text[0].isupper():
            replacement = replacement[0].upper() + replacement[1:]
        changes.append(Change(match.matched_text, replacement, match.register, match.start, confidence))
        result = result[:match.start] + replacement + result[match.end:]

    if result == text:
        return text, []
    return result, changes
