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

"""notebook-render: serves agent-generated, fully baked UQ notebook reports.

``GET /render/{artifact_id}`` returns a self-contained static HTML report. The
producing agent writes ``uq_<model>_<timestamp>.ipynb`` and a sibling ``.html``
(nbconvert, images embedded, figures baked) into ``NOTEBOOK_DIR``. We return the
HTML bytes as-is: no live kernel, no WebSocket, so the inline view renders on load
and cannot come up blank. The artifact id is opaque, so its filename is read from
the platform artifact registry (Valkey), read-only.

Everything is env-driven; no host is hard-coded. The browser only sees
same-origin ``/notebook/...`` paths. The frontend forwards them with the
``/notebook`` prefix intact, so each route is registered in both forms.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

# --- Configuration (all overridable) ---------------------------------------

NOTEBOOK_DIR = Path(os.environ.get("NOTEBOOK_DIR", "/app/shared/uq-notebooks"))
# Platform artifact registry (Valkey). An agent registers each generated notebook
# as an ``ArtifactReference`` under ``artifacts:conv:{conversation_id}:by_id`` (a
# Redis hash: field = artifact_id, value = JSON with the real ``name``/``uri``). We
# read it to map an opaque artifact_id to its on-disk filename. Read-only.
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD") or None
_REGISTRY_KEY_PATTERN = "artifacts:conv:*:by_id"


# --- Artifact registry lookup (Valkey) --------------------------------------


def _registry_basename(artifact_id: str) -> str | None:
    """Look up ``artifact_id`` in the Valkey artifact registry and return the
    stored file's basename (e.g. ``uq_linear_bank_worth_20260903T062558Z.ipynb``),
    or ``None`` if the registry is unreachable or the id is not found.

    The registry is conversation-scoped — records live under
    ``artifacts:conv:{conversation_id}:by_id`` and the caller only has the
    artifact_id, so we scan those hashes (there are few, one per conversation)
    for the field. We read the record's ``name`` (falling back to the basename
    of its ``uri``) and return only the basename; path assembly + the traversal
    guard happen in ``_resolve_under_dir``. Any failure returns ``None`` so the
    caller can fall back to the ``{artifact_id}.{suffix}`` scheme.
    """
    aid = Path(str(artifact_id)).name  # traversal guard on the lookup key too
    try:
        import redis  # local import: optional dep, keeps import-time failures contained

        client = redis.Redis.from_url(REDIS_URL, password=REDIS_PASSWORD, decode_responses=True, socket_timeout=3)
        for key in client.scan_iter(match=_REGISTRY_KEY_PATTERN, count=100):
            raw = client.hget(key, aid)
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except (ValueError, TypeError):
                return None
            name = rec.get("name")
            if not name:
                uri = rec.get("uri") or ""
                name = Path(urlsplit(uri).path).name or None
            return Path(str(name)).name if name else None
    except Exception:
        return None
    return None


# --- Notebook / HTML path resolution ----------------------------------------


def _artifact_stem(artifact_id: str) -> str:
    """Basename of ``artifact_id`` with any ``.ipynb``/``.html`` suffix stripped."""
    name = Path(artifact_id).name  # strip any path components (traversal guard)
    for suffix in (".ipynb", ".html"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name


def _resolve_under_dir(name: str) -> Path:
    """Resolve ``name`` under NOTEBOOK_DIR, guarding against path traversal."""
    candidate = (NOTEBOOK_DIR / name).resolve()
    root = NOTEBOOK_DIR.resolve()
    if root not in candidate.parents and candidate.parent != root:
        raise ValueError("resolved path escapes NOTEBOOK_DIR")
    return candidate


def _resolve_with_suffix(artifact_id: str, suffix: str) -> Path:
    """Resolve the on-disk file for ``artifact_id`` with the given ``suffix``
    (``.ipynb`` / ``.html``) under NOTEBOOK_DIR.

    Preferred path: consult the Valkey artifact registry for the real filename
    (``uq_{model}_{timestamp}.ipynb``) and swap its suffix — the artifact_id is
    an opaque UUID with no relationship to the filename, so this is the only
    reliable mapping. Fallback: the legacy ``{artifact_id}{suffix}`` scheme,
    used when the registry is unreachable or the id predates registration (and
    by the unit tests, whose fixtures are named by id).
    """
    basename = _registry_basename(artifact_id)
    if basename:
        stem = basename
        for known in (".ipynb", ".html"):
            if stem.endswith(known):
                stem = stem[: -len(known)]
                break
        return _resolve_under_dir(f"{stem}{suffix}")
    return _resolve_under_dir(f"{_artifact_stem(artifact_id)}{suffix}")


def _notebook_path(artifact_id: str) -> Path:
    """Resolve the .ipynb for ``artifact_id`` under NOTEBOOK_DIR (registry-first)."""
    return _resolve_with_suffix(artifact_id, ".ipynb")


def _html_path(artifact_id: str) -> Path:
    """Resolve the baked .html for ``artifact_id`` under NOTEBOOK_DIR (registry-first)."""
    return _resolve_with_suffix(artifact_id, ".html")


# --- /render (static baked HTML) --------------------------------------------


async def render(request: Request) -> Response:
    """GET /render/{artifact_id} -> the baked static HTML report.

    The agent bakes the ``.html`` beside the notebook; we serve it as plain bytes.
    The figures are already in the file, so the page renders on load.
    """
    artifact_id = request.path_params["artifact_id"]
    try:
        html_path = _html_path(artifact_id)
    except ValueError:
        return JSONResponse({"ok": False, "error": "bad artifact id"}, status_code=400)
    if not html_path.exists():
        # A notebook may exist without its baked HTML (e.g. an nbconvert failure at
        # generation time). Report that distinctly so it's diagnosable.
        try:
            nb_exists = _notebook_path(artifact_id).exists()
        except ValueError:
            nb_exists = False
        detail = (
            "baked HTML missing (notebook exists but was not exported to HTML)" if nb_exists else "report not found"
        )
        return JSONResponse({"ok": False, "error": detail}, status_code=404)
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


async def health(_request: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "service": "notebook-render", "mode": "static-html"})


# --- App --------------------------------------------------------------------

# Routes are registered bare (direct access: dev, tests) and under ``/notebook``
# (through the frontend proxy, which keeps the prefix).
routes = [
    Route("/health", health, methods=["GET"]),
    Route("/notebook/health", health, methods=["GET"]),
    Route("/render/{artifact_id}", render, methods=["GET"]),
    Route("/notebook/render/{artifact_id}", render, methods=["GET"]),
]

app = Starlette(routes=routes)
