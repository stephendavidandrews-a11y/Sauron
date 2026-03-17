"""Tests for Phase 4 fixes: model singleton, upsert safety, no utcnow (Phase 5C)."""

import inspect
import importlib


def test_no_utcnow_anywhere():
    """No module should use deprecated datetime.utcnow()."""
    modules = [
        "sauron.routing.networking",
        "sauron.routing.routing_log",
        "sauron.routing.retry",
        "sauron.api.pipeline_api",
        "sauron.api.provisional_orgs_api",
        "sauron.api.graph_edges_api",
        "sauron.jobs.intentions",
        "sauron.jobs.morning_email",
        "sauron.learning.amendments",
    ]
    for mod_name in modules:
        mod = importlib.import_module(mod_name)
        source = inspect.getsource(mod)
        assert "utcnow()" not in source, f"{mod_name} still uses deprecated utcnow()"


def test_dedup_uses_embedder_singleton():
    """dedup.py should reuse embedder._get_model(), not instantiate its own SentenceTransformer."""
    mod = importlib.import_module("sauron.extraction.dedup")
    source = inspect.getsource(mod)
    assert "SentenceTransformer(" not in source, "dedup.py should not instantiate SentenceTransformer directly"
    assert "_get_model" in source, "dedup.py should use _get_model() from embedder"


def test_text_pipeline_uses_on_conflict():
    """text_pipeline.py should use ON CONFLICT, not INSERT OR REPLACE for conversations/extractions."""
    mod = importlib.import_module("sauron.text.text_pipeline")
    source = inspect.getsource(mod)
    lines = source.split("\n")
    for i, line in enumerate(lines):
        if "INSERT OR REPLACE" in line:
            context = "\n".join(lines[max(0,i-2):i+3])
            assert "conversations" not in context.lower(), f"Line {i}: INSERT OR REPLACE still used for conversations"
            assert "extractions" not in context.lower(), f"Line {i}: INSERT OR REPLACE still used for extractions"


def test_deep_extraction_uses_str_conversation_id():
    """deep.py should use str | None for conversation_id, not int | None."""
    mod = importlib.import_module("sauron.extraction.deep")
    source = inspect.getsource(mod)
    assert "conversation_id: int" not in source, "deep.py still uses int for conversation_id"
