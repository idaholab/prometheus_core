# This file is part of Prometheus
# https://inl.gov/super-intelligence/prometheus/
#
# Copyright 2026 Battelle Energy Alliance, LLC
# All rights reserved, see NOTICE.txt for full restrictions
# https://github.com/idaholab/prometheus_core/blob/main/NOTICE.txt
#
# Licensed under the MIT License, please see LICENSE for details
# https://github.com/idaholab/prometheus_core/blob/main/LICENSE
#
# SPDX-License-Identifier: MIT

"""Stack test: the running backend serves an RS256 signing key with no admin action.

Talks to the already-running Compose stack through the backend's published
host port (``BACKEND_PORT``, default 8600). It never starts or stops a
container, so it does not use the ``docker_compose_up`` fixture.
"""

import os
from pathlib import Path

import httpx
import pytest


pytestmark = pytest.mark.integration


def _backend_port(project_root: Path) -> str:
    """Return BACKEND_PORT from the process environment, then platform/.env, else 8600."""
    port = (os.getenv("BACKEND_PORT") or "").strip()
    if port:
        return port
    env_path = project_root / ".env"
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == "BACKEND_PORT" and value.strip():
                return value.strip()
    return "8600"


@pytest.fixture
def stack_backend_url(project_root: Path) -> str:
    """Return the running stack's backend URL, or skip when the backend does not answer."""
    url = f"http://localhost:{_backend_port(project_root)}"
    try:
        httpx.get(f"{url}/healthz", timeout=5, follow_redirects=True)
    except httpx.HTTPError as exc:
        pytest.skip(f"Backend stack is not reachable at {url}: {type(exc).__name__}")
    return url


def test_fresh_stack_serves_a_signing_key(stack_backend_url):
    """GET /.well-known/jwks.json lists at least one RS256 signing key with a kid."""
    resp = httpx.get(f"{stack_backend_url}/.well-known/jwks.json", timeout=15)
    assert resp.status_code == 200, f"JWKS returned {resp.status_code}: {resp.text}"

    keys = resp.json().get("keys")
    assert isinstance(keys, list), f"JWKS body has no 'keys' list: {resp.text}"
    signing_keys = [k for k in keys if k.get("alg") == "RS256" and k.get("use") == "sig" and k.get("kid")]
    assert signing_keys, f"JWKS serves no RS256 signing key with a kid: {keys}"
