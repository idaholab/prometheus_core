"""GET /healthz (liveness, dependency-free) and GET /readyz (readiness, checks Valkey + admin-db)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.routers import health as health_mod


class _DownRedis:
    async def ping(self) -> None:
        raise ConnectionError("valkey is down")


class _HungRedis:
    async def ping(self) -> None:
        await asyncio.sleep(60)


@pytest.fixture
def sqlite_admin_db(monkeypatch):
    """Point the readiness probe's own session at an in-memory SQLite engine."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(health_mod, "get_session_factory", lambda: async_sessionmaker(engine))
    return engine


def test_readyz_ok_when_valkey_and_admin_db_up(sqlite_admin_db):
    from app.main import app

    resp = TestClient(app).get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "checks": {"valkey": "ok", "admin_db": "ok"}}


def test_readyz_503_when_valkey_down_but_healthz_still_200(sqlite_admin_db):
    from app.main import app

    original = app.state.redis
    app.state.redis = _DownRedis()
    try:
        client = TestClient(app)
        ready = client.get("/readyz")
        live = client.get("/healthz")
    finally:
        app.state.redis = original

    assert ready.status_code == 503
    assert ready.json() == {"status": "unavailable", "checks": {"valkey": "fail", "admin_db": "ok"}}
    assert live.status_code == 200
    assert live.json() == {"status": "ok"}


def test_readyz_503_when_admin_db_down(monkeypatch):
    from app.main import app

    def _broken_factory():
        raise ConnectionError("admin-db is down")

    monkeypatch.setattr(health_mod, "get_session_factory", _broken_factory)
    client = TestClient(app)
    resp = client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["checks"] == {"valkey": "ok", "admin_db": "fail"}
    assert client.get("/healthz").status_code == 200


def test_readyz_503_when_valkey_hangs(sqlite_admin_db, monkeypatch):
    from app.main import app

    monkeypatch.setattr(health_mod, "READINESS_CHECK_TIMEOUT_S", 0.05)
    original = app.state.redis
    app.state.redis = _HungRedis()
    try:
        resp = TestClient(app).get("/readyz")
    finally:
        app.state.redis = original
    assert resp.status_code == 503
    assert resp.json()["checks"]["valkey"] == "fail"
