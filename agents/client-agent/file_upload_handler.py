"""User-uploaded file ingestion: description inference and DeepLynx storage.

On each request that carries `uploaded_files`, the orchestrator calls
`infer_file_descriptions` (one LLM call) to produce a description for every
file, then `upload_files_to_deeplynx` to store them and register artifact
references.  The resulting artifact IDs are tracked as
`newly_uploaded_artifact_ids` in the conversation context for the current turn
so the planner can surface them with an ephemeral prefix and `resolve_artifact_inputs`
can auto-bind them to skill parameters.

See docs/dev-docs/file-uploads.md for the full workflow description.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from pydantic import BaseModel

if TYPE_CHECKING:
    from prometheus_api.agent import ArtifactReference, EventQueue, RequestContext
    from prometheus_api.storage_client.connection import ConnectionConfig

MAX_UPLOAD_BYTES_ENV = "PROMETHEUS_MAX_UPLOAD_BYTES"
DEFAULT_MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def configured_max_upload_bytes() -> int:
    raw_value = os.getenv(MAX_UPLOAD_BYTES_ENV)
    if raw_value is None or not raw_value.strip():
        return DEFAULT_MAX_UPLOAD_BYTES
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{MAX_UPLOAD_BYTES_ENV} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{MAX_UPLOAD_BYTES_ENV} must be positive")
    return value


MAX_UPLOAD_BYTES = configured_max_upload_bytes()
STAGED_UPLOAD_TTL_SECONDS = 24 * 60 * 60
_UPLOAD_ID_RE = re.compile(r"^[a-f0-9]{32}$")


class UploadedFile(BaseModel):
    name: str
    mime_type: str
    size_bytes: int
    upload_id: str  # Server-side staged upload token


def staged_upload_dir() -> Path:
    """Return the server-local directory used for staged upload bytes."""
    root = os.getenv("PROMETHEUS_STAGED_UPLOAD_DIR")
    if root:
        return Path(root)
    return Path(tempfile.gettempdir()) / "prometheus-staged-uploads"


def new_staged_upload_id() -> str:
    return uuid.uuid4().hex


def staged_upload_paths(upload_id: str) -> tuple[Path, Path]:
    """Return data and metadata paths for a staged upload ID."""
    token = str(upload_id or "")
    if not _UPLOAD_ID_RE.fullmatch(token):
        raise ValueError("Invalid staged upload ID")
    root = staged_upload_dir()
    return root / f"{token}.bin", root / f"{token}.json"


def write_staged_upload_metadata(upload_id: str, metadata: Dict[str, Any]) -> None:
    _, meta_path = staged_upload_paths(upload_id)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def read_staged_upload_metadata(upload_id: str) -> Dict[str, Any]:
    _, meta_path = staged_upload_paths(upload_id)
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Staged upload {upload_id} was not found") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Staged upload {upload_id} metadata is invalid")
    return payload


def consume_staged_upload(upload_id: str) -> None:
    """Delete a staged upload after it has been persisted or rejected."""
    data_path, meta_path = staged_upload_paths(upload_id)
    for path in (data_path, meta_path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def cleanup_stale_staged_uploads(max_age_seconds: int = STAGED_UPLOAD_TTL_SECONDS) -> None:
    """Best-effort cleanup for staged uploads abandoned before the A2A turn."""
    root = staged_upload_dir()
    if not root.exists():
        return
    cutoff = time.time() - max(0, int(max_age_seconds))
    for path in root.glob("*"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except Exception:
            pass


def _normalize_mime_type(mime_type: str | None) -> str:
    return (mime_type or "").split(";", 1)[0].strip().lower()


def resolve_staged_upload(uploaded_file: UploadedFile, user_id: Optional[str] = None) -> Path:
    """Validate request metadata for a staged upload and return the byte path.

    When *user_id* is provided, the upload is rejected if it was created by a
    different user, preventing cross-user upload retrieval.
    """
    source_path, _ = staged_upload_paths(uploaded_file.upload_id)
    metadata = read_staged_upload_metadata(uploaded_file.upload_id)
    if not source_path.exists():
        raise FileNotFoundError(f"Staged upload {uploaded_file.upload_id} file is missing")

    # Cross-user upload retrieval prevention: reject if a different user_id
    # staged this upload.  Skip the check when either side has no user_id
    # (dev mode or legacy uploads without a stamped owner).
    staged_user_id = metadata.get("user_id") or ""
    if user_id and staged_user_id and staged_user_id != user_id:
        raise PermissionError(
            f"Staged upload {uploaded_file.upload_id} was created by a different user"
        )

    actual_size = source_path.stat().st_size
    if actual_size > MAX_UPLOAD_BYTES:
        raise ValueError(f"{uploaded_file.name} exceeds the {MAX_UPLOAD_BYTES} byte upload limit")
    if actual_size != uploaded_file.size_bytes:
        raise ValueError(f"Staged upload {uploaded_file.upload_id} size does not match request")

    if metadata.get("name") and metadata.get("name") != uploaded_file.name:
        raise ValueError(f"Staged upload {uploaded_file.upload_id} name does not match request")

    staged_mime = _normalize_mime_type(metadata.get("mime_type"))
    request_mime = _normalize_mime_type(uploaded_file.mime_type)
    if staged_mime and request_mime and staged_mime != request_mime:
        raise ValueError(f"Staged upload {uploaded_file.upload_id} MIME type does not match request")

    return source_path


# ---------------------------------------------------------------------------
# MIME → human-readable label
# ---------------------------------------------------------------------------

_EXACT_MIME_LABELS: Dict[str, str] = {
    "application/pdf": "PDF document",
    "application/json": "JSON data file",
    "text/csv": "CSV data file",
    "text/plain": "text file",
    "text/markdown": "Markdown document",
    "text/yaml": "YAML configuration file",
    "application/yaml": "YAML configuration file",
    "image/jpeg": "JPEG image",
    "image/png": "PNG image",
    "image/gif": "GIF image",
    "image/svg+xml": "SVG image",
    "image/webp": "WebP image",
    "image/tiff": "TIFF image",
    "application/zip": "ZIP archive",
    "application/gzip": "gzip archive",
    "application/x-tar": "tar archive",
    "application/x-hdf5": "HDF5 data file",
    "application/vnd.ms-excel": "Excel spreadsheet",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel spreadsheet",
}

_EXT_LABELS: Dict[str, str] = {
    ".e": "Exodus mesh file",
    ".exo": "Exodus mesh file",
    ".exodus": "Exodus mesh file",
    ".inp": "ABAQUS/Cubit input file",
    ".i": "MOOSE input file",
    ".yaml": "YAML configuration file",
    ".yml": "YAML configuration file",
    ".json": "JSON data file",
    ".csv": "CSV data file",
    ".txt": "text file",
    ".md": "Markdown document",
    ".pdf": "PDF document",
    ".h5": "HDF5 data file",
    ".hdf5": "HDF5 data file",
    ".nc": "NetCDF data file",
    ".vtu": "VTK unstructured grid file",
    ".vtp": "VTK polydata file",
    ".vtk": "VTK data file",
    ".stl": "STL geometry file",
    ".obj": "OBJ geometry file",
    ".step": "STEP CAD file",
    ".stp": "STEP CAD file",
    ".ifc": "IFC building model file",
    ".png": "PNG image",
    ".jpg": "JPEG image",
    ".jpeg": "JPEG image",
    ".svg": "SVG image",
    ".tif": "TIFF image",
    ".tiff": "TIFF image",
}


def mime_type_label(mime_type: str, filename: str = "") -> str:
    """Return a human-readable file type label from a MIME type and optional filename."""
    mime = (mime_type or "").lower().strip()

    if mime in _EXACT_MIME_LABELS:
        return _EXACT_MIME_LABELS[mime]

    ext = Path(filename).suffix.lower() if filename else ""
    if ext in _EXT_LABELS:
        return _EXT_LABELS[ext]

    if mime.startswith("image/"):
        return "image file"
    if mime.startswith("video/"):
        return "video file"
    if mime.startswith("audio/"):
        return "audio file"
    if mime.startswith("text/"):
        return "text file"
    if mime.startswith("application/"):
        subtype = mime.split("/", 1)[1].lstrip("x-").replace("-", " ").replace("_", " ")
        if subtype:
            return f"{subtype} file"

    return "file"


# ---------------------------------------------------------------------------
# Description inference
# ---------------------------------------------------------------------------

async def infer_file_descriptions(
    query: str,
    files: List[UploadedFile],
    llm: Any,
) -> Dict[str, str]:
    """Return {filename: description} for every uploaded file.

    The LLM is instructed to always produce a non-empty description.  When
    the query provides rich context it is used; otherwise the description is
    synthesised from the filename and MIME type alone.
    """
    file_list = "\n".join(
        f"- {f.name} ({mime_type_label(f.mime_type, f.name)}, {f.size_bytes:,} bytes)"
        for f in files
    )
    prompt = (
        "The user uploaded the following file(s) together with a query.\n\n"
        f"Files:\n{file_list}\n\n"
        f"User query: {query!r}\n\n"
        "For each file, write one concise sentence describing what it likely contains "
        "and why it was uploaded.  Use the query for context when it is informative; "
        "otherwise synthesise a description from the filename and file type alone "
        "(e.g. \"MOOSE Exodus mesh file for reactor core geometry.\").\n"
        "Always produce a non-empty string — never output null.\n\n"
        "Respond ONLY with a JSON object mapping each exact filename to its description:\n"
        '{"filename1": "description", "filename2": "description", ...}'
    )
    response = await llm.medium(prompt, temperature=0, max_tokens=4096)
    text = response.text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            out: Dict[str, str] = {}
            for f in files:
                desc = result.get(f.name)
                out[f.name] = str(desc).strip() if desc else _fallback_description(f)
            return out
    except Exception:
        pass
    # If parsing fails fall back for all files
    return {f.name: _fallback_description(f) for f in files}


def _fallback_description(f: UploadedFile) -> str:
    label = mime_type_label(f.mime_type, f.name)
    return f"User-uploaded {label}: {f.name}"


# ---------------------------------------------------------------------------
# DeepLynx upload
# ---------------------------------------------------------------------------

async def upload_files_to_deeplynx(
    agent: Any,
    files: List[UploadedFile],
    descriptions: Dict[str, str],
    context: "RequestContext",
    event_queue: "EventQueue",
    storage_config: "ConnectionConfig",
    user_id: Optional[str] = None,
) -> List["ArtifactReference"]:
    """Resolve each staged file, upload to DeepLynx, and return refs."""
    refs = []
    for f in files:
        description = descriptions.get(f.name) or _fallback_description(f)
        try:
            source_path = resolve_staged_upload(f, user_id=user_id)

            ref = await agent.send_deeplynx_artifact(
                context=context,
                event_queue=event_queue,
                file_path=source_path,
                name=f.name,
                description=description,
                storage_config=storage_config,
                mime_type=f.mime_type,
                tags=["user-upload"],
                metadata={"original_filename": f.name, "source": "user-upload"},
            )
            refs.append(ref)
        except Exception as exc:
            print(f"[WARN] Failed to upload {f.name!r} to DeepLynx: {exc}")
        finally:
            try:
                consume_staged_upload(f.upload_id)
            except Exception:
                pass
    return refs
