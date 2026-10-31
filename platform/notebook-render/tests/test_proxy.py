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

``GET /render/{artifact_id}`` returns the baked ``.html`` report when present,
a distinct 404 when the notebook exists without its baked HTML, and never a
file outside ``NOTEBOOK_DIR``. The opaque artifact id is mapped to its filename
through the artifact registry, falling back to an id-named file.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("starlette")
from starlette.testclient import TestClient  # noqa: E402

import proxy  # noqa: E402


@pytest.fixture
def client():
    return TestClient(proxy.app)


def test_notebook_path_neutralizes_traversal(monkeypatch, tmp_path):
    """A traversal attempt collapses to the basename inside NOTEBOOK_DIR."""
    monkeypatch.setattr(proxy, "NOTEBOOK_DIR", tmp_path)
    monkeypatch.setattr(proxy, "_registry_basename", lambda aid: None)  # no Valkey in unit tests
    assert proxy._notebook_path("../../etc/passwd") == (tmp_path / "passwd.ipynb").resolve()
    assert proxy._notebook_path("uq_x.ipynb") == (tmp_path / "uq_x.ipynb").resolve()


class _FakeRedis:
    """Minimal stand-in for the Valkey artifact registry (conversation-scoped hashes)."""

    def __init__(self, hashes):
        self._hashes = hashes  # {key: {field: json_str}}

    def scan_iter(self, match=None, count=None):
        return iter(self._hashes.keys())

    def hget(self, key, field):
        return self._hashes.get(key, {}).get(field)


def test_registry_lookup_maps_opaque_id_to_real_filename(client, monkeypatch, tmp_path):
    """The real filename (uq_{model}_{ts}) has no relation to the artifact_id; the
    registry record's ``name`` bridges them."""
    real_stem = "uq_linear_bank_worth_20260903T062558Z"
    (tmp_path / f"{real_stem}.ipynb").write_text("{}")
    (tmp_path / f"{real_stem}.html").write_text("<html><body>REAL REPORT</body></html>")
    monkeypatch.setattr(proxy, "NOTEBOOK_DIR", tmp_path)
    aid = "0f4b8c1e-1234-4abc-9def-000000000000"
    record = json.dumps({"artifact_id": aid, "name": f"{real_stem}.ipynb", "uri": "file:///elsewhere/x.ipynb"})
    fake = _FakeRedis({"artifacts:conv:c1:by_id": {aid: record}})
    import redis as redis_mod

    monkeypatch.setattr(redis_mod.Redis, "from_url", staticmethod(lambda *a, **k: fake))

    assert proxy._registry_basename(aid) == f"{real_stem}.ipynb"
    assert proxy._html_path(aid) == (tmp_path / f"{real_stem}.html").resolve()
    resp = client.get(f"/render/{aid}")
    assert resp.status_code == 200
    assert "REAL REPORT" in resp.text


def test_registry_miss_falls_back_to_id_named_file(client, monkeypatch, tmp_path):
    """No registry record: resolve as {artifact_id}{suffix}."""
    (tmp_path / "UI-uq_fallback.html").write_text("<html>FALLBACK</html>")
    monkeypatch.setattr(proxy, "NOTEBOOK_DIR", tmp_path)
    import redis as redis_mod

    monkeypatch.setattr(redis_mod.Redis, "from_url", staticmethod(lambda *a, **k: _FakeRedis({})))
    assert proxy._registry_basename("UI-uq_fallback") is None
    resp = client.get("/render/UI-uq_fallback")
    assert resp.status_code == 200
    assert "FALLBACK" in resp.text


def test_registry_basename_returns_none_when_redis_unreachable(monkeypatch):
    """Unreachable Valkey: _registry_basename swallows the error and returns None."""
    monkeypatch.setattr(proxy, "REDIS_URL", "redis://127.0.0.1:1")  # nothing listens here
    assert proxy._registry_basename("anything") is None


def test_health_reports_static_html(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "service": "notebook-render", "mode": "static-html"}


def test_render_serves_baked_html(client, monkeypatch, tmp_path):
    """GET /render/{name} returns the baked {name}.html bytes verbatim."""
    nb_name = "UI-uq_linear.ipynb"
    (tmp_path / nb_name).write_text("{}")
    baked = "<!DOCTYPE html><html><body><div class='plotly-graph-div'>FIG</div></body></html>"
    (tmp_path / "UI-uq_linear.html").write_text(baked)
    monkeypatch.setattr(proxy, "NOTEBOOK_DIR", tmp_path)
    monkeypatch.setattr(proxy, "_registry_basename", lambda aid: None)  # id-named fixtures

    resp = client.get(f"/render/{nb_name}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert resp.text == baked


def test_render_served_under_notebook_prefix(client, monkeypatch, tmp_path):
    """The frontend forwards /notebook/render/{id} with the prefix intact; it must resolve."""
    (tmp_path / "UI-uq_p.html").write_text("<html>OK</html>")
    monkeypatch.setattr(proxy, "NOTEBOOK_DIR", tmp_path)
    monkeypatch.setattr(proxy, "_registry_basename", lambda aid: None)

    resp = client.get("/notebook/render/UI-uq_p")
    assert resp.status_code == 200
    assert resp.text == "<html>OK</html>"


def test_render_404_distinguishes_missing_html_from_missing_report(client, monkeypatch, tmp_path):
    """Notebook present but HTML absent -> a distinct, diagnosable 404 message."""
    monkeypatch.setattr(proxy, "NOTEBOOK_DIR", tmp_path)
    monkeypatch.setattr(proxy, "_registry_basename", lambda aid: None)
    (tmp_path / "UI-uq_nohtml.ipynb").write_text("{}")

    resp = client.get("/render/UI-uq_nohtml")
    assert resp.status_code == 404
    assert "baked HTML missing" in resp.json()["error"]

    resp2 = client.get("/render/UI-uq_absent")
    assert resp2.status_code == 404
    assert resp2.json()["error"] == "report not found"


def test_render_neutralizes_traversal(client, monkeypatch, tmp_path):
    """A traversal id never reads outside NOTEBOOK_DIR."""
    monkeypatch.setattr(proxy, "NOTEBOOK_DIR", tmp_path)
    monkeypatch.setattr(proxy, "_registry_basename", lambda aid: None)
    resp = client.get("/render/..%2F..%2Fetc%2Fpasswd")
    assert resp.status_code in (400, 404)
    assert "root:" not in resp.text
