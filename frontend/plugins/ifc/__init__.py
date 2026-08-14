"""IFC 3D building model visualization plugin."""

import tempfile
from pathlib import Path
from typing import Any, Optional

import httpx

from plugins import (
    GENERIC_UPLOAD_MIMETYPES,
    UploadContext,
    UploadMatch,
    UploadRenderResult,
    normalize_mime_type,
)

MIMETYPES = ["model/ifc", "application/ifc"]
UPLOAD_EXTENSIONS = [".ifc"]
COMPONENT_NAME = "IFCViewer"
_IFC_STEP_MIMETYPES = {"model/step", "application/step", "application/x-step", "text/plain"}


def _resolve_path(uri: str) -> Optional[Path]:
    if uri.startswith("file://"):
        return Path(uri[7:])
    if uri and not uri.startswith("http"):
        p = Path(uri)
        if p.exists():
            return p
    return None


async def inspect_upload(context: UploadContext) -> UploadMatch | None:
    """Identify IFC STEP physical files from MIME, extension, and contents."""
    normalized = normalize_mime_type(context.mime_type)
    if normalized in MIMETYPES:
        return UploadMatch(mime_type=normalized, confidence=90, reason="declared IFC MIME")

    should_inspect = (
        normalized in GENERIC_UPLOAD_MIMETYPES
        or normalized in _IFC_STEP_MIMETYPES
        or context.suffix in UPLOAD_EXTENSIONS
    )
    if not should_inspect:
        return None

    try:
        with context.file_path.open("rb") as stream:
            sample = stream.read(512)  # ISO-10303-21 header always appears within the first few lines
    except Exception:
        return None

    text = sample.decode("latin-1", errors="ignore").upper()
    if "ISO-10303-21" in text and "FILE_SCHEMA" in text and "IFC" in text:
        confidence = 80 if context.suffix in UPLOAD_EXTENSIONS else 70
        return UploadMatch(
            mime_type=MIMETYPES[0],
            confidence=confidence,
            reason="IFC STEP header",
        )
    return None


def _user_ifc_output_dir(dataset_id: str) -> "Optional[Path]":
    """Return a per-user namespaced output directory for this IFC dataset."""
    try:
        import chainlit as cl
        from utils.settings import settings
        user_id: Optional[str] = cl.user_session.get("user_id")
        if user_id:
            return settings.ifc_data_dir / user_id / dataset_id
    except Exception:
        pass
    return None


async def render_artifact(artifact: dict) -> Optional[Any]:
    uri = artifact.get("uri") or ""
    name = artifact.get("name", "model.ifc")

    file_path = _resolve_path(uri)
    if file_path and file_path.exists():
        from components.ifc_integration import process_ifc_upload
        import uuid as _uuid
        output_dir = _user_ifc_output_dir(str(_uuid.uuid4())[:8])
        dataset = await process_ifc_upload(file_path, output_dir=output_dir)
        return dataset.to_chainlit_element()

    if uri.startswith("http"):
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(uri)
            response.raise_for_status()
        with tempfile.TemporaryDirectory(prefix="ifc-artifact-") as tmp_dir:
            tmp_path = Path(tmp_dir) / Path(name).name
            tmp_path.write_bytes(response.content)
            from components.ifc_integration import process_ifc_upload
            import uuid as _uuid
            output_dir = _user_ifc_output_dir(str(_uuid.uuid4())[:8])
            dataset = await process_ifc_upload(tmp_path, output_dir=output_dir)
        return dataset.to_chainlit_element()

    return None


async def process_upload(context: UploadContext) -> UploadRenderResult:
    from components.ifc_integration import process_ifc_upload, format_file_size
    import uuid as _uuid
    output_dir = _user_ifc_output_dir(str(_uuid.uuid4())[:8])
    dataset = await process_ifc_upload(context.file_path, output_dir=output_dir)
    desc = f"**IFC model loaded:** {context.display_name} ({format_file_size(dataset.file_size)})"
    return UploadRenderResult(desc, [dataset.to_chainlit_element()])
