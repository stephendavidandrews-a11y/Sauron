"""Tests for morning_email connection management and safety (Phase 5C)."""

import inspect


def test_generate_morning_brief_uses_get_db():
    """generate_morning_brief() must use get_db context manager, not raw get_connection."""
    from sauron.jobs import morning_email

    source = inspect.getsource(morning_email.generate_morning_brief)
    assert "get_db()" in source, "generate_morning_brief should use get_db() context manager"
    assert "get_connection()" not in source, "generate_morning_brief should not use raw get_connection()"


def test_inner_brief_receives_connection():
    """_generate_morning_brief_inner should accept a conn parameter."""
    from sauron.jobs.morning_email import _generate_morning_brief_inner

    sig = inspect.signature(_generate_morning_brief_inner)
    params = list(sig.parameters.keys())
    assert "conn" in params, "_generate_morning_brief_inner must accept a conn parameter"


def test_no_utcnow_in_morning_email():
    """morning_email.py should not use deprecated datetime.utcnow()."""
    from sauron.jobs import morning_email

    source = inspect.getsource(morning_email)
    assert "utcnow()" not in source, "morning_email still uses deprecated utcnow()"
