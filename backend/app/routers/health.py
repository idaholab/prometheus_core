"""Operational probes (not part of the public API; deliberately absent from CONTRACT.md).

``/healthz`` is liveness and must stay dependency-free: if it checked Valkey or admin-db,
a datastore blip would make Kubernetes restart every backend pod, which is worse than the
blip. ``/readyz`` is readiness: it checks the dependencies a request needs, so a pod is
only sent traffic once it can serve it. Neither is proxied by nginx (only ``/api/`` is).
"""

import asyncio
import logging
from typing import Awaitable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db import get_session_factory
from app.redis_client import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

# Short enough that a hung dependency fails the probe well inside the kubelet's own
# probe timeout, rather than stacking up requests behind it.
READINESS_CHECK_TIMEOUT_S = 2.0


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


async def _check(name: str, probe: Awaitable[object]) -> bool:
    try:
        await asyncio.wait_for(probe, timeout=READINESS_CHECK_TIMEOUT_S)
    except Exception:  # noqa: BLE001 - any failure, including timeout, means "not ready"
        logger.warning("readiness check failed: %s", name, exc_info=True)
        return False
    return True


async def _ping_admin_db() -> None:
    # Own short-lived session rather than the get_db_session dependency: that one commits
    # on exit, and a commit on a connection that just failed would raise after the 503
    # was already decided.
    async with get_session_factory()() as session:
        await session.execute(text("SELECT 1"))


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    valkey_ok, admin_db_ok = await asyncio.gather(
        _check("valkey", get_redis(request).ping()),
        _check("admin-db", _ping_admin_db()),
    )
    checks = {"valkey": "ok" if valkey_ok else "fail", "admin_db": "ok" if admin_db_ok else "fail"}
    ready = valkey_ok and admin_db_ok
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ok" if ready else "unavailable", "checks": checks},
    )
