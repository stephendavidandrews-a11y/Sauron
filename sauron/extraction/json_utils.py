"""Robust JSON extraction from LLM responses.

LLMs sometimes wrap JSON in prose preamble, markdown fences, or
trailing commentary. This module handles all those cases.
"""


def extract_json(raw_text: str) -> str:
    """Extract JSON object from LLM response text.

    Handles:
    - Pure JSON responses
    - Markdown code fences (```json ... ```)
    - Prose preamble before JSON
    - Trailing commentary after JSON
    """
    raw_text = raw_text.strip()

    # Try markdown code fence first
    if "```" in raw_text:
        parts = raw_text.split("```")
        for part in parts[1:]:
            stripped = part.strip()
            if stripped.startswith("json"):
                return stripped[4:].strip()
            elif stripped.startswith("{"):
                return stripped

    # If it already starts with {, just return it
    if raw_text.startswith("{"):
        # But trim anything after the last }
        end = raw_text.rfind("}")
        if end != -1:
            return raw_text[:end + 1]
        return raw_text

    # Find first { and last } - model added prose preamble
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw_text[start:end + 1]

    # Give up and return as-is (will fail at validation)
    return raw_text
