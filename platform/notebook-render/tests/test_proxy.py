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

"""Unit tests for the notebook-render service.

Its live surface is ``GET /render/{artifact_id}`` -> the baked static HTML
report. The ``/rerun`` endpoint is dormant (no caller today; kept for a future
JSX interactivity layer), but its security model still holds and is tested:

1. ``GET /render/{name}`` returns the baked ``{name}.html`` bytes when present,
   and a distinct 404 when the notebook exists without its baked HTML.
2. ``AGENT_SECRET`` (the sentinel from conftest) NEVER appears in a ``/rerun``
   response body. The proxy injects it as a server-side Bearer and must return
   only the UQ result.
3. ``RERUN_ROUTE`` selects the upstream: ``direct`` -> the UQ agent, and
   ``client-agent`` -> the orchestrator. The whitelisted params are forwarded;
   anything else is dropped.

Plus a regression test for ``extract_uq_result`` against the real notebook
shape (a ``uq_result = {...}`` cell with a trailing non-JSON ``.keys()`` line,
which ``json.loads`` cannot parse but ``raw_decode`` can).
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("starlette")
from starlette.testclient import TestClient  # noqa: E402

import proxy  # noqa: E402

SENTINEL = "sentinel-secret-do-not-leak"


@pytest.fixture
def client():
    return TestClient(proxy.app)


def _full_uq_result():
    return {
        "toy_model_id": "linear_bank_worth",
        "num_samples": 2,
        "metrics": {"bank_worth": {"mean": 1.0, "std": 0.1}},
        "samples": [
            {"params": {"BANK_A_POS": 0.1}, "outputs": {"bank_worth": 0.9}},
            {"params": {"BANK_A_POS": 0.5}, "outputs": {"bank_worth": 1.1}},
        ],
    }


def test_auth_header_carries_the_secret_but_response_does_not(client, monkeypatch):
    """The Bearer is sent upstream; the sentinel must not appear in the response."""
    assert SENTINEL in proxy._auth_headers()["Authorization"]

    async def _fake_direct(payload):
        # /api/chat returns a trimmed summary (no samples) + a notebook_uri.
        return {"ok": True, "result": {"toy_model_id": "linear_bank_worth", "num_samples": 2}}

    monkeypatch.setattr(proxy, "RERUN_ROUTE", "direct")
    monkeypatch.setattr(proxy, "_call_direct", _fake_direct)
    # No notebook on disk -> proxy returns the trimmed summary as-is; that's fine
    # for the leak assertion.

    resp = client.post("/rerun", json={"num_samples": 2, "toy_model_id": "linear_bank_worth"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert SENTINEL not in resp.text
    assert "Authorization" not in resp.text
    assert "Bearer" not in resp.text


def test_rerun_route_direct_calls_uq_agent(client, monkeypatch):
    seen = {}

    async def _fake_direct(payload):
        seen["route"] = "direct"
        seen["payload"] = payload
        return {"result": _full_uq_result()}

    async def _fake_client_agent(payload):
        seen["route"] = "client-agent"
        return {"result": _full_uq_result()}

    monkeypatch.setattr(proxy, "RERUN_ROUTE", "direct")
    monkeypatch.setattr(proxy, "_call_direct", _fake_direct)
    monkeypatch.setattr(proxy, "_call_client_agent", _fake_client_agent)

    resp = client.post(
        "/rerun",
        json={"num_samples": 5, "toy_model_id": "quadratic_reactivity", "bogus": "dropped"},
    )
    assert resp.status_code == 200
    assert seen["route"] == "direct"
    # Whitelisted params forwarded; the unknown key is dropped.
    assert seen["payload"] == {"num_samples": 5, "toy_model_id": "quadratic_reactivity"}
    assert "bogus" not in seen["payload"]


def test_rerun_unwraps_nested_params_envelope(client, monkeypatch):
    """The notebook widget posts the /api/chat shape ``{"params": {...}}``.

    The proxy must unwrap it, drop the widget's own ``skill_id`` (the upstream
    helper injects the canonical one), and forward the whitelisted params.
    """
    seen = {}

    async def _fake_direct(payload):
        seen["payload"] = payload
        return {"result": _full_uq_result()}

    monkeypatch.setattr(proxy, "RERUN_ROUTE", "direct")
    monkeypatch.setattr(proxy, "_call_direct", _fake_direct)

    resp = client.post(
        "/rerun",
        json={
            "params": {
                "skill_id": "forward_sampling_uq",
                "mode": "toy_polynomial",
                "toy_model_id": "linear_bank_worth",
                "num_samples": 7,
                "parameters": [{"name": "BANK_A_POS", "distribution": "uniform", "min": 0.0, "max": 1.0}],
            },
            "include_artifacts": False,
        },
    )
    assert resp.status_code == 200
    assert seen["payload"] == {
        "num_samples": 7,
        "toy_model_id": "linear_bank_worth",
        "parameters": [{"name": "BANK_A_POS", "distribution": "uniform", "min": 0.0, "max": 1.0}],
        "mode": "toy_polynomial",
    }
    # The widget's skill_id is not forwarded verbatim; the helper injects it.
    assert "skill_id" not in seen["payload"]


def test_rerun_route_client_agent_calls_orchestrator(client, monkeypatch):
    seen = {}

    async def _fake_direct(payload):
        seen["route"] = "direct"
        return {"result": _full_uq_result()}

    async def _fake_client_agent(payload):
        seen["route"] = "client-agent"
        return {"result": _full_uq_result()}

    monkeypatch.setattr(proxy, "RERUN_ROUTE", "client-agent")
    monkeypatch.setattr(proxy, "_call_direct", _fake_direct)
    monkeypatch.setattr(proxy, "_call_client_agent", _fake_client_agent)

    resp = client.post("/rerun", json={"num_samples": 3, "toy_model_id": "linear_bank_worth"})
    assert resp.status_code == 200
    assert seen["route"] == "client-agent"
    assert resp.json()["result"]["samples"]


def test_rerun_recovers_full_samples_from_notebook(client, monkeypatch, tmp_path):
    """When /api/chat returns only a summary + notebook_uri, the proxy reopens the
    notebook and returns the full per-sample result."""
    nb_dir = tmp_path / "uq-notebooks"
    nb_dir.mkdir()
    nb_name = "UI-uq_linear.ipynb"
    # Notebook data cell as the agent writes it: assignment + trailing .keys().
    data_src = "uq_result = " + json.dumps(_full_uq_result(), indent=2) + "\nuq_result.keys()\n"
    nb = {"cells": [{"cell_type": "code", "source": data_src.splitlines(keepends=True)}]}
    (nb_dir / nb_name).write_text(json.dumps(nb))

    monkeypatch.setattr(proxy, "NOTEBOOK_DIR", nb_dir)

    async def _fake_direct(payload):
        # Summary omits samples but points at the freshly written notebook.
        return {"result": {"toy_model_id": "linear_bank_worth", "notebook_uri": f"file://{nb_dir / nb_name}"}}

    monkeypatch.setattr(proxy, "RERUN_ROUTE", "direct")
    monkeypatch.setattr(proxy, "_call_direct", _fake_direct)

    resp = client.post("/rerun", json={"num_samples": 2, "toy_model_id": "linear_bank_worth"})
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert len(result["samples"]) == 2
    assert result["samples"][0]["outputs"]["bank_worth"] == 0.9


def test_extract_uq_result_handles_trailing_non_json(tmp_path):
    nb_name = "x.ipynb"
    data_src = "uq_result = " + json.dumps(_full_uq_result()) + "\nuq_result.keys()\n"
    nb = {"cells": [{"cell_type": "markdown", "source": ["# hi"]}, {"cell_type": "code", "source": [data_src]}]}
    path = tmp_path / nb_name
    path.write_text(json.dumps(nb))

    got = proxy.extract_uq_result(path)
    assert got is not None
    assert got["num_samples"] == 2
    assert len(got["samples"]) == 2


def test_extract_uq_result_returns_none_without_samples(tmp_path):
    # A cell that mentions uq_result but has no samples key must not match.
    nb = {"cells": [{"cell_type": "code", "source": ['uq_result = {"metrics": {}}\n']}]}
    path = tmp_path / "y.ipynb"
    path.write_text(json.dumps(nb))
    assert proxy.extract_uq_result(path) is None


def test_notebook_path_neutralizes_traversal(monkeypatch, tmp_path):
    monkeypatch.setattr(proxy, "NOTEBOOK_DIR", tmp_path)
    # Traversal components are stripped to a basename under NOTEBOOK_DIR.
    resolved = proxy._notebook_path("../../etc/passwd")
    assert resolved.parent == tmp_path.resolve()
    assert resolved.name == "passwd.ipynb"
    assert str(resolved).startswith(str(tmp_path.resolve()))


def test_registry_lookup_maps_opaque_id_to_real_filename(client, monkeypatch, tmp_path):
    """When the artifact_id is registered, /render resolves the REAL on-disk
    filename (uq_{model}_{timestamp}.html) via the registry, not {id}.html."""
    nb_dir = tmp_path / "uq-artifacts"
    nb_dir.mkdir()
    real_name = "uq_linear_bank_worth_20260903T062558Z.ipynb"
    (nb_dir / "uq_linear_bank_worth_20260903T062558Z.html").write_text(
        "<html><body>registry-resolved report</body></html>", encoding="utf-8"
    )
    monkeypatch.setattr(proxy, "NOTEBOOK_DIR", nb_dir)
    # Stand in for the Valkey lookup: opaque UUID -> the record's stored name.
    monkeypatch.setattr(
        proxy,
        "_registry_basename",
        lambda aid: real_name if aid == "92ec0e09-53ab-422a-9e31-e2726ae85e9a" else None,
    )

    resp = client.get("/render/92ec0e09-53ab-422a-9e31-e2726ae85e9a")
    assert resp.status_code == 200
    assert "registry-resolved report" in resp.text


def test_registry_miss_falls_back_to_id_named_file(client, monkeypatch, tmp_path):
    """With no registry hit (unreachable Valkey or unregistered id), the legacy
    {artifact_id}.html scheme still resolves — keeps old artifacts + tests working."""
    nb_dir = tmp_path / "uq-artifacts"
    nb_dir.mkdir()
    (nb_dir / "legacy-id.html").write_text("<html><body>fallback</body></html>", encoding="utf-8")
    monkeypatch.setattr(proxy, "NOTEBOOK_DIR", nb_dir)
    monkeypatch.setattr(proxy, "_registry_basename", lambda aid: None)

    resp = client.get("/render/legacy-id.ipynb")
    assert resp.status_code == 200
    assert "fallback" in resp.text


def test_registry_basename_returns_none_when_redis_unreachable(monkeypatch):
    """A dead/absent Valkey must degrade to None (never raise), so the caller
    falls back to the id-named scheme rather than 500-ing."""
    monkeypatch.setattr(proxy, "REDIS_URL", "redis://127.0.0.1:6390")  # nothing listening
    assert proxy._registry_basename("any-id") is None


def test_rerun_rejects_non_object_body(client):
    resp = client.post("/rerun", json=["not", "an", "object"])
    assert resp.status_code == 400
    assert SENTINEL not in resp.text


def test_health_reports_route(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["service"] == "notebook-render"


def test_render_serves_baked_html(client, monkeypatch, tmp_path):
    """GET /render/{name} returns the baked {name}.html bytes as-is."""
    nb_dir = tmp_path / "uq-notebooks"
    nb_dir.mkdir()
    html = "<!DOCTYPE html><html><body><div>baked plot</div></body></html>"
    (nb_dir / "UI-uq_linear.html").write_text(html, encoding="utf-8")
    monkeypatch.setattr(proxy, "NOTEBOOK_DIR", nb_dir)

    # The plugin passes the .ipynb basename; the proxy maps it to the .html sibling.
    resp = client.get("/render/UI-uq_linear.ipynb")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "baked plot" in resp.text


def test_render_served_under_notebook_prefix(client, monkeypatch, tmp_path):
    """The frontend mount forwards WITH the /notebook prefix intact (it does not
    strip it), so the prefixed route must resolve to the same handler."""
    nb_dir = tmp_path / "uq-notebooks"
    nb_dir.mkdir()
    (nb_dir / "UI-uq_linear.html").write_text("<html><body>baked plot</body></html>", encoding="utf-8")
    monkeypatch.setattr(proxy, "NOTEBOOK_DIR", nb_dir)

    # This is the exact path the frontend Chainlit mount forwards.
    resp = client.get("/notebook/render/UI-uq_linear.ipynb")
    assert resp.status_code == 200
    assert "baked plot" in resp.text


def test_render_404_distinguishes_missing_html_from_missing_report(client, monkeypatch, tmp_path):
    """A notebook present without its baked HTML reports a distinct 404 detail."""
    nb_dir = tmp_path / "uq-notebooks"
    nb_dir.mkdir()
    # Notebook exists, HTML does not (e.g. an nbconvert failure at generation time).
    (nb_dir / "half.ipynb").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(proxy, "NOTEBOOK_DIR", nb_dir)

    resp = client.get("/render/half.ipynb")
    assert resp.status_code == 404
    assert "baked HTML missing" in resp.json()["error"]

    # Neither file present -> plain not-found.
    resp = client.get("/render/nope.ipynb")
    assert resp.status_code == 404
    assert resp.json()["error"] == "report not found"


def test_render_neutralizes_traversal(client, monkeypatch, tmp_path):
    """A traversal artifact id resolves to a basename under NOTEBOOK_DIR."""
    nb_dir = tmp_path / "uq-notebooks"
    nb_dir.mkdir()
    monkeypatch.setattr(proxy, "NOTEBOOK_DIR", nb_dir)
    # ../../etc/passwd -> passwd.html under NOTEBOOK_DIR; absent -> 404, never a leak.
    resp = client.get("/render/..%2F..%2Fetc%2Fpasswd")
    assert resp.status_code == 404


def test_result_returns_full_uq_result(client, monkeypatch, tmp_path):
    """GET /result/{name} returns the full uq_result (with samples) from the notebook."""
    nb_dir = tmp_path / "uq-notebooks"
    nb_dir.mkdir()
    nb_name = "UI-uq_linear.ipynb"
    data_src = "uq_result = " + json.dumps(_full_uq_result(), indent=2) + "\nuq_result.keys()\n"
    nb = {"cells": [{"cell_type": "code", "source": data_src.splitlines(keepends=True)}]}
    (nb_dir / nb_name).write_text(json.dumps(nb))
    monkeypatch.setattr(proxy, "NOTEBOOK_DIR", nb_dir)

    resp = client.get("/result/UI-uq_linear.ipynb")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["result"]["samples"]) == 2
    assert body["result"]["samples"][0]["outputs"]["bank_worth"] == 0.9


def test_result_served_under_notebook_prefix(client, monkeypatch, tmp_path):
    """The frontend mount forwards WITH the /notebook prefix intact."""
    nb_dir = tmp_path / "uq-notebooks"
    nb_dir.mkdir()
    nb_name = "UI-uq_linear.ipynb"
    data_src = "uq_result = " + json.dumps(_full_uq_result()) + "\nuq_result.keys()\n"
    nb = {"cells": [{"cell_type": "code", "source": [data_src]}]}
    (nb_dir / nb_name).write_text(json.dumps(nb))
    monkeypatch.setattr(proxy, "NOTEBOOK_DIR", nb_dir)

    resp = client.get("/notebook/result/UI-uq_linear.ipynb")
    assert resp.status_code == 200
    assert resp.json()["result"]["num_samples"] == 2


def test_result_404_when_no_uq_result(client, monkeypatch, tmp_path):
    """A notebook without a samples-bearing uq_result cell reports 404, not a crash."""
    nb_dir = tmp_path / "uq-notebooks"
    nb_dir.mkdir()
    # Notebook exists but has no uq_result with samples.
    (nb_dir / "plain.ipynb").write_text(json.dumps({"cells": []}))
    monkeypatch.setattr(proxy, "NOTEBOOK_DIR", nb_dir)

    resp = client.get("/result/plain.ipynb")
    assert resp.status_code == 404
    assert "no uq_result" in resp.json()["error"]

    # Missing notebook entirely -> distinct 404.
    resp = client.get("/result/nope.ipynb")
    assert resp.status_code == 404
    assert resp.json()["error"] == "notebook not found"


def test_result_neutralizes_traversal(client, monkeypatch, tmp_path):
    """A traversal artifact id resolves to a basename under NOTEBOOK_DIR; absent -> 404."""
    nb_dir = tmp_path / "uq-notebooks"
    nb_dir.mkdir()
    monkeypatch.setattr(proxy, "NOTEBOOK_DIR", nb_dir)
    resp = client.get("/result/..%2F..%2Fetc%2Fpasswd")
    assert resp.status_code == 404
    assert SENTINEL not in resp.text
