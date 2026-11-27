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


async def test_a_queued_conversion_does_not_time_out_while_it_waits(monkeypatch, tmp_path):
    """A one-worker pool runs jobs one after another. Each conversion takes 0.15 s and the
    budget is 0.2 s, so a second job's clock must start when it gets the worker, not
    when it is submitted: otherwise it times out queued and the pool is killed."""
    monkeypatch.setattr(service.settings, "mesh_workers", 1, raising=False)
    monkeypatch.setattr(service.settings, "mesh_timeout_seconds", 0.2, raising=False)
    monkeypatch.setattr(service, "_slots", service.weakref.WeakKeyDictionary())

    class _OneWorker(_FakeExecutor):
        """Each submitted job finishes 0.15 s after the previous one, like a real
        single-worker pool working through its queue."""

        def __init__(self) -> None:
            super().__init__(futures.Future())
            self._free_at = 0.0

        def submit(self, fn, *args):
            loop = asyncio.get_running_loop()
            self._free_at = max(self._free_at, loop.time()) + 0.15
            future: futures.Future = futures.Future()
            future.set_running_or_notify_cancel()
            loop.call_at(self._free_at, future.set_result, (f"ds{len(self.submitted)}", {}, {}))
            self.submitted.append((fn, args))
            return future

    fake = _OneWorker()
    monkeypatch.setattr(service, "_vtk_executor", fake)

    args = (tmp_path / "m.exo", tmp_path, "m.exo", "file:///m.exo", "")
    one, two = await asyncio.gather(
        service._convert_offloop(*args, ident="a"),
        service._convert_offloop(*args, ident="b"),
    )

    assert one is not None and two is not None
    assert fake._processes[1].killed is False


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
    for bad in ["..", "../etc", "a/b", "a\\b", "..%2f", "foo bar", "", ".index", ".hidden"]:
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


# --------------------------------------------------------------------------- #
# mesh_props: on-demand conversion, source index, shared in-flight builds
# --------------------------------------------------------------------------- #

# A real dataset id: compute_dataset_id's 16 hex characters.
_DATASET = "0123456789abcdef"

_MESH = {
    "artifact_id": "m1",
    "name": "mesh.exo",
    "mime_type": "application/x-exodus",
    "uri": "deeplynx://organizations/1/projects/2/items/42",
}


def _fake_cached_convert(monkeypatch, tmp_path, calls, *, gate=None):
    """A _convert_offloop that writes a real cache entry, so later reads hit the disk."""
    monkeypatch.setattr(service.settings, "mesh_cache_dir", str(tmp_path / "cache"), raising=False)

    async def _convert(local_path, cache_root, name, uri, mime, *, ident):
        calls.append(uri)
        if gate is not None:
            await gate.wait()
        out = cache_root / _DATASET
        out.mkdir(parents=True, exist_ok=True)
        (out / "manifest.json").write_text(json.dumps(_manifest(point=["T"])))
        (out / "meta.json").write_text(json.dumps({"num_timesteps": 1, "time_values": [0.0]}))
        (out / "surface_t0000.vtp").write_text("<VTKFile/>")
        return _DATASET, _manifest(point=["T"]), {"num_timesteps": 1, "time_values": [0.0]}

    monkeypatch.setattr(service, "_convert_offloop", _convert)


async def test_mesh_props_converts_once_then_reads_the_source_index(monkeypatch, tmp_path):
    _stub_resolver(monkeypatch, tmp_path)
    calls: list[str] = []
    _fake_cached_convert(monkeypatch, tmp_path, calls)

    first = await service.mesh_props(dict(_MESH))
    assert first is not None and first["datasetId"] == _DATASET

    async def _no_download(*_a, **_k):
        raise AssertionError("a source-index hit must not download")

    monkeypatch.setattr(uri_resolver, "resolve_to_local_path", _no_download)
    again = await service.mesh_props({**_MESH, "name": "renamed.exo"})

    assert calls == [_MESH["uri"]]
    assert again is not None and again["datasetId"] == _DATASET
    assert again["title"] == "renamed.exo"


async def test_concurrent_mesh_props_share_one_conversion(monkeypatch, tmp_path):
    _stub_resolver(monkeypatch, tmp_path)
    calls: list[str] = []
    gate = asyncio.Event()
    _fake_cached_convert(monkeypatch, tmp_path, calls, gate=gate)

    pending = [asyncio.create_task(service.mesh_props(dict(_MESH))) for _ in range(3)]
    await asyncio.sleep(0.01)
    gate.set()
    results = await asyncio.gather(*pending)

    assert calls == [_MESH["uri"]]
    assert all(r is not None and r["datasetId"] == _DATASET for r in results)


async def test_a_cancelled_caller_does_not_cancel_the_conversion(monkeypatch, tmp_path):
    _stub_resolver(monkeypatch, tmp_path)
    calls: list[str] = []
    gate = asyncio.Event()
    _fake_cached_convert(monkeypatch, tmp_path, calls, gate=gate)

    caller = asyncio.create_task(service.mesh_props(dict(_MESH)))
    while not service._inflight:  # the shared task has started
        await asyncio.sleep(0)
    (shared,) = service._inflight.values()
    caller.cancel()
    gate.set()
    await shared

    assert (tmp_path / "cache" / _DATASET / "manifest.json").is_file()
    # The task, not the gone caller, records the index entry, so the next view is a hit.
    assert len(list((tmp_path / "cache" / ".index").glob("*.json"))) == 1


async def test_a_file_source_is_never_indexed(monkeypatch, tmp_path):
    """A file:// path can be rewritten under the same URI, so each view re-reads it."""
    _stub_resolver(monkeypatch, tmp_path)
    calls: list[str] = []
    _fake_cached_convert(monkeypatch, tmp_path, calls)
    local = {**_MESH, "uri": "file:///out/result.e"}

    await service.mesh_props(dict(local))
    await service.mesh_props(dict(local))

    assert calls == ["file:///out/result.e", "file:///out/result.e"]
    assert not (tmp_path / "cache" / ".index").exists()


async def test_one_item_with_another_file_gets_its_own_index_entry(monkeypatch, tmp_path):
    """The resolver downloads metadata.deeplynx_file_id when it is set, so an artifact
    naming the same item with another file must not reuse, or overwrite, the entry
    another conversation's artifact wrote."""
    _stub_resolver(monkeypatch, tmp_path)
    calls: list[str] = []
    _fake_cached_convert(monkeypatch, tmp_path, calls)
    first = {**_MESH, "metadata": {"deeplynx_file_id": "f1"}}
    other = {**_MESH, "artifact_id": "m9", "metadata": {"deeplynx_file_id": "f2"}}

    await service.mesh_props(dict(first))
    await service.mesh_props(dict(other))
    await service.mesh_props(dict(first))

    assert len(calls) == 2  # f1 converted, f2 converted, f1 again from the index
    assert len(list((tmp_path / "cache" / ".index").glob("*.json"))) == 2


async def test_mesh_props_is_none_without_a_uri():
    assert await service.mesh_props({**_MESH, "uri": ""}) is None


# --------------------------------------------------------------------------- #
# GET /api/conversations/{cid}/artifacts/{aid}/mesh
# --------------------------------------------------------------------------- #


def _patch_catalog(monkeypatch, catalog: dict[str, dict]) -> None:
    from app.routers import artifacts as artifacts_router

    class _Catalog:
        available = True

        def owns(self, user_id, conv_id):
            return (user_id, conv_id) == ("alice", "c1")

        def get_meta(self, conv_id):
            return {}

        def get_artifact(self, conv_id, artifact_id):
            return catalog.get(artifact_id) if conv_id == "c1" else None

    monkeypatch.setattr(artifacts_router, "ConversationStateClient", lambda _url: _Catalog())


def test_mesh_props_route_converts_and_returns_viewer_props(monkeypatch, tmp_path):
    _stub_resolver(monkeypatch, tmp_path)
    calls: list[str] = []
    _fake_cached_convert(monkeypatch, tmp_path, calls)
    _patch_catalog(monkeypatch, {"m1": _MESH})

    resp = _authed_client(monkeypatch, tmp_path / "cache").get("/api/conversations/c1/artifacts/m1/mesh")

    assert resp.status_code == 200
    assert resp.json()["baseUrl"] == f"/api/artifacts/mesh/{_DATASET}"


def test_mesh_props_route_404s_for_another_users_conversation(monkeypatch, tmp_path):
    _patch_catalog(monkeypatch, {"m1": _MESH})
    client = _authed_client(monkeypatch, tmp_path)
    assert client.get("/api/conversations/c-bob/artifacts/m1/mesh").status_code == 404


def test_mesh_props_route_404s_for_a_non_mesh(monkeypatch, tmp_path):
    _patch_catalog(monkeypatch, {"p1": {"artifact_id": "p1", "name": "plot.png", "mime_type": "image/png"}})
    client = _authed_client(monkeypatch, tmp_path)
    assert client.get("/api/conversations/c1/artifacts/p1/mesh").status_code == 404


def test_mesh_props_route_422s_when_conversion_fails(monkeypatch, tmp_path):
    _stub_resolver(monkeypatch, tmp_path)
    monkeypatch.setattr(service.settings, "mesh_cache_dir", str(tmp_path / "cache"), raising=False)

    async def _fail(*_a, **_k):
        return None

    monkeypatch.setattr(service, "_convert_offloop", _fail)
    _patch_catalog(monkeypatch, {"m1": _MESH})

    resp = _authed_client(monkeypatch, tmp_path / "cache").get("/api/conversations/c1/artifacts/m1/mesh")
    assert resp.status_code == 422
    assert "mesh.exo" in resp.json()["detail"]


def test_mesh_props_route_422s_when_conversion_raises(monkeypatch, tmp_path, caplog):
    """An unexpected error in the shared task (a storage error, say) is the documented
    422, not a 500, and it is logged once."""
    import logging

    monkeypatch.setattr(service.settings, "mesh_cache_dir", str(tmp_path / "cache"), raising=False)

    async def _boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(service, "_enrich_one", _boom)
    _patch_catalog(monkeypatch, {"m1": _MESH})

    with caplog.at_level(logging.ERROR, logger=service.logger.name):
        resp = _authed_client(monkeypatch, tmp_path / "cache").get("/api/conversations/c1/artifacts/m1/mesh")

    assert resp.status_code == 422
    assert [r.levelno for r in caplog.records if r.name == service.logger.name] == [logging.ERROR]


def test_vtp_route_never_serves_the_source_index(monkeypatch, tmp_path):
    index = tmp_path / ".index"
    index.mkdir()
    (index / "k.json").write_text("{}")

    client = _authed_client(monkeypatch, tmp_path)
    assert client.get("/api/artifacts/mesh/.index/k.json").status_code == 400


def test_only_mesh_artifacts_with_a_uri_get_a_mesh_url():
    from app.services.artifacts import shape_artifacts

    mesh, no_uri, png = shape_artifacts(
        [
            _MESH,
            {**_MESH, "artifact_id": "m2", "uri": ""},
            {"artifact_id": "p1", "name": "a.png", "uri": "file:///a.png"},
        ],
        conversation_id="c1",
    )
    assert mesh.mesh_url == "/api/conversations/c1/artifacts/m1/mesh"
    assert no_uri.mesh_url == ""
    assert png.mesh_url == ""


async def test_an_unwritable_source_index_still_returns_the_props(monkeypatch, tmp_path):
    _stub_resolver(monkeypatch, tmp_path)
    calls: list[str] = []
    _fake_cached_convert(monkeypatch, tmp_path, calls)

    # A regular file where the index directory should be: mkdir fails with an OSError.
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    monkeypatch.setattr(service, "_index_path", lambda _root, key: blocker / f"{key}.json")

    props = await service.mesh_props(dict(_MESH))
    assert props is not None and props["datasetId"] == _DATASET


async def test_a_corrupt_cached_dataset_is_converted_again(monkeypatch, tmp_path):
    _stub_resolver(monkeypatch, tmp_path)
    calls: list[str] = []
    _fake_cached_convert(monkeypatch, tmp_path, calls)
    await service.mesh_props(dict(_MESH))
    (tmp_path / "cache" / _DATASET / "meta.json").write_text("{not json")

    props = await service.mesh_props(dict(_MESH))

    assert len(calls) == 2
    assert props is not None and props["datasetId"] == _DATASET


async def test_an_index_entry_whose_dataset_was_evicted_is_converted_again(monkeypatch, tmp_path):
    import shutil

    _stub_resolver(monkeypatch, tmp_path)
    calls: list[str] = []
    _fake_cached_convert(monkeypatch, tmp_path, calls)
    await service.mesh_props(dict(_MESH))
    shutil.rmtree(tmp_path / "cache" / _DATASET)  # the index still names it

    props = await service.mesh_props(dict(_MESH))

    assert len(calls) == 2
    assert props is not None and props["datasetId"] == _DATASET


async def test_an_index_entry_naming_an_unsafe_dataset_id_is_ignored(monkeypatch, tmp_path):
    """A damaged index file must not make the backend read a dataset outside the cache,
    even one that looks complete."""
    import shutil

    _stub_resolver(monkeypatch, tmp_path)
    calls: list[str] = []
    _fake_cached_convert(monkeypatch, tmp_path, calls)
    await service.mesh_props(dict(_MESH))
    shutil.copytree(tmp_path / "cache" / _DATASET, tmp_path / "outside")
    (index,) = (tmp_path / "cache" / ".index").glob("*.json")
    index.write_text(json.dumps({"dataset_id": "../outside"}))

    props = await service.mesh_props(dict(_MESH))

    assert len(calls) == 2
    assert props is not None and props["datasetId"] == _DATASET
