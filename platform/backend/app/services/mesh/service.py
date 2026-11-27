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

"""App-facing mesh enrichment: populate mesh artifacts' ``json_body`` with a VTP manifest.

For every artifact the classifier routes to the ``"mesh"`` render hint, this resolves
the raw Exodus/STL bytes (reusing :func:`app.uri_resolver.resolve_to_local_path`),
converts them to ``.vtp`` timesteps + a manifest off the event loop (in a *subprocess*
pool, content-hash cached), and sets ``json_body`` to the exact prop shape
``frontend/src/viewers/mesh/MeshViewerElement.tsx`` reads. The ``.vtp`` files are served
by ``GET /api/artifacts/mesh/{dataset_id}/{filename}`` (see ``routers/artifacts.py``),
so ``baseUrl`` points there.

On any failure the artifact's ``json_body`` is left unset (``None``) so the frontend
adapter cleanly degrades to a file download — restoring rendering must never break a turn.

IMPORTANT: the VTK-dependent converter modules are imported lazily inside
:func:`_convert_sync` (which runs in a worker subprocess), so importing this module — as
``routers/artifacts.py`` and ``services/chat.py`` both do — never pulls in ``vtk``. The
offline backend test suite has no VTK installed, and with the conversion out-of-process
the web process never imports VTK at all.

WHY A SUBPROCESS AND NOT A THREAD: VTK is a large C++ library reached through Python
bindings. A segfault or an OOM kill inside it takes down the whole interpreter — which,
with a thread pool, is the web process, dropping every in-flight conversation on the
floor (the most plausible source of the unexplained backend restarts seen in dev). In a
child process the same crash costs exactly one artifact: :func:`_enrich_one` catches it
and the frontend adapter degrades that artifact to a file download.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import multiprocessing
import re
import shutil
import tempfile
import uuid
import weakref
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from app import uri_resolver
from app.config import settings
from app.services.artifacts import _normalize_mime, artifact_identity, classify_render_hint

if TYPE_CHECKING:  # avoid importing the prometheus_api contract at runtime
    from app.a2a_client import ConversationResponse

logger = logging.getLogger(__name__)

# URL prefix the VTP-serving route is mounted at; baseUrl = f"{MESH_URL_PREFIX}/{id}".
MESH_URL_PREFIX = "/api/artifacts/mesh"

# STL MIME types (a subset of _MESH_MIMETYPES) that pick the STL reader over Exodus.
_STL_MIMES = {
    "model/stl",
    "application/stl",
    "application/x-stl",
    "application/sla",
    "application/vnd.ms-pki.stl",
    "model/x.stl-binary",
    "model/x.stl-ascii",
}

# Dedicated *process* pool for CPU-bound VTK work. Built lazily so importing this
# module (which routers/artifacts.py and services/chat.py both do at startup) costs
# nothing, and dropped whenever a child dies so the next call rebuilds it.
#
# All access happens from the event-loop thread (every caller is a coroutine and none
# of the accessors await), so the bare global needs no lock.
_vtk_executor: Optional[ProcessPoolExecutor] = None


def _executor() -> ProcessPoolExecutor:
    global _vtk_executor
    if _vtk_executor is None:
        # "spawn", never "fork": forking a live asyncio server — with its selector,
        # its httpx/redis connection pools and its threads — into a child that then
        # loads VTK is undefined behaviour. spawn starts a clean interpreter that
        # imports only what _convert_sync needs.
        #
        # max_tasks_per_child=1 retires each worker after one conversion. VTK does
        # not reliably release memory between datasets, so a long-lived worker
        # ratchets upward until it hits the container limit; a fresh process per
        # conversion bounds that at one mesh. The cost is one spawn + VTK import
        # (order of a second) per conversion, paid only when the content-hash cache
        # misses. Requires Python >= 3.11; the image is 3.13.
        _vtk_executor = ProcessPoolExecutor(
            max_workers=settings.mesh_workers,
            mp_context=multiprocessing.get_context("spawn"),
            max_tasks_per_child=1,
        )
    return _vtk_executor


def _discard_executor(executor: ProcessPoolExecutor, *, kill_children: bool) -> None:
    """Drop ``executor`` so the next :func:`_executor` call builds a fresh one.

    Acts only while ``executor`` is still *the* pool. A conversion names the pool it ran
    on, because by the time it fails that pool may already have been replaced: a timeout
    kills pool A, a new conversion builds pool B, and another job still on A then gets
    ``BrokenProcessPool``. Discarding "whatever is current" there shut down B with
    ``cancel_futures=True`` and cancelled unrelated conversions queued on it.

    A :class:`BrokenProcessPool` poisons the executor for *every* subsequent submit,
    not just the one whose child died, so the pool cannot be reused after a crash —
    it has to be replaced.

    ``kill_children`` is for the timeout path. ``shutdown(cancel_futures=True)``
    cancels work that has not started yet but cannot interrupt a call already running
    in a child, so a wedged VTK conversion would keep burning a core indefinitely.
    Terminating the worker processes is the only way to stop it. That is also why a
    timeout may abort a *different* conversion that happened to be running
    concurrently: it degrades down the same "no mesh data" path as any other failure.
    """
    global _vtk_executor
    if _vtk_executor is not executor:
        return  # already replaced; whoever replaced it dealt with this one
    _vtk_executor = None
    if kill_children:
        # `_processes` is private, so guard it: on a CPython that renames it we still
        # get the cancel-pending-work half below, just not the hard kill.
        for proc in list((getattr(executor, "_processes", None) or {}).values()):
            try:
                if proc.is_alive():
                    proc.kill()
            except Exception:  # pragma: no cover - best-effort teardown
                logger.debug("mesh: could not kill worker %r", proc, exc_info=True)
    executor.shutdown(wait=False, cancel_futures=True)


def shutdown_mesh_executor() -> None:
    """Tear the pool down on app shutdown (called from the ``main.py`` lifespan).

    Without this, spawned workers outlive the server on a graceful stop and the
    container lingers until Docker's kill timeout expires.
    """
    if _vtk_executor is not None:
        _discard_executor(_vtk_executor, kill_children=True)


def mesh_cache_root() -> Path:
    """Directory holding converted ``{dataset_id}/`` VTP sets.

    Configured via ``mesh-cache-dir`` / ``PROMETHEUS_MESH_CACHE_DIR``; defaults to
    ``<tempdir>/prometheus-mesh``. Persistent for the service lifetime (NOT the
    per-request scratch dir the content route uses), since the browser fetches the
    VTP files after the turn completes.
    """
    configured = settings.mesh_cache_dir
    root = Path(configured) if configured else Path(tempfile.gettempdir()) / "prometheus-mesh"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _mesh_kind(name: str, uri: str, mime: str) -> str:
    """Pick ``"stl"`` vs ``"exodus"`` from extension (uri, then name), then MIME."""
    for source in (uri, name):
        if source and Path(str(source)).suffix.lower() == ".stl":
            return "stl"
    if mime in _STL_MIMES:
        return "stl"
    return "exodus"


def _build_json_body(dataset_id: str, manifest: dict, metadata: dict, title: str) -> dict[str, Any]:
    """Assemble the MeshViewer prop shape (ported from old MeshDataset.to_props()).

    Only ``baseUrl`` differs from the old props: it points at the backend VTP route
    instead of Chainlit's ``/public/mesh-data/{id}``.
    """
    variables = manifest.get("variables") or {}
    point_vars = variables.get("point") or []
    cell_vars = variables.get("cell") or []
    initial_variable = point_vars[0] if point_vars else (cell_vars[0] if cell_vars else None)
    return {
        "datasetId": dataset_id,
        "baseUrl": f"{MESH_URL_PREFIX}/{dataset_id}",
        "title": title,
        "metadata": metadata,
        "manifest": manifest,
        "initialTimestep": 0,
        "initialVariable": initial_variable,
        "initialColorPreset": "coolToWarm",
        "height": "500px",
        "showControls": True,
        "allowPicking": True,
    }


def _convert_sync(local_path: Path, cache_root: Path, name: str, uri: str, mime: str) -> tuple[str, dict, dict]:
    """Convert a resolved mesh file to a cached VTP set. Runs in a worker subprocess.

    Returns ``(dataset_id, manifest, metadata)``. VTK is imported lazily here so the
    module import graph stays vtk-free.

    Every argument (``str``, ``Path``) and the whole return value are picklable, which
    is what lets this run out-of-process unchanged. The only channel back to the parent
    besides that tuple is the cache directory on disk, which both sides address by path.
    """
    import json

    if _mesh_kind(name, uri, mime) == "stl":
        from .cache import compute_dataset_id, get_cache_path, is_cached
        from .stl import convert_stl_sync

        dataset_id = compute_dataset_id(local_path, {"type": "stl"})
        output_dir = get_cache_path(cache_root, dataset_id)
        if not is_cached(cache_root, dataset_id):
            convert_stl_sync(local_path, output_dir)
        manifest = json.loads((output_dir / "manifest.json").read_text())
        metadata = json.loads((output_dir / "meta.json").read_text())
        return dataset_id, manifest, metadata

    from .converter import convert_exodus
    from .models import ConvertRequest

    request = ConvertRequest(input_path=local_path, output_dir=cache_root, timestep_mode="all")
    result = convert_exodus(request, cache_root=cache_root)
    manifest = json.loads((result.output_dir / "manifest.json").read_text())
    return result.dataset_id, manifest, result.metadata


# One slot per pool worker, so a job waits here, not in the pool's queue. The timeout
# below then covers running time only: a burst of on-demand views can't time a queued
# job out, and that timeout can't kill conversions that were running fine. Per event
# loop, because an asyncio.Semaphore belongs to the loop it first waits on.
_slots: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = weakref.WeakKeyDictionary()


def _conversion_slots() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    slots = _slots.get(loop)
    if slots is None:
        slots = _slots[loop] = asyncio.Semaphore(settings.mesh_workers)
    return slots


async def _convert_offloop(
    local_path: Path,
    cache_root: Path,
    name: str,
    uri: str,
    mime: str,
    *,
    ident: str,
) -> Optional[tuple[str, dict, dict]]:
    """Run :func:`_convert_sync` in the VTK subprocess pool, bounded by a timeout.

    At most ``settings.mesh_workers`` conversions are submitted at once; the rest wait
    for a slot before their timeout starts.

    Returns ``None`` (having logged) when the conversion could not be completed, which
    the caller turns into an un-enriched artifact. This is the whole "run VTK without
    risking the web process" concern in one place; :func:`_enrich_one` above it only
    resolves the source and stamps the result.

    The two failures worth naming:

    * :class:`BrokenProcessPool` — the worker died (VTK segfault, or the kernel
      OOM-killed it). With the old thread pool this was an interpreter-level crash that
      took every live conversation with it. The pool is poisoned for all later submits,
      so it is dropped and the next call builds a fresh one.
    * timeout — a wedged conversion cannot be cancelled cooperatively, so the workers
      are killed. See :func:`_discard_executor` for why that can also abort a
      concurrent conversion.

    That abort arrives as a :class:`asyncio.CancelledError` — ``shutdown(cancel_futures=
    True)`` cancels the pending future ``run_in_executor`` wrapped — which, unlike a real
    cancellation of this task, must not propagate: it would escape every ``except
    Exception`` above us and fail an unrelated chat turn. ``Task.cancelling()`` tells the
    two apart.
    """
    async with _conversion_slots():
        return await _run_in_pool(local_path, cache_root, name, uri, mime, ident=ident)


async def _run_in_pool(
    local_path: Path, cache_root: Path, name: str, uri: str, mime: str, *, ident: str
) -> Optional[tuple[str, dict, dict]]:
    """One conversion on the pool, holding a slot; see :func:`_convert_offloop`."""
    loop = asyncio.get_running_loop()
    executor = _executor()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(executor, _convert_sync, local_path, cache_root, name, uri, mime),
            timeout=settings.mesh_timeout_seconds,
        )
    except asyncio.CancelledError:
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise  # we are being cancelled; not the pool's doing
        logger.warning(
            "mesh: conversion for artifact %s (%s) was cancelled by a pool teardown",
            ident,
            name or uri,
        )
        return None
    except BrokenProcessPool:
        logger.warning(
            "mesh: conversion worker died for artifact %s (%s); rebuilding the pool",
            ident,
            name or uri,
        )
        _discard_executor(executor, kill_children=False)
        return None
    except asyncio.TimeoutError:
        logger.warning(
            "mesh: conversion exceeded %ss for artifact %s (%s); killing the pool",
            settings.mesh_timeout_seconds,
            ident,
            name or uri,
        )
        _discard_executor(executor, kill_children=True)
        return None


# --------------------------------------------------------------------------- #
# Source index: artifact source -> converted dataset, without download or hashing
# --------------------------------------------------------------------------- #

# Dot-prefixed, so the VTP route (which rejects such segments) never serves it.
_INDEX_DIR = ".index"
# Part of every index key. Bump it when the converter's output changes, and entries
# from older code stop matching instead of pinning a source to their datasets.
CONVERTER_VERSION = "1"
# Dataset ids are compute_dataset_id's 16 hex characters; an index entry naming
# anything else is ignored, so a damaged index file can't point outside the cache.
_DATASET_ID_RE = re.compile(r"^[0-9a-f]{16}$")


def _source_key(artifact: dict[str, Any], uri: str) -> Optional[str]:
    """Stable key for "this artifact's source bytes", or ``None`` when there is none.

    Only a ``deeplynx://`` source names immutable content (uploads are staged there
    too), so only it is indexed. The key holds what the resolver actually downloads:
    the URI plus ``metadata.deeplynx_file_id``, which the resolver prefers over the
    item in the URI, so two artifacts naming one item with different files never share
    an entry. The STL/Exodus choice is part of the key because the same bytes convert
    differently under each. A ``file://`` or ``http(s)://`` source can change under the
    same URI, so it gets no key and is downloaded and content-hashed every time.
    """
    if not uri.startswith("deeplynx://"):
        return None
    file_id = str((artifact.get("metadata") or {}).get("deeplynx_file_id") or "")
    kind = _mesh_kind(str(artifact.get("name") or ""), uri, _normalize_mime(artifact.get("mime_type")))
    basis = f"{CONVERTER_VERSION}|{kind}|{uri}|{file_id}"
    return hashlib.sha256(basis.encode("utf-8", "replace")).hexdigest()[:32]


def _index_path(cache_root: Path, key: str) -> Path:
    return cache_root / _INDEX_DIR / f"{key}.json"


def _read_index(cache_root: Path, key: str) -> Optional[str]:
    """The dataset id recorded for *key*, if any.

    The dataset may since have been evicted; :func:`_props_from_cache` then fails to
    read it and the caller converts again.
    """
    try:
        dataset_id = json.loads(_index_path(cache_root, key).read_text()).get("dataset_id")
    except (OSError, ValueError, AttributeError):
        return None
    return dataset_id if isinstance(dataset_id, str) and _DATASET_ID_RE.match(dataset_id) else None


def _write_index(cache_root: Path, key: str, dataset_id: str) -> None:
    """Record *dataset_id* for *key* atomically (rename), so a reader never sees half a file."""
    path = _index_path(cache_root, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps({"dataset_id": dataset_id}))
        tmp.replace(path)
    except OSError:
        logger.warning("mesh: could not write source index for dataset %s", dataset_id, exc_info=True)


def _props_from_cache(cache_root: Path, dataset_id: str, title: str) -> Optional[dict[str, Any]]:
    """The viewer props of a cached dataset, or ``None`` unless it is usable.

    Usable means: both JSON files parse, the manifest names at least one VTP file and
    the first is on disk, and the mesh isn't recorded as empty. ``None`` sends the
    caller back to a conversion.
    """
    out = cache_root / dataset_id
    try:
        manifest = json.loads((out / "manifest.json").read_text())
        metadata = json.loads((out / "meta.json").read_text())
        first_vtp = out / str(manifest["files"][0]["filename"])
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None
    if not first_vtp.is_file() or metadata.get("num_nodes") == 0:
        return None
    return _build_json_body(dataset_id, manifest, metadata, title)


# One conversion per source at a time, in this process. A second request for the same
# mesh awaits the first one's task instead of downloading and converting it again.
_inflight: dict[str, "asyncio.Task[Optional[dict[str, Any]]]"] = {}


async def mesh_props(artifact: dict[str, Any]) -> Optional[dict[str, Any]]:
    """MeshViewer props for one mesh artifact, converting it on first use.

    ``None`` when the artifact has no URI or the source can't be resolved or converted
    (logged). A ``deeplynx://`` source converted before -- live or on an earlier view --
    is a disk read through the source index, with no download and no hashing; any other
    source is downloaded and content-hashed, which still finds an earlier conversion of
    the same bytes. Concurrent calls for one
    source share a single conversion, which runs as its own task: a caller that gives
    up (a browser that navigated away) doesn't cancel it, so the next view is a hit.
    """
    uri = str(artifact.get("uri") or "")
    if not uri:
        return None
    title = str(artifact.get("name") or "") or "Mesh Viewer"
    cache_root = mesh_cache_root()
    key = _source_key(artifact, uri)

    if key is not None:
        dataset_id = _read_index(cache_root, key)
        if dataset_id is not None:
            props = _props_from_cache(cache_root, dataset_id, title)
            if props is not None:
                return props

    # Without a key, concurrent requests for one URI still share a conversion.
    flight = key or f"uri:{uri}"
    task = _inflight.get(flight)
    if task is None:
        task = asyncio.create_task(_convert_and_index(artifact, uri, cache_root, key))
        _inflight[flight] = task
        task.add_done_callback(lambda _t: _inflight.pop(flight, None))
    props = await asyncio.shield(task)
    return {**props, "title": title} if props is not None else None


async def _convert_and_index(
    artifact: dict[str, Any], uri: str, cache_root: Path, key: Optional[str]
) -> Optional[dict[str, Any]]:
    """The shared task's body: convert, then record the source index entry.

    It writes the index itself, so a conversion whose every caller gave up is still a
    hit next time. It never raises: an unexpected error is logged and becomes ``None``
    (the route's 422), and nothing is left for asyncio to report as unretrieved.
    """
    try:
        props = await _enrich_one(artifact, uri, cache_root)
    except Exception:
        logger.exception("mesh: conversion of %r failed", uri)
        return None
    if props is not None and key is not None:
        _write_index(cache_root, key, str(props["datasetId"]))
    return props


async def _enrich_one(artifact: dict[str, Any], uri: str, cache_root: Path) -> Optional[dict[str, Any]]:
    """Resolve + convert one mesh artifact into its ``json_body``, or ``None`` on failure."""
    ident = artifact_identity(artifact)
    name = str(artifact.get("name") or "")
    mime = _normalize_mime(artifact.get("mime_type"))

    download_dir = Path(tempfile.mkdtemp(prefix="mesh-src-"))
    try:
        local_path = await uri_resolver.resolve_to_local_path(
            uri, cache_dir=download_dir, artifact=artifact, artifact_id=ident
        )
        if local_path is None or not local_path.exists():
            logger.warning("mesh: could not resolve %r for artifact %s", uri, ident)
            return None
        converted = await _convert_offloop(local_path, cache_root, name, uri, mime, ident=ident)
        if converted is None:
            return None
        dataset_id, manifest, metadata = converted
    finally:
        # For file:// sources resolve_to_local_path returns the original path (outside
        # download_dir), so this only cleans up http(s)/deeplynx downloads.
        shutil.rmtree(download_dir, ignore_errors=True)

    return _build_json_body(dataset_id, manifest, metadata, name or "Mesh Viewer")


async def enrich_mesh_artifact_dicts(artifacts: list[dict[str, Any]]) -> None:
    """Populate ``json_body`` for every mesh artifact in *artifacts*, in place.

    The list-based core shared by the live turn (:func:`enrich_mesh_artifacts`, which
    unions a response's ``new_artifacts`` + ``artifacts``) and conversation resume
    (``routers/conversations.py``, which passes the persisted catalog straight from
    Redis). Entries are deduped by identity so each dataset is converted once, and the
    content-hash cache makes any repeat — notably re-rendering a past conversation whose
    meshes were already converted live — free. Failures are swallowed: the artifact
    keeps ``json_body: None`` and the frontend adapter degrades to a file download.
    """
    all_artifacts: list[dict[str, Any]] = [a for a in artifacts if isinstance(a, dict)]
    if not all_artifacts:
        return

    # First occurrence (by identity) of each mesh artifact still needing a body.
    to_convert: dict[str, dict[str, Any]] = {}
    for artifact in all_artifacts:
        ident = artifact_identity(artifact)
        if ident in to_convert:
            continue
        if artifact.get("json_body") is not None:
            continue
        if classify_render_hint(artifact) != "mesh":
            continue
        if not (artifact.get("uri") or ""):
            continue
        to_convert[ident] = artifact

    if not to_convert:
        return

    bodies: dict[str, dict[str, Any]] = {}
    for ident, artifact in to_convert.items():
        try:
            body = await mesh_props(artifact)
        except Exception:
            logger.exception("mesh enrichment failed for artifact %s", ident)
            continue
        if body is not None:
            bodies[ident] = body

    # Apply each computed body to every artifact object sharing that identity.
    for artifact in all_artifacts:
        if artifact.get("json_body") is not None:
            continue
        body = bodies.get(artifact_identity(artifact))
        if body is not None:
            artifact["json_body"] = body


async def enrich_mesh_artifacts(response: "ConversationResponse") -> None:
    """Enrich the mesh artifacts carried by a live turn's *response*, in place.

    Thin wrapper over :func:`enrich_mesh_artifact_dicts`: unions ``new_artifacts``
    (shaped for the wire) and ``artifacts`` (the persisted catalog) — both point at the
    same dicts for a shared artifact, so stamping either is enough.
    """
    await enrich_mesh_artifact_dicts(
        list(getattr(response, "new_artifacts", None) or []) + list(getattr(response, "artifacts", None) or [])
    )
