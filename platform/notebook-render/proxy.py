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

"""notebook-render — static baked-HTML server + dormant secret-safe re-run proxy.

Two responsibilities, one origin:

1.  ``GET /render/{artifact_id}`` serves a self-contained, fully-baked static
    HTML report. The UQ agent writes ``{artifact_id}.ipynb`` **and** a sibling
    ``{artifact_id}.html`` (nbconvert HTMLExporter, images embedded, Plotly
    figures as CDN-backed ``<div>``s) into ``NOTEBOOK_DIR``. We return the HTML
    bytes directly: no Voila, no live kernel, no WebSocket. Because every figure
    is already baked into the file, the inline view renders on load and can never
    come up blank on a kernel starve.

2.  ``POST /rerun`` is a **dormant** structured re-invocation endpoint. Nothing
    calls it today — the notebook is a static report with no in-page widgets — but
    it is kept in place for a future frontend (JSX) interactivity layer to drive.
    It injects the ``AGENT_SECRET`` Bearer *here*, server-side, so the secret
    never reaches the browser, POSTs the UQ agent's flat ``/api/chat`` structured
    route (or the client-agent orchestrator when ``RERUN_ROUTE=client-agent``),
    then — because ``/api/chat`` returns a *trimmed* summary with no per-sample
    ``samples`` — opens the freshly written notebook and extracts the full
    ``uq_result`` (with samples) baked into its data cell, returning
    ``{"result": <full uq_result>}``. See
    ``docs/docs/dev-docs/rerun-invocation-path.md`` for the route decision.

Everything is env-driven; no host is hard-coded. The browser only ever sees
same-origin paths relative to Chainlit's origin (``/notebook/...``), so there is
no CORS or mixed-content concern under TLS. The frontend mount forwards those
paths WITH the ``/notebook`` prefix intact (it does not strip it), so every route
below is registered in both the bare and ``/notebook``-prefixed form.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

# --- Configuration (all overridable) ---------------------------------------

NOTEBOOK_DIR = Path(os.environ.get("NOTEBOOK_DIR", "/app/shared/uq-notebooks"))
UQ_AGENT_URL = os.environ.get("UQ_AGENT_URL", "http://multiphysics-uq-agent:8000").rstrip("/")
# Platform artifact registry (Valkey). The UQ agent registers each generated
# notebook as an ``ArtifactReference`` under ``artifacts:conv:{conversation_id}:by_id``
# (a Redis hash: field = artifact_id, value = JSON with the real ``name``/``uri``).
# We read it here — same store the agents write to — to map an opaque artifact_id
# to its on-disk filename (``uq_{model}_{timestamp}.ipynb``), because that filename
# has no relationship to the id. Read-only; no write path.
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD") or None
_REGISTRY_KEY_PATTERN = "artifacts:conv:*:by_id"
CLIENT_AGENT_URL = os.environ.get("CLIENT_AGENT_URL", "http://client-agent:8000").rstrip("/")
# Dormant /rerun route selector (no caller today; kept for a future JSX layer).
# "direct" (default) -> POST the UQ agent's /api/chat, which IS the structured skill
# entry point: it accepts {skill_id, parameters, num_samples, ...} and returns the full
# uq_result. "client-agent" -> POST the client-agent /api/chat instead; NOTE that endpoint
# is the NL *planner* (it wants a `query` string, not structured params) and will NOT run
# forward_sampling_uq from a params dict today. See
# docs/docs/dev-docs/rerun-invocation-path.md for why direct is the default and the options
# to revisit with the platform designer.
RERUN_ROUTE = os.environ.get("RERUN_ROUTE", "direct").strip().lower()
AGENT_SECRET = os.environ.get("AGENT_SECRET", "")
# Skill the UQ agent dispatches on; snake_case as the flat /api/chat route expects.
RERUN_SKILL_ID = os.environ.get("RERUN_SKILL_ID", "forward_sampling_uq")

_UPSTREAM_TIMEOUT = float(os.environ.get("RERUN_TIMEOUT_SECONDS", "900"))


def _auth_headers() -> dict[str, str]:
    """Server-side Bearer. Always sent (per platform decision), even if empty,
    so the agent build that requires auth is satisfied regardless of
    AGENT_SECRET_REQUIRED. Never echoed back to the caller."""
    return {"Authorization": f"Bearer {AGENT_SECRET}"}


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
    caller can fall back to the legacy ``{artifact_id}.{suffix}`` scheme (this
    keeps the unit tests, which write ``{id}.html`` fixtures, green).
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


# --- Notebook sample extraction (kept for the dormant /rerun path) ----------


def extract_uq_result(notebook_path: Path) -> dict[str, Any] | None:
    """Pull the full baked ``uq_result`` (with per-sample ``samples``) out of a
    generated notebook's data cell.

    ``/api/chat`` returns a trimmed summary with no ``samples``; the agent bakes
    the full result into a code cell as ``uq_result = {...}`` (followed by
    trailing non-JSON like ``uq_result.keys()``), so plain ``json.loads`` throws
    "Extra data". ``raw_decode`` reads exactly one JSON object off the front.
    """
    try:
        nb = json.loads(notebook_path.read_text())
    except Exception:
        return None
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        src = "".join(cell.get("source", []))
        marker = "uq_result"
        if marker not in src or "=" not in src:
            continue
        after_eq = src[src.index(marker) :].split("=", 1)[1].strip()
        try:
            obj, _ = json.JSONDecoder().raw_decode(after_eq)
        except Exception:
            continue
        if isinstance(obj, dict) and "samples" in obj:
            return obj
    return None


# --- /render (static baked HTML) --------------------------------------------


async def render(request: Request) -> Response:
    """GET /render/{artifact_id} -> the baked static HTML report.

    The UQ agent bakes ``{artifact_id}.html`` beside the notebook; we serve it as
    plain bytes. No kernel, no Voila, no WebSocket — the figures are already in
    the file, so the page renders on load and cannot go blank.
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


# --- /result (full uq_result JSON for the interactive dashboard) ------------


async def result(request: Request) -> JSONResponse:
    """GET /result/{artifact_id} -> the full baked ``uq_result`` as JSON.

    The interactive UQ dashboard element fetches this same-origin to obtain the
    complete result (``parameters`` + per-sample ``samples`` + ``metrics``) that
    is embedded ONLY in the generated notebook, never on the A2A wire (the inline
    ``uq_summary`` is trimmed). We reuse the notebook path resolver and the same
    ``extract_uq_result`` used by ``/rerun``. No secret is involved: this reads a
    trusted, agent-generated notebook already sitting in ``NOTEBOOK_DIR``.
    """
    artifact_id = request.path_params["artifact_id"]
    try:
        nb_path = _notebook_path(artifact_id)
    except ValueError:
        return JSONResponse({"ok": False, "error": "bad artifact id"}, status_code=400)
    if not nb_path.exists():
        return JSONResponse({"ok": False, "error": "notebook not found"}, status_code=404)
    data = extract_uq_result(nb_path)
    if data is None:
        return JSONResponse({"ok": False, "error": "no uq_result in notebook"}, status_code=404)
    return JSONResponse({"ok": True, "result": data})


# --- /rerun (dormant; kept for a future JSX interactivity layer) ------------


async def _call_direct(payload: dict[str, Any]) -> dict[str, Any]:
    """POST the UQ agent's flat /api/chat with the re-run params."""
    body = {
        "params": {"skill_id": RERUN_SKILL_ID, **payload},
        "include_artifacts": False,
    }
    async with httpx.AsyncClient(timeout=_UPSTREAM_TIMEOUT) as client:
        resp = await client.post(f"{UQ_AGENT_URL}/api/chat", json=body, headers=_auth_headers())
        resp.raise_for_status()
        return resp.json()


async def _call_client_agent(payload: dict[str, Any]) -> dict[str, Any]:
    """Route the re-run through the client-agent orchestrator's /api/chat."""
    body = {
        "params": {"skill_id": RERUN_SKILL_ID, **payload},
        "include_artifacts": False,
    }
    async with httpx.AsyncClient(timeout=_UPSTREAM_TIMEOUT) as client:
        resp = await client.post(f"{CLIENT_AGENT_URL}/api/chat", json=body, headers=_auth_headers())
        resp.raise_for_status()
        return resp.json()


async def rerun(request: Request) -> JSONResponse:
    """Dormant structured re-invocation. Body: {num_samples, toy_model_id, parameters?, mode?}.

    No caller today (the report is static). Kept so a future frontend interactivity
    layer can re-invoke the skill without a secret ever reaching the browser.
    Returns {"result": <full uq_result with samples>}.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid JSON body"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "body must be an object"}, status_code=400)

    # Accept either the UQ agent's /api/chat shape ``{"params": {...}, ...}`` or a
    # flat ``{num_samples, toy_model_id, ...}`` body. Forward only a whitelisted set;
    # the upstream helpers re-wrap and inject the skill_id + Bearer server-side, so
    # any ``skill_id`` in the body is ignored.
    source = body.get("params") if isinstance(body.get("params"), dict) else body

    payload: dict[str, Any] = {}
    for key in ("num_samples", "toy_model_id", "parameters", "mode", "metrics_to_collect"):
        if source.get(key) is not None:
            payload[key] = source[key]

    try:
        if RERUN_ROUTE == "client-agent":
            chat = await _call_client_agent(payload)
        else:
            chat = await _call_direct(payload)
    except httpx.HTTPError as exc:
        return JSONResponse({"ok": False, "error": f"upstream call failed: {exc}"}, status_code=502)

    summary = chat.get("result") if isinstance(chat, dict) else None
    if not isinstance(summary, dict):
        return JSONResponse({"ok": False, "error": "upstream returned no result"}, status_code=502)

    # /api/chat strips per-sample data; recover it from the freshly written notebook.
    result: dict[str, Any] = summary
    notebook_uri = summary.get("notebook_uri")
    if isinstance(notebook_uri, str) and notebook_uri:
        nb_name = Path(urlsplit(notebook_uri).path).name
        try:
            full = extract_uq_result(_notebook_path(nb_name))
        except ValueError:
            full = None
        if full is not None:
            result = full

    # Never leak the Bearer or upstream envelope; return only the UQ result.
    return JSONResponse({"ok": True, "result": result})


async def health(_request: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "service": "notebook-render", "mode": "static-html", "rerun_route": RERUN_ROUTE})


# --- App --------------------------------------------------------------------

# The frontend mounts this app at ``/notebook`` on Chainlit's ASGI app, but that
# Mount does NOT strip the mount prefix before forwarding (Chainlit inserts the
# route ahead of its SPA catch-all rather than via a prefix-stripping sub-app), so
# requests arrive here as ``/notebook/render/{id}`` and ``/notebook/rerun`` -- not
# ``/render/{id}``. We therefore register BOTH the bare and the ``/notebook``-prefixed
# forms, so the service works whether it is reached directly (dev, tests) or through
# the frontend mount.
routes = [
    Route("/health", health, methods=["GET"]),
    Route("/notebook/health", health, methods=["GET"]),
    Route("/render/{artifact_id}", render, methods=["GET"]),
    Route("/notebook/render/{artifact_id}", render, methods=["GET"]),
    # Full uq_result JSON (parameters + samples + metrics) for the interactive dashboard.
    Route("/result/{artifact_id}", result, methods=["GET"]),
    Route("/notebook/result/{artifact_id}", result, methods=["GET"]),
    # Dormant; no caller today. Kept for a future JSX interactivity layer.
    Route("/rerun", rerun, methods=["POST"]),
    Route("/notebook/rerun", rerun, methods=["POST"]),
]

app = Starlette(routes=routes)
