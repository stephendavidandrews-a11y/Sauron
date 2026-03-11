"""Vocal baseline management — EMA tracking and deviation detection.

Re-exports from analyzer for backwards compatibility.
Additional baseline-specific utilities live here.
"""

from sauron.vocal.analyzer import update_baseline, compare_to_baseline

__all__ = ["update_baseline", "compare_to_baseline"]
