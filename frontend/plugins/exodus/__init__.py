"""Exodus II mesh visualization plugin."""

from pathlib import Path
from typing import Any, Optional

from plugins import (
    GENERIC_UPLOAD_MIMETYPES,
    UploadContext,
    UploadMatch,
    UploadRenderResult,
    normalize_mime_type,
)

MIMETYPES = ["application/x-exodus", "application/exodus"]
UPLOAD_EXTENSIONS = [".exo", ".e"]
COMPONENT_NAME = "MeshViewer"  # shared VTK viewer (public/elements/MeshViewer.jsx)
_EXODUS_CONTAINER_SIGNATURES = (b"CDF\x01", b"CDF\x02", b"\x89HDF\r\n\x1a\n")
_EXODUS_CONTAINER_MIMETYPES = {"application/x-hdf5", "application/x-netcdf", "application/netcdf"}


def _resolve_path(uri: str) -> Optional[Path]:
    if uri.startswith("file://"):
        return Path(uri[7:])
    if uri and not uri.startswith("http"):
        p = Path(uri)
        if p.exists():
            return p
    return None


def _has_exodus_container_signature(file_path: Path) -> bool:
    try:
        with file_path.open("rb") as stream:
            header = stream.read(16)
    except Exception:
        return False
    return any(header.startswith(signature) for signature in _EXODUS_CONTAINER_SIGNATURES)


async def inspect_upload(context: UploadContext) -> UploadMatch | None:
    """Identify Exodus uploads from MIME, extension, and NetCDF/HDF5 contents."""
    normalized = normalize_mime_type(context.mime_type)
    if normalized in MIMETYPES:
        return UploadMatch(mime_type=normalized, confidence=90, reason="declared Exodus MIME")

    should_inspect = (
        normalized in GENERIC_UPLOAD_MIMETYPES
        or normalized in _EXODUS_CONTAINER_MIMETYPES
        or context.suffix in UPLOAD_EXTENSIONS
    )
    if not should_inspect:
        return None
    if not _has_exodus_container_signature(context.file_path):
        return None

    try:
        from components.exodus_integration import inspect_exodus_file_async

        await inspect_exodus_file_async(context.file_path)
    except Exception:
        return None

    confidence = 80 if normalized in _EXODUS_CONTAINER_MIMETYPES else 70
    if context.suffix in UPLOAD_EXTENSIONS:
        confidence += 10
    return UploadMatch(
        mime_type=MIMETYPES[0],
        confidence=min(confidence, 95),
        reason="Exodus container inspection",
    )


def _user_mesh_output_dir(dataset_id: str) -> "Optional[Path]":
    """Return a per-user namespaced output directory for this dataset.

    When a user_id is available from the Chainlit session, mesh data is placed
    under ``public/mesh-data/{user_id}/{dataset_id}`` rather than the shared
    ``public/mesh-data/{dataset_id}`` path, preventing one user from guessing
    another user's dataset URL.
    """
    try:
        import chainlit as cl
        from utils.settings import settings
        user_id: Optional[str] = cl.user_session.get("user_id")
        if user_id:
            return settings.mesh_data_dir / user_id / dataset_id
    except Exception:
        pass
    return None


async def render_artifact(artifact: dict) -> Optional[Any]:
    file_path = _resolve_path(artifact.get("uri") or "")
    if not file_path or not file_path.exists():
        return None
    from components.exodus_integration import process_exodus_upload
    import uuid as _uuid
    dataset_id = str(_uuid.uuid4())[:8]
    output_dir = _user_mesh_output_dir(dataset_id)
    dataset = await process_exodus_upload(file_path, output_dir=output_dir)
    return dataset.to_chainlit_element()


async def process_upload(context: UploadContext) -> UploadRenderResult:
    from components.exodus_integration import process_exodus_upload
    import uuid as _uuid
    dataset_id = str(_uuid.uuid4())[:8]
    output_dir = _user_mesh_output_dir(dataset_id)
    dataset = await process_exodus_upload(context.file_path, output_dir=output_dir)
    meta = dataset.metadata or {}
    name = context.display_name
    lines = [f"**Exodus mesh loaded:** `{name}`"]
    if meta.get("num_timesteps"):
        lines.append(f"- Timesteps: {meta['num_timesteps']}")
    if meta.get("num_nodes"):
        lines.append(f"- Nodes: {meta['num_nodes']:,}")
    if meta.get("num_elements"):
        lines.append(f"- Elements: {meta['num_elements']:,}")
    all_vars = meta.get("nodal_variables", []) + meta.get("element_variables", [])
    if all_vars:
        lines.append(
            f"- Variables: {', '.join(all_vars[:5])}{'...' if len(all_vars) > 5 else ''}"
        )
    return UploadRenderResult("\n".join(lines), [dataset.to_chainlit_element()])
