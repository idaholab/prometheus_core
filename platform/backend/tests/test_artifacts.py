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

"""Offline tests for artifact classification + the content proxy (task 07).

The classifier tests exercise ``classify_render_hint`` across json_type / tags /
mime / extension precedence. The router tests drive ``GET /api/artifacts/{id}/content``
against a ``TestClient`` with a seeded session catalog and ``uri_resolver`` stubbed —
no live agent, DeepLynx, or network. The auth/200 cases also prove the router is
mounted in ``app/main.py``.
"""

import pytest
from fastapi.testclient import TestClient

from app import uri_resolver
from app.services.artifacts import (
    artifact_download_payload,
    artifact_identity,
    classify_render_hint,
    to_artifact_meta,
)


# --------------------------------------------------------------------------- #
# classify_render_hint — precedence: json_type → tags → mime → extension
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "artifact,expected",
    [
        ({"json_type": "prometheus.thermal_analysis.result.v1"}, "thermal"),
        ({"tags": ["ifc"]}, "ifc"),
        ({"tags": ["exodus"]}, "mesh"),
        ({"tags": ["stl"]}, "mesh"),
        ({"tags": ["citation"]}, "reference"),
        ({"tags": ["data"]}, "json"),  # tag alias maps to the json viewer kind
        ({"mime_type": "model/ifc"}, "ifc"),
        ({"mime_type": "application/exodus"}, "mesh"),
        ({"mime_type": "application/x-netcdf"}, "mesh"),  # T-6: exodus container MIME
        ({"mime_type": "application/x-hdf5"}, "mesh"),  # T-6: exodus container MIME
        ({"mime_type": "model/stl"}, "mesh"),
        # A-2: a specific MIME outranks a generic tag…
        ({"tags": ["data"], "mime_type": "application/pdf"}, "pdf"),
        # …but a specific tag outranks a *generic* download MIME.
        ({"tags": ["exodus"], "mime_type": "application/octet-stream"}, "mesh"),
        ({"mime_type": "text/x-mermaid"}, "mermaid"),
        ({"mime_type": "application/pdf"}, "pdf"),
        ({"mime_type": "application/json"}, "json"),
        ({"mime_type": "text/csv"}, "table"),  # A-9: not the JSONViewer; the table viewer
        ({"mime_type": "application/csv"}, "table"),
        ({"mime_type": "text/tab-separated-values"}, "table"),
        ({"mime_type": "text/csv; charset=utf-8"}, "table"),
        ({"name": "results.csv"}, "table"),
        ({"name": "results.TSV"}, "table"),
        ({"mime_type": "text/plain", "name": "results.csv"}, "table"),  # mislabeled CSV
        ({"mime_type": "text/markdown", "name": "results.tsv"}, "table"),
        ({"mime_type": "text/csv", "tags": ["data"]}, "table"),  # MIME outranks the tag
        ({"mime_type": "image/png"}, "image"),
        ({"mime_type": "image/svg+xml"}, "image"),  # SVG folds into image (React)
        ({"mime_type": "application/octet-stream"}, "file"),
        ({"mime_type": "text/markdown"}, "report"),  # A-1: rendered inline, not downloaded
        ({"mime_type": "text/plain"}, "report"),  # A-1: old app rendered plain text inline too
        ({"mime_type": "application/yaml"}, "code"),
        ({"mime_type": "application/x-yaml"}, "code"),
        ({"mime_type": "text/yaml"}, "code"),
        ({"mime_type": "text/x-yaml"}, "code"),
        ({"name": "config.yaml"}, "code"),  # extension fallback
        ({"name": "config.yml"}, "code"),  # extension fallback
        # text/plain + a .yaml/.yml name still gets the source viewer, not Markdown.
        ({"mime_type": "text/plain", "name": "config.yaml"}, "code"),
        ({"mime_type": "text/x-moose"}, "code"),  # vendor MIME, no registered IANA type
        ({"name": "input.i"}, "code"),  # MOOSE input extension fallback
        # text/plain + a .i name still gets the source viewer, not Markdown.
        ({"mime_type": "text/plain", "name": "input.i"}, "code"),
        # More source / config languages: MIME, extension, and whole-file-name routes.
        ({"mime_type": "text/x-python"}, "code"),
        ({"mime_type": "application/toml"}, "code"),
        ({"mime_type": "application/xml"}, "code"),
        ({"mime_type": "text/xml"}, "code"),
        ({"mime_type": "text/x-c++src"}, "code"),
        ({"mime_type": "text/x-fortran"}, "code"),
        ({"mime_type": "application/x-sh"}, "code"),
        ({"mime_type": "application/sql"}, "code"),
        ({"mime_type": "text/x-diff"}, "code"),
        ({"name": "solver.py"}, "code"),
        ({"name": "pyproject.toml"}, "code"),
        ({"name": "mesh.xdmf"}, "code"),
        ({"name": "kernel.F90"}, "code"),  # extension match is case-insensitive
        ({"name": "main.cpp"}, "code"),
        ({"name": "run.sh"}, "code"),
        ({"name": "fix.patch"}, "code"),
        ({"name": "app.tsx"}, "code"),
        ({"name": "settings.jsonc"}, "code"),
        ({"name": "Dockerfile"}, "code"),
        ({"name": "Makefile"}, "code"),
        ({"name": "CMakeLists.txt"}, "code"),  # basename beats the generic .txt extension
        ({"mime_type": "text/plain", "name": "CMakeLists.txt"}, "code"),
        ({"mime_type": "text/plain", "name": "solver.py"}, "code"),
        ({"name": "run.log"}, "code"),  # bare .log / .txt names fall back to the source viewer
        ({"name": "notes.txt"}, "code"),
        # …but they must not capture ordinary text replies: agent text parts default to
        # the name "artifact.txt" with a text/plain or text/markdown MIME.
        ({"mime_type": "text/plain", "name": "artifact.txt"}, "report"),
        ({"mime_type": "text/markdown", "name": "notes.txt"}, "report"),
        # A non-source extension keeps report too: only code/table names override the MIME.
        ({"mime_type": "text/plain", "name": "scan.pdf"}, "report"),
        # JSON keeps the interactive tree viewer.
        ({"name": "data.json"}, "json"),
        ({"mime_type": "application/json", "name": "data.json"}, "json"),
        ({"name": "model.inp"}, "file"),  # .inp is ambiguous (Abaqus/MCNP/etc.) — stays a download
        ({"mime_type": "model/step"}, "file"),  # CAD → downloadable file
        ({"mime_type": "application/x-ipynb+json"}, "file"),  # notebook → downloadable file
        ({"name": "analysis.ipynb"}, "file"),  # notebook extension fallback
        ({"uri": "deeplynx://x/items/1", "name": "model.ifc"}, "ifc"),  # extension fallback
        ({"name": "report.pdf"}, "pdf"),
        ({"name": "notes.md"}, "report"),  # A-1: markdown extension fallback
        ({"name": "mesh.exo"}, "mesh"),
        ({"json_body": {"k": "v"}}, "json"),  # inline JSON, no other signal
        ({"mime_type": "application/x-whatever"}, "unknown"),
        ({}, "unknown"),
    ],
)
def test_classify_render_hint(artifact, expected):
    assert classify_render_hint(artifact) == expected


def test_to_artifact_meta_merges_metadata_tags():
    """Tags that crossed the A2A hop only in metadata still reach the frontend."""
    meta = to_artifact_meta(
        {
            "artifact_id": "m1",
            "name": "mesh.bin",
            "mime_type": "application/octet-stream",
            "tags": ["draft"],
            "metadata": {"tags": ["exodus", "draft"]},
        }
    )
    assert meta is not None
    assert meta.tags == ["draft", "exodus"]
    # A routing tag that only arrived in metadata still picks the viewer.
    assert meta.render_hint == "mesh"


def test_to_artifact_meta_tags_ignore_non_list_metadata_tags():
    meta = to_artifact_meta({"artifact_id": "m2", "name": "x", "tags": ["a", None], "metadata": {"tags": "exodus"}})
    assert meta is not None and meta.tags == ["a"]
    assert to_artifact_meta({"artifact_id": "m3", "name": "x"}).tags == []


# --------------------------------------------------------------------------- #
# artifact_download_payload — inline serialization
# --------------------------------------------------------------------------- #


def test_json_type_beats_mime():
    # A thermal result mislabeled with a generic MIME still routes to the viewer.
    artifact = {"json_type": "prometheus.thermal_analysis.result.v1", "mime_type": "application/json"}
    assert classify_render_hint(artifact) == "thermal"


def test_mime_normalized_with_charset_param():
    assert classify_render_hint({"mime_type": "application/pdf; charset=binary"}) == "pdf"


def test_to_artifact_meta_carries_hint_and_skips_conversation_message():
    meta = to_artifact_meta({"artifact_id": "a1", "name": "r.pdf", "mime_type": "application/pdf"})
    assert meta is not None and meta.render_hint == "pdf"

    assert to_artifact_meta({"name": "conversation_message"}) is None
    assert to_artifact_meta({"metadata": {"kind": "conversation_message"}}) is None


def test_to_artifact_meta_populates_citation_for_reference(monkeypatch):
    # CON-1: reference artifacts carry source/section/page from metadata onto the wire.
    meta = to_artifact_meta(
        {
            "artifact_id": "ref1",
            "tags": ["reference"],
            "metadata": {"source": "ASME BPVC", "section": "II-D", "page": 42},
        }
    )
    assert meta is not None and meta.render_hint == "reference"
    assert meta.citation is not None
    assert meta.citation.source == "ASME BPVC"
    assert meta.citation.section == "II-D"
    assert meta.citation.page == "42"  # coerced to str


def test_to_artifact_meta_citation_absent_when_no_metadata():
    meta = to_artifact_meta({"artifact_id": "a1", "mime_type": "application/pdf"})
    assert meta is not None and meta.citation is None


def test_download_payload_json_body():
    content, ext, mime = artifact_download_payload({"json_body": {"a": 1}})
    assert ext == ".json" and mime == "application/json"
    assert b'"a": 1' in content


def test_download_payload_markdown_extension_ignores_mime_parameters():
    content, ext, mime = artifact_download_payload({"text": "# hi"}, mime_type="text/markdown; charset=utf-8")
    assert ext == ".md" and content == b"# hi"
    assert mime == "text/markdown; charset=utf-8"  # the returned media type is unchanged


def test_download_payload_text_prefers_markdown_extension():
    content, ext, mime = artifact_download_payload({"text": "# hi"}, mime_type="text/markdown")
    assert ext == ".md" and mime == "text/markdown" and content == b"# hi"


def test_download_payload_text_prefers_yaml_extension():
    content, ext, mime = artifact_download_payload({"text": "a: 1\n"}, mime_type="application/yaml")
    assert ext == ".yaml" and mime == "application/yaml" and content == b"a: 1\n"


def test_download_payload_text_prefers_moose_extension():
    content, ext, mime = artifact_download_payload({"text": "[Mesh]\n[]\n"}, mime_type="text/x-moose")
    assert ext == ".i" and mime == "text/x-moose" and content == b"[Mesh]\n[]\n"


@pytest.mark.parametrize(
    ("mime", "ext"),
    [
        ("text/x-python", ".py"),
        ("application/toml", ".toml"),
        ("application/xml; charset=utf-8", ".xml"),
        ("text/x-c++hdr", ".hpp"),
        ("text/x-fortran", ".f90"),
        ("application/x-sh", ".sh"),
        ("text/x-diff", ".diff"),
        ("text/plain", ".txt"),
    ],
)
def test_download_payload_text_extension_per_mime(mime, ext):
    _, got_ext, got_mime = artifact_download_payload({"text": "x"}, mime_type=mime)
    assert got_ext == ext and got_mime == mime


@pytest.mark.parametrize(
    ("mime", "ext"),
    [
        ("text/csv", ".csv"),
        ("application/csv", ".csv"),
        ("text/csv; charset=utf-8", ".csv"),
        ("text/tab-separated-values", ".tsv"),
    ],
)
def test_download_payload_table_extension_per_mime(mime, ext):
    content, got_ext, got_mime = artifact_download_payload({"text_body": "a,b\n1,2\n"}, mime_type=mime)
    assert got_ext == ext and got_mime == mime and content == b"a,b\n1,2\n"


def test_download_payload_serves_text_body_not_description():
    content, ext, _ = artifact_download_payload(
        {"text_body": "print(1)\n", "description": "A python sample"}, mime_type="text/x-python"
    )
    assert content == b"print(1)\n" and ext == ".py"


def test_download_payload_empty_text_body_is_an_empty_file():
    # An empty file is still content: it must not fall through to the description.
    payload = artifact_download_payload({"text_body": "", "description": "empty sample"}, mime_type="text/x-python")
    assert payload is not None
    content, ext, _ = payload
    assert content == b"" and ext == ".py"


def test_download_payload_none_when_nothing_inline():
    assert artifact_download_payload({"name": "x", "uri": "file:///tmp/x"}) is None


# --------------------------------------------------------------------------- #
# GET /api/artifacts/{id}/content
# --------------------------------------------------------------------------- #


async def _authed_client(monkeypatch, session_store, artifacts=None) -> TestClient:
    """TestClient with a valid cookie and a seeded session artifact catalog.

    ``session_store`` is the Valkey-backed store conftest already installed on
    ``app.state``, so seeding is a write rather than an assignment: ``SessionState``
    is a frozen snapshot.
    """
    from app import security
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "jwt_secret", "test-secret", raising=False)
    monkeypatch.setattr(security.settings, "jwt_secret", "test-secret", raising=False)

    await session_store.reset("sid-artifact", "c1", artifacts=artifacts or [])

    token = security.issue_token(security.User(identifier="alice"), sid="sid-artifact")
    client = TestClient(app)
    client.cookies.set(settings.cookie_name, token)
    return client


def test_content_requires_auth():
    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/artifacts/a1/content")
    assert resp.status_code == 401


async def test_content_404_when_not_in_catalog(monkeypatch, session_store):
    client = await _authed_client(monkeypatch, session_store, artifacts=[{"artifact_id": "other"}])
    resp = client.get("/api/artifacts/missing/content")
    assert resp.status_code == 404


async def test_content_streams_inline_json_body(monkeypatch, session_store):
    client = await _authed_client(
        monkeypatch,
        session_store,
        artifacts=[{"artifact_id": "a1", "name": "result", "json_body": {"answer": 42}}],
    )
    resp = client.get("/api/artifacts/a1/content")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json() == {"answer": 42}
    assert 'filename="result.json"' in resp.headers["content-disposition"]


async def test_content_streams_text_body_inline(monkeypatch, session_store):
    client = await _authed_client(
        monkeypatch,
        session_store,
        artifacts=[
            {
                "artifact_id": "a1",
                "name": "solver.py",
                "mime_type": "text/x-python",
                "text_body": "print('hi')\n",
                "description": "A python sample",
            }
        ],
    )
    resp = client.get("/api/artifacts/a1/content")
    assert resp.status_code == 200
    assert resp.content == b"print('hi')\n"
    assert resp.headers["content-disposition"].startswith("inline")
    assert 'filename="solver.py"' in resp.headers["content-disposition"]


async def test_content_empty_text_body_is_200_with_no_bytes(monkeypatch, session_store):
    client = await _authed_client(
        monkeypatch,
        session_store,
        artifacts=[
            {
                "artifact_id": "a1",
                "name": "empty.py",
                "mime_type": "text/x-python",
                "text_body": "",
                "description": "Empty sample",
            }
        ],
    )
    resp = client.get("/api/artifacts/a1/content")
    assert resp.status_code == 200
    assert resp.content == b""
    assert resp.headers["content-disposition"].startswith("inline")


async def test_content_streams_file_uri(monkeypatch, session_store, tmp_path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    client = await _authed_client(
        monkeypatch,
        session_store,
        artifacts=[{"artifact_id": "a1", "name": "doc.pdf", "mime_type": "application/pdf", "uri": f"file://{f}"}],
    )
    resp = client.get("/api/artifacts/a1/content")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")
    assert resp.content == b"%PDF-1.4 fake"


async def test_content_502_when_resolve_fails(monkeypatch, session_store):
    async def _fail(uri, *, cache_dir, artifact=None, artifact_id=None):
        return None

    monkeypatch.setattr(uri_resolver, "resolve_to_local_path", _fail)
    client = await _authed_client(
        monkeypatch,
        session_store,
        artifacts=[{"artifact_id": "a1", "name": "x", "uri": "deeplynx://org/items/1"}],
    )
    resp = client.get("/api/artifacts/a1/content")
    assert resp.status_code == 502


async def test_content_404_when_in_catalog_but_no_content(monkeypatch, session_store):
    client = await _authed_client(monkeypatch, session_store, artifacts=[{"artifact_id": "a1", "name": "empty"}])
    resp = client.get("/api/artifacts/a1/content")
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# A-4 — stable identity for id-less artifacts
# --------------------------------------------------------------------------- #


def test_artifact_identity_is_stable_distinct_and_prefers_explicit():
    a = {"name": "one.txt", "uri": "deeplynx://x/items/1"}
    b = {"name": "two.txt", "uri": "deeplynx://x/items/2"}
    ida, idb = artifact_identity(a), artifact_identity(b)
    assert ida and idb and ida != idb  # non-empty and distinct (no "" collision)
    assert ida == artifact_identity(dict(a))  # deterministic
    assert artifact_identity({"artifact_id": "explicit", "name": "x"}) == "explicit"


async def test_content_fetches_idless_inline_artifact(monkeypatch, session_store):
    art = {"name": "notes", "json_body": {"k": "v"}}  # no artifact_id/id
    client = await _authed_client(monkeypatch, session_store, artifacts=[art])
    resp = client.get(f"/api/artifacts/{artifact_identity(art)}/content")
    assert resp.status_code == 200
    assert resp.json() == {"k": "v"}


# --------------------------------------------------------------------------- #
# A-5 / A-6 — Content-Disposition type + filename escaping
# --------------------------------------------------------------------------- #


async def test_content_disposition_is_attachment_for_download(monkeypatch, session_store, tmp_path):
    f = tmp_path / "logs.zip"
    f.write_bytes(b"PK\x03\x04zip")
    client = await _authed_client(
        monkeypatch,
        session_store,
        artifacts=[{"artifact_id": "a1", "name": "logs.zip", "mime_type": "application/zip", "uri": f"file://{f}"}],
    )
    resp = client.get("/api/artifacts/a1/content")
    assert resp.status_code == 200
    assert resp.headers["content-disposition"].startswith("attachment;")


async def test_content_disposition_escapes_dangerous_filename(monkeypatch, session_store):
    art = {"artifact_id": "a1", "name": 'ev"il\nname', "json_body": {"k": 1}}
    client = await _authed_client(monkeypatch, session_store, artifacts=[art])
    cd = client.get("/api/artifacts/a1/content").headers["content-disposition"]
    assert "\n" not in cd and "\r" not in cd  # no header injection
    # quote + newline stripped from the ascii name (.json appended for the inline body)
    assert 'filename="evilname.json"' in cd
    assert "filename*=UTF-8''" in cd  # RFC 5987 form carries the exact name
