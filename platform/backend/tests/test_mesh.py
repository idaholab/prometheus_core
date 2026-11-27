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

"""Tests for the mesh (Exodus/STL → VTP) restoration.

Most tests are offline (no VTK): the json_body/prop shape, the source-kind picker,
the enrichment hook (with the VTK conversion + URI resolver stubbed), and the VTP
route (auth / 404 / path-traversal, serving a pre-seeded cache file). The converter
round-trip is guarded by ``pytest.importorskip("vtk")`` so it runs only where VTK is
installed (the container), never breaking the offline suite.
"""

import asyncio
import json
import pickle
import types
from concurrent import futures
from concurrent.futures.process import BrokenProcessPool

import pytest
from fastapi.testclient import TestClient

from app import uri_resolver
from app.services.mesh import service


# --------------------------------------------------------------------------- #
# _mesh_kind — STL vs Exodus dispatch
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "name,uri,mime,expected",
    [
        ("mesh.stl", "", "", "stl"),
        ("", "file:///data/model.STL", "", "stl"),  # extension is case-insensitive
        ("", "", "model/stl", "stl"),
        ("", "", "application/vnd.ms-pki.stl", "stl"),
        ("mesh.exo", "", "", "exodus"),
        ("mesh.e", "", "", "exodus"),
        ("data", "", "application/x-exodus", "exodus"),
        ("", "", "", "exodus"),  # default
        # extension wins over a mismatched mime
        ("mesh.stl", "", "application/x-exodus", "stl"),
    ],
)
def test_mesh_kind(name, uri, mime, expected):
    assert service._mesh_kind(name, uri, mime) == expected


# --------------------------------------------------------------------------- #
# _build_json_body — the exact prop shape MeshViewerElement.tsx reads
# --------------------------------------------------------------------------- #


def _manifest(point=None, cell=None):
    return {
        "version": "1.0",
        "num_timesteps": 1,
        "files": [{"index": 0, "timestep_index": 0, "time_value": 0.0, "filename": "surface_t0000.vtp"}],
        "variables": {"point": point or [], "cell": cell or []},
        "array_ranges": {},
        "bounds": [0, 1, 0, 1, 0, 1],
    }


def test_build_json_body_shape_and_baseurl():
    metadata = {"num_timesteps": 2, "time_values": [0.0, 1.0]}
    body = service._build_json_body("ds123", _manifest(point=["temperature"], cell=["block_id"]), metadata, "My Mesh")

    assert body["datasetId"] == "ds123"
    assert body["baseUrl"] == "/api/artifacts/mesh/ds123"
    assert body["baseUrl"] == f"{service.MESH_URL_PREFIX}/ds123"
    assert body["title"] == "My Mesh"
    assert body["metadata"] is metadata
    assert body["manifest"]["files"][0]["filename"] == "surface_t0000.vtp"
    assert body["initialColorPreset"] == "coolToWarm"
    assert body["showControls"] is True
    assert body["allowPicking"] is True


def test_build_json_body_initial_variable_prefers_point_then_cell_then_none():
    m = {"num_timesteps": 1, "time_values": [0.0]}
    assert service._build_json_body("d", _manifest(point=["p1"], cell=["c1"]), m, "t")["initialVariable"] == "p1"
    assert service._build_json_body("d", _manifest(cell=["c1"]), m, "t")["initialVariable"] == "c1"
    assert service._build_json_body("d", _manifest(), m, "t")["initialVariable"] is None


# --------------------------------------------------------------------------- #
# enrich_mesh_artifacts — the turn-time hook (VTK + resolver stubbed)
# --------------------------------------------------------------------------- #


def _stub_resolver(monkeypatch, tmp_path):
    """Make resolve_to_local_path return a real (existing) local file."""
    src = tmp_path / "mesh.exo"
    src.write_bytes(b"fake-exodus-bytes")

    async def _resolve(uri, *, cache_dir, artifact=None, artifact_id=None):
        return src

    monkeypatch.setattr(uri_resolver, "resolve_to_local_path", _resolve)
    return src


async def test_enrich_populates_mesh_json_body(monkeypatch, tmp_path):
    _stub_resolver(monkeypatch, tmp_path)

    calls = []

    async def _fake_convert(local_path, cache_root, name, uri, mime, *, ident):
        calls.append((name, mime))
        return "dsAAA", _manifest(point=["temperature"]), {"num_timesteps": 1, "time_values": [0.0]}

    monkeypatch.setattr(service, "_convert_offloop", _fake_convert)

    art = {"artifact_id": "m1", "name": "mesh.exo", "mime_type": "application/x-exodus", "uri": "file:///x/mesh.exo"}
    response = types.SimpleNamespace(new_artifacts=[art], artifacts=[art])

    await service.enrich_mesh_artifacts(response)

    assert calls  # conversion actually ran
    assert art["json_body"] is not None
    assert art["json_body"]["datasetId"] == "dsAAA"
    assert art["json_body"]["baseUrl"] == "/api/artifacts/mesh/dsAAA"
    assert art["json_body"]["initialVariable"] == "temperature"


async def test_enrich_applies_body_to_all_objects_sharing_identity(monkeypatch, tmp_path):
    # new_artifacts and the persisted catalog can be distinct dict objects for the same
    # artifact; both must end up carrying the manifest.
    _stub_resolver(monkeypatch, tmp_path)

    async def _fake_convert(*a, **kw):
        return "ds1", _manifest(), {"num_timesteps": 1, "time_values": [0.0]}

    monkeypatch.setattr(service, "_convert_offloop", _fake_convert)

    new_obj = {"artifact_id": "same", "name": "a.exo", "mime_type": "application/x-exodus", "uri": "file:///a.exo"}
    cat_obj = {"artifact_id": "same", "name": "a.exo", "mime_type": "application/x-exodus", "uri": "file:///a.exo"}
    response = types.SimpleNamespace(new_artifacts=[new_obj], artifacts=[cat_obj])

    await service.enrich_mesh_artifacts(response)

    assert new_obj["json_body"] is not None
    assert cat_obj["json_body"] is not None  # distinct object, same identity → enriched


async def test_enrich_leaves_non_mesh_untouched(monkeypatch, tmp_path):
    _stub_resolver(monkeypatch, tmp_path)

    async def _boom(*a, **kw):
        raise AssertionError("conversion must not run for a non-mesh artifact")

    monkeypatch.setattr(service, "_convert_offloop", _boom)

    art = {"artifact_id": "p1", "name": "report.pdf", "mime_type": "application/pdf", "uri": "file:///r.pdf"}
    response = types.SimpleNamespace(new_artifacts=[art], artifacts=[art])

    await service.enrich_mesh_artifacts(response)

    assert art.get("json_body") is None


async def test_enrich_downgrades_gracefully_on_conversion_failure(monkeypatch, tmp_path):
    _stub_resolver(monkeypatch, tmp_path)

    async def _fail(*a, **kw):
        raise RuntimeError("vtk blew up")

    monkeypatch.setattr(service, "_convert_offloop", _fail)

    art = {"artifact_id": "m2", "name": "mesh.exo", "mime_type": "application/x-exodus", "uri": "file:///x.exo"}
    response = types.SimpleNamespace(new_artifacts=[art], artifacts=[art])

    await service.enrich_mesh_artifacts(response)  # must not raise

    assert art.get("json_body") is None  # left null → frontend downgrades to a download


async def test_enrich_skips_mesh_without_uri(monkeypatch):
    async def _boom(*a, **kw):
        raise AssertionError("conversion must not run without a resolvable uri")

    monkeypatch.setattr(service, "_convert_offloop", _boom)

    art = {"artifact_id": "m3", "name": "mesh.exo", "mime_type": "application/x-exodus"}  # no uri
    response = types.SimpleNamespace(new_artifacts=[art], artifacts=[art])

    await service.enrich_mesh_artifacts(response)

    assert art.get("json_body") is None


# --------------------------------------------------------------------------- #
# _convert_offloop — subprocess-pool crash + timeout containment
# --------------------------------------------------------------------------- #


class _FakeProc:
    """Stand-in for a ProcessPoolExecutor worker process."""

    def __init__(self) -> None:
        self.killed = False

    def is_alive(self) -> bool:
        return not self.killed

    def kill(self) -> None:
        self.killed = True


class _FakeExecutor:
    """Minimal executor: `run_in_executor` only needs `.submit()` returning a Future.

    `_processes` mirrors ProcessPoolExecutor's private worker map, which
    `_discard_executor(..., kill_children=True)` reaches into to stop a wedged conversion.
    """

    def __init__(self, future: futures.Future) -> None:
        self._future = future
        self._processes = {1: _FakeProc()}
        self.shutdown_calls: list[dict] = []
        self.submitted: list[tuple] = []

    def submit(self, fn, *args):
        self.submitted.append((fn, args))
        return self._future

    def shutdown(self, wait=True, cancel_futures=False):
        self.shutdown_calls.append({"wait": wait, "cancel_futures": cancel_futures})


async def test_convert_offloop_survives_a_dead_worker(monkeypatch, tmp_path):
    """A child segfault/OOM must cost one artifact, not the web process."""
    future: futures.Future = futures.Future()
    future.set_running_or_notify_cancel()
    future.set_exception(BrokenProcessPool("worker died"))
    fake = _FakeExecutor(future)
    monkeypatch.setattr(service, "_vtk_executor", fake)

    result = await service._convert_offloop(tmp_path / "m.exo", tmp_path, "m.exo", "file:///m.exo", "", ident="m1")

    assert result is None  # degrades, does not raise
    # The pool is poisoned for every later submit, so it must be replaced, not reused.
    assert service._vtk_executor is None
    assert fake.shutdown_calls == [{"wait": False, "cancel_futures": True}]
    # A dead worker needs no killing; only the timeout path does that.
    assert fake._processes[1].killed is False


async def test_convert_offloop_times_out_and_kills_the_pool(monkeypatch, tmp_path):
    """A wedged conversion can't be cancelled cooperatively, so the workers are killed."""
    fake = _FakeExecutor(futures.Future())  # never completes
    monkeypatch.setattr(service, "_vtk_executor", fake)
    monkeypatch.setattr(service.settings, "mesh_timeout_seconds", 0.05, raising=False)

    result = await service._convert_offloop(tmp_path / "m.exo", tmp_path, "m.exo", "file:///m.exo", "", ident="m2")

    assert result is None
    assert service._vtk_executor is None
    assert fake._processes[1].killed is True
    assert fake.shutdown_calls == [{"wait": False, "cancel_futures": True}]


async def test_stale_pool_failure_leaves_the_replacement_pool_alone(monkeypatch, tmp_path):
    """A job still on a replaced pool A breaks with ``BrokenProcessPool`` after B took over.

    Discarding "whatever is current" used to shut down B, cancelling unrelated
    conversions queued on it; only the pool the job actually ran on may be discarded.
    """
    future: futures.Future = futures.Future()
    stale = _FakeExecutor(future)
    replacement = _FakeExecutor(futures.Future())
    monkeypatch.setattr(service, "_vtk_executor", stale)

    async def fail_after_replacement():
        await asyncio.sleep(0)  # let _convert_offloop submit to `stale` first
        service._vtk_executor = replacement  # a timeout elsewhere replaced the pool
        future.set_running_or_notify_cancel()
        future.set_exception(BrokenProcessPool("worker died"))

    result, _ = await asyncio.gather(
        service._convert_offloop(tmp_path / "m.exo", tmp_path, "m.exo", "file:///m.exo", "", ident="m3"),
        fail_after_replacement(),
    )

    assert result is None
    assert service._vtk_executor is replacement
    assert replacement.shutdown_calls == []


async def test_pool_teardown_cancellation_degrades_instead_of_propagating(monkeypatch, tmp_path):
    """``shutdown(cancel_futures=True)`` on our pool cancels our pending job. That is not a
    cancellation of *this* task, so it must degrade to "no mesh data", not escape."""
    future: futures.Future = futures.Future()
    monkeypatch.setattr(service, "_vtk_executor", _FakeExecutor(future))

    async def teardown():
        await asyncio.sleep(0)
        future.cancel()

    result, _ = await asyncio.gather(
        service._convert_offloop(tmp_path / "m.exo", tmp_path, "m.exo", "file:///m.exo", "", ident="m4"),
        teardown(),
    )
    assert result is None


async def test_real_task_cancellation_still_propagates(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "_vtk_executor", _FakeExecutor(futures.Future()))
    task = asyncio.create_task(
        service._convert_offloop(tmp_path / "m.exo", tmp_path, "m.exo", "file:///m.exo", "", ident="m5")
    )
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_shutdown_mesh_executor_is_a_noop_when_unused(monkeypatch):
    """The lifespan calls this unconditionally; a server that converted nothing has no pool."""
    monkeypatch.setattr(service, "_vtk_executor", None)
    service.shutdown_mesh_executor()  # must not raise
    assert service._vtk_executor is None


def test_shutdown_mesh_executor_kills_a_live_pool(monkeypatch):
    """A graceful stop must not leave spawned VTK workers holding the container open."""
    fake = _FakeExecutor(futures.Future())
    monkeypatch.setattr(service, "_vtk_executor", fake)
    service.shutdown_mesh_executor()
    assert service._vtk_executor is None
    assert fake._processes[1].killed is True
    assert fake.shutdown_calls == [{"wait": False, "cancel_futures": True}]


async def test_convert_sync_crosses_the_process_boundary(monkeypatch, tmp_path):
    """Guard the contract the process pool depends on: the callable is picklable by
    reference and every argument survives a pickle round-trip. A future refactor that
    closes `_convert_sync` over something unpicklable would otherwise only fail at
    runtime, inside a submit, as a degraded artifact. The arguments are the ones
    `_convert_offloop` really submits, not a tuple built here."""
    done: futures.Future = futures.Future()
    done.set_running_or_notify_cancel()
    done.set_result(None)
    fake = _FakeExecutor(done)
    monkeypatch.setattr(service, "_vtk_executor", fake)

    await service._convert_offloop(tmp_path / "m.exo", tmp_path, "m.exo", "file:///m.exo", "", ident="m6")

    ((fn, args),) = fake.submitted
    assert pickle.loads(pickle.dumps(fn)) is service._convert_sync
    assert pickle.loads(pickle.dumps(args)) == args


# --------------------------------------------------------------------------- #
# GET /api/artifacts/mesh/{dataset_id}/{filename}
# --------------------------------------------------------------------------- #


def _authed_client(monkeypatch, tmp_path) -> TestClient:
    """TestClient with a valid session cookie and the mesh cache root at tmp_path."""
    from app import security
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "jwt_secret", "test-secret", raising=False)
    monkeypatch.setattr(security.settings, "jwt_secret", "test-secret", raising=False)
    monkeypatch.setattr(settings, "mesh_cache_dir", str(tmp_path), raising=False)

    token = security.issue_token(security.User(identifier="alice"), sid="sid-mesh")
    client = TestClient(app)
    client.cookies.set(settings.cookie_name, token)
    return client


def test_mesh_route_requires_auth(tmp_path, monkeypatch):
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "mesh_cache_dir", str(tmp_path), raising=False)
    client = TestClient(app)
    assert client.get("/api/artifacts/mesh/ds1/surface_t0000.vtp").status_code == 401


def test_mesh_route_serves_cached_vtp(monkeypatch, tmp_path):
    ds = tmp_path / "ds1"
    ds.mkdir()
    (ds / "surface_t0000.vtp").write_text("<VTKFile type='PolyData'></VTKFile>")

    client = _authed_client(monkeypatch, tmp_path)
    resp = client.get("/api/artifacts/mesh/ds1/surface_t0000.vtp")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    assert "VTKFile" in resp.text


def test_mesh_route_404_when_missing(monkeypatch, tmp_path):
    client = _authed_client(monkeypatch, tmp_path)
    assert client.get("/api/artifacts/mesh/ds1/surface_t0000.vtp").status_code == 404


def test_mesh_route_rejects_directory_as_file(monkeypatch, tmp_path):
    (tmp_path / "ds1").mkdir()  # exists but is a dir, not a file
    client = _authed_client(monkeypatch, tmp_path)
    assert client.get("/api/artifacts/mesh/ds1/sub").status_code == 404


def test_reject_unsafe_segment_blocks_traversal():
    from fastapi import HTTPException

    from app.routers.artifacts import _reject_unsafe_segment

    # good names pass
    _reject_unsafe_segment("ds1")
    _reject_unsafe_segment("surface_t0000.vtp")

    # traversal / separators / bad chars are rejected with 400
    for bad in ["..", "../etc", "a/b", "a\\b", "..%2f", "foo bar", ""]:
        with pytest.raises(HTTPException) as exc:
            _reject_unsafe_segment(bad)
        assert exc.value.status_code == 400


# --------------------------------------------------------------------------- #
# Converter round-trip — VTK-only (skipped where VTK isn't installed)
# --------------------------------------------------------------------------- #


def test_stl_conversion_roundtrip_and_cache(tmp_path):
    vtk = pytest.importorskip("vtk")
    from app.services.mesh.stl import convert_stl_sync

    # Synthesize a small binary STL from a sphere.
    sphere = vtk.vtkSphereSource()
    sphere.Update()
    stl_path = tmp_path / "sphere.stl"
    writer = vtk.vtkSTLWriter()
    writer.SetFileName(str(stl_path))
    writer.SetInputConnection(sphere.GetOutputPort())
    writer.Write()

    out = tmp_path / "out"
    metadata = convert_stl_sync(stl_path, out)

    assert (out / "surface_t0000.vtp").is_file()
    assert (out / "manifest.json").is_file()
    assert (out / "meta.json").is_file()
    assert metadata["num_timesteps"] == 1
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["files"][0]["filename"] == "surface_t0000.vtp"
    assert manifest["variables"] == {"point": [], "cell": []}


def test_convert_sync_stl_branch_uses_cache(tmp_path):
    pytest.importorskip("vtk")
    import vtk

    from app.services.mesh.cache import compute_dataset_id

    sphere = vtk.vtkSphereSource()
    sphere.Update()
    stl_path = tmp_path / "sphere.stl"
    writer = vtk.vtkSTLWriter()
    writer.SetFileName(str(stl_path))
    writer.SetInputConnection(sphere.GetOutputPort())
    writer.Write()

    cache_root = tmp_path / "cache"
    cache_root.mkdir()

    dataset_id, manifest, metadata = service._convert_sync(stl_path, cache_root, "sphere.stl", "", "model/stl")
    assert dataset_id == compute_dataset_id(stl_path, {"type": "stl"})
    assert (cache_root / dataset_id / "surface_t0000.vtp").is_file()
    assert manifest["num_timesteps"] == 1
    assert metadata["num_elements"] > 0

    # Second call is a cache hit (manifest already present) — same id, still valid.
    dataset_id2, _, _ = service._convert_sync(stl_path, cache_root, "sphere.stl", "", "model/stl")
    assert dataset_id2 == dataset_id


def test_unreadable_exodus_is_rejected_and_not_cached(tmp_path):
    """VTK reads an unparseable file as an empty mesh rather than raising; that must
    not be cached as the file's mesh, or every later view serves it."""
    pytest.importorskip("vtk")
    from app.services.mesh.cache import is_cached
    from app.services.mesh.converter import convert_exodus
    from app.services.mesh.exceptions import InvalidExodusFileError
    from app.services.mesh.models import ConvertRequest

    bad = tmp_path / "bad.e"
    bad.write_text("not an exodus file\n")
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    request = ConvertRequest(input_path=bad, output_dir=cache_root, timestep_mode="all")

    with pytest.raises(InvalidExodusFileError, match="No geometry"):
        convert_exodus(request, cache_root=cache_root)

    assert not any(is_cached(cache_root, d.name) for d in cache_root.iterdir())
    assert not any(cache_root.iterdir())


def test_a_readable_exodus_converts_past_the_empty_mesh_guard(tmp_path):
    pytest.importorskip("vtk")
    import shutil
    from pathlib import Path

    from app.services.mesh.converter import convert_exodus
    from app.services.mesh.models import ConvertRequest

    src = tmp_path / "square.e"
    shutil.copy(Path(__file__).parent / "fixtures" / "mesh" / "square.e", src)
    cache_root = tmp_path / "cache"
    cache_root.mkdir()

    result = convert_exodus(
        ConvertRequest(input_path=src, output_dir=cache_root, timestep_mode="all"), cache_root=cache_root
    )

    assert result.metadata["num_nodes"] == 9
    assert result.metadata["num_elements"] == 4
    assert (result.output_dir / "manifest.json").is_file()
    assert (result.output_dir / "surface_t0000.vtp").is_file()

    # A second conversion of the same file is a cache hit: a cached entry with nodes is served.
    again = convert_exodus(
        ConvertRequest(input_path=src, output_dir=cache_root, timestep_mode="all"), cache_root=cache_root
    )
    assert again.dataset_id == result.dataset_id
    assert again.metadata["num_nodes"] == 9


def test_inspect_exodus_rejects_an_unreadable_file_like_conversion(tmp_path):
    """Both entry points share one geometry check: inspecting a file VTK can't read
    must not report it as a valid file with zero nodes."""
    pytest.importorskip("vtk")
    from pathlib import Path

    from app.services.mesh.converter import inspect_exodus
    from app.services.mesh.exceptions import InvalidExodusFileError

    bad = tmp_path / "bad.e"
    bad.write_text("not an exodus file\n")

    with pytest.raises(InvalidExodusFileError, match="No geometry"):
        inspect_exodus(bad)

    assert inspect_exodus(Path(__file__).parent / "fixtures" / "mesh" / "square.e")["num_nodes"] == 9


def test_a_cached_empty_mesh_is_reconverted_and_rejected(tmp_path):
    """An empty mesh cached before the guard existed is a miss, not a hit."""
    pytest.importorskip("vtk")
    from dataclasses import asdict

    from app.services.mesh.cache import compute_dataset_id, get_cache_path
    from app.services.mesh.converter import convert_exodus
    from app.services.mesh.exceptions import InvalidExodusFileError
    from app.services.mesh.models import ConvertRequest

    bad = tmp_path / "bad.e"
    bad.write_text("not an exodus file\n")
    cache_root = tmp_path / "cache"
    request = ConvertRequest(input_path=bad, output_dir=cache_root, timestep_mode="all")
    poisoned = get_cache_path(cache_root, compute_dataset_id(bad, asdict(request)))
    poisoned.mkdir(parents=True)
    (poisoned / "manifest.json").write_text("{}")
    (poisoned / "meta.json").write_text(json.dumps({"num_nodes": 0}))

    with pytest.raises(InvalidExodusFileError, match="No geometry"):
        convert_exodus(request, cache_root=cache_root)


async def test_a_converter_error_logs_one_warning_without_a_traceback(monkeypatch, tmp_path, caplog):
    import logging

    from app.services.mesh.exceptions import InvalidExodusFileError

    _stub_resolver(monkeypatch, tmp_path)

    async def _invalid(*a, **kw):
        raise InvalidExodusFileError("No geometry read from mesh.exo")

    monkeypatch.setattr(service, "_convert_offloop", _invalid)
    art = {"artifact_id": "m4", "name": "mesh.exo", "mime_type": "application/x-exodus", "uri": "file:///x.exo"}
    with caplog.at_level(logging.WARNING, logger=service.logger.name):
        await service.enrich_mesh_artifacts(types.SimpleNamespace(new_artifacts=[art], artifacts=[art]))

    records = [r for r in caplog.records if r.name == service.logger.name]
    assert [(r.levelno, r.exc_info) for r in records] == [(logging.WARNING, None)]
    assert art.get("json_body") is None
