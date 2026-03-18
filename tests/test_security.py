"""Test sauron/security.py -- API key auth, exception handler, logging middleware."""

import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sauron.security import require_api_key, global_exception_handler, RequestLoggingMiddleware


@pytest.fixture
def secured_app():
    """Create a FastAPI app with security dependencies."""
    from fastapi import Depends

    app = FastAPI()
    app.add_exception_handler(Exception, global_exception_handler)
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/protected")
    async def protected(key=Depends(require_api_key)):
        return {"data": "secret"}

    @app.get("/api/error")
    async def error_route(key=Depends(require_api_key)):
        raise RuntimeError("boom")

    @app.get("/static/app.js")
    async def static_file():
        return {"js": True}

    return app


@pytest.fixture
def client(secured_app):
    return TestClient(secured_app, raise_server_exceptions=False)


# -- API key validation --


def test_health_endpoint_skips_auth(client, monkeypatch):
    """Health endpoint is public, no API key needed."""
    monkeypatch.setenv("SAURON_API_KEY", "test-key-123")
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_protected_endpoint_rejects_no_key(client, monkeypatch):
    """Protected endpoint returns 401 without API key."""
    monkeypatch.setenv("SAURON_API_KEY", "test-key-123")
    resp = client.get("/api/protected")
    assert resp.status_code == 401


def test_protected_endpoint_rejects_wrong_key(client, monkeypatch):
    """Protected endpoint returns 401 with wrong API key."""
    monkeypatch.setenv("SAURON_API_KEY", "correct-key")
    resp = client.get("/api/protected", headers={"X-API-Key": "wrong-key"})
    assert resp.status_code == 401


def test_protected_endpoint_accepts_correct_key(client, monkeypatch):
    """Protected endpoint returns 200 with correct API key."""
    monkeypatch.setenv("SAURON_API_KEY", "correct-key")
    resp = client.get("/api/protected", headers={"X-API-Key": "correct-key"})
    assert resp.status_code == 200
    assert resp.json()["data"] == "secret"


def test_missing_api_key_env_returns_503(client, monkeypatch):
    """When SAURON_API_KEY is not set, returns 503 Service Misconfigured."""
    monkeypatch.delenv("SAURON_API_KEY", raising=False)
    resp = client.get("/api/protected", headers={"X-API-Key": "anything"})
    assert resp.status_code == 503


# -- Global exception handler --


def test_global_exception_handler_returns_500(client, monkeypatch):
    """Unhandled exceptions return 500 with generic message."""
    monkeypatch.setenv("SAURON_API_KEY", "key")
    resp = client.get("/api/error", headers={"X-API-Key": "key"})
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Internal server error"


# -- Non-API paths skip auth --


def test_non_api_paths_skip_auth(client, monkeypatch):
    """Static file paths are not subject to API key auth."""
    monkeypatch.setenv("SAURON_API_KEY", "key")
    resp = client.get("/static/app.js")
    assert resp.status_code == 200
