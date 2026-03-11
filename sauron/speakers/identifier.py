"""Speaker identification — high-level functions for the pipeline."""

from sauron.speakers.resolver import resolve_speakers
from sauron.speakers.profiles import enroll_speaker, add_sample, list_profiles

__all__ = ["resolve_speakers", "enroll_speaker", "add_sample", "list_profiles"]
