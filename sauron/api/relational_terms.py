"""Shared relational terms module — single source of truth.

Used by corrections.py, graph.py, and entity_resolver.py.
Accepts any user-typed term as valid (not just hardcoded ones).
"""

import logging
from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)

# Expanded default relational terms (~80 terms)
RELATIONAL_TERMS = {
    # Family - immediate
    "brother", "sister", "wife", "husband", "spouse", "partner",
    "mom", "mother", "dad", "father", "son", "daughter",
    "child", "kid", "baby",
    # Family - extended
    "uncle", "aunt", "cousin", "nephew", "niece",
    "grandfather", "grandmother", "grandpa", "grandma",
    "grandson", "granddaughter", "grandchild",
    "stepbrother", "stepsister", "stepmother", "stepfather",
    "stepmom", "stepdad", "stepson", "stepdaughter",
    "half-brother", "half-sister",
    "brother-in-law", "sister-in-law", "mother-in-law", "father-in-law",
    "son-in-law", "daughter-in-law",
    "godfather", "godmother", "godson", "goddaughter",
    # Family - engagement/dating
    "fiancé", "fiancée", "fiance", "fiancee",
    "boyfriend", "girlfriend", "ex", "ex-wife", "ex-husband",
    # Family - descriptive
    "birth mother", "birth father", "biological mother", "biological father",
    "adoptive mother", "adoptive father",
    # Professional
    "boss", "manager", "supervisor", "director",
    "colleague", "coworker", "co-worker",
    "assistant", "secretary", "intern", "mentee",
    "mentor", "advisor", "adviser",
    "employee", "subordinate", "direct report",
    "business partner", "co-founder", "founder",
    # Social
    "friend", "best friend", "roommate", "housemate",
    "neighbor", "neighbour",
    # Professional services
    "doctor", "therapist", "counselor", "psychiatrist",
    "lawyer", "attorney", "accountant", "financial advisor",
    "dentist", "trainer", "coach", "tutor", "teacher", "professor",
    "pastor", "priest", "rabbi",
    "nanny", "babysitter", "caregiver",
    # Other
    "acquaintance", "contact", "client", "patient",
    "landlord", "tenant",
}

# Plural forms
PLURAL_TERMS = {
    "brothers", "sisters", "sons", "daughters",
    "children", "kids", "babies",
    "cousins", "nephews", "nieces",
    "grandchildren", "grandsons", "granddaughters",
    "colleagues", "coworkers", "friends", "neighbors", "neighbours",
    "employees", "clients", "patients",
    "stepbrothers", "stepsisters", "stepsons", "stepdaughters",
}

# Combined set for quick lookup
ALL_TERMS = RELATIONAL_TERMS | PLURAL_TERMS


def is_relational_term(term: str, check_db: bool = True) -> bool:
    """Check if a term is a recognized relational term.

    Checks: default set, plural set, and optionally learned terms from DB.
    """
    term_lower = term.lower().strip()
    if term_lower in ALL_TERMS:
        return True

    if check_db:
        try:
            conn = get_connection()
            try:
                # Check if this term has been used before in learned_relationships
                row = conn.execute(
                    """SELECT COUNT(*) as c FROM unified_contacts
                       WHERE relationships LIKE ?""",
                    (f'%"{term_lower}"%',),
                ).fetchone()
                if row and row["c"] > 0:
                    return True
            finally:
                conn.close()
        except Exception:
            pass

    return False


def get_all_terms(include_db: bool = True) -> set:
    """Get all known relational terms (defaults + learned from DB)."""
    terms = set(ALL_TERMS)

    if include_db:
        try:
            conn = get_connection()
            try:
                rows = conn.execute(
                    """SELECT DISTINCT relationships FROM unified_contacts
                       WHERE relationships IS NOT NULL AND relationships != '{}'"""
                ).fetchall()
                import json
                for row in rows:
                    try:
                        rels = json.loads(row["relationships"])
                        # learned_relationships list
                        for lr in rels.get("learned_relationships", []):
                            rel = lr.get("relationship", "").lower().strip()
                            if rel:
                                terms.add(rel)
                        # Direct keys that look like relationship terms
                        for key in rels:
                            key_lower = key.lower().strip()
                            if key_lower not in ("learned_relationships", "tags",
                                                "personalring", "personalgroup",
                                                "howwemet", "partnername",
                                                "partner_name", "personal_ring",
                                                "personal_group", "how_we_met",
                                                "relation_to_stephen", "relationship"):
                                # This might be a custom relationship term
                                pass
                    except (json.JSONDecodeError, TypeError):
                        pass
            finally:
                conn.close()
        except Exception:
            pass

    return terms
