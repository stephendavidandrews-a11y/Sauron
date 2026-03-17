"""Tests for embedder connection management (Phase 5C)."""

import inspect


def test_embed_conversation_uses_get_db():
    """embed_conversation() must use get_db context manager."""
    from sauron.embeddings import embedder

    source = inspect.getsource(embedder.embed_conversation)
    assert "get_db()" in source, "embed_conversation should use get_db() context manager"
    assert "get_connection()" not in source, "embed_conversation should not use raw get_connection()"


def test_embed_inner_receives_connection():
    """_embed_conversation_inner should accept conn and conversation_id params."""
    from sauron.embeddings.embedder import _embed_conversation_inner

    sig = inspect.signature(_embed_conversation_inner)
    params = list(sig.parameters.keys())
    assert "conn" in params
    assert "conversation_id" in params
