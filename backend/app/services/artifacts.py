"""Artifact catalog → wire metadata shaping + render-hint classification (task 07).

The turn orchestrator (task 04) calls :func:`to_artifact_meta` to shape each raw
catalog dict from ``ConversationResponse`` into the frozen :class:`ArtifactMeta`
wire shape, and :func:`shape_artifacts` to build the list for a completed turn.

:func:`classify_render_hint` derives the frontend viewer hint. It combines the
intent of the two Chainlit classifiers — the plugin dispatch order in
``frontend/plugins/__init__.py`` (json_type → mime → extension) and the MIME
fallback ``_classify_artifact`` (message_handler.py:849) — plus the tag table in
``docs/docs/dev-docs/artifacts.md``. The hint values are aligned 1:1 with the
React ``ElementKind`` artifact subset (``frontend/src/lib/chainlit/elements.ts``).

The plugin trigger constants are **re-declared here** (copied verbatim from each
``frontend/plugins/<name>/__init__.py``) rather than imported, so the backend
stays decoupled from the Chainlit ``plugins`` package (task ground rule: port,
don't couple).

:func:`artifact_download_payload` serializes inline-only artifact content
(``json_body`` / text) for the content proxy, ported from
``_artifact_download_payload`` (message_handler.py:978).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from app.contract import ArtifactMeta, Citation, RenderHint

# --------------------------------------------------------------------------- #
# Classifier trigger tables — copied verbatim from frontend/plugins/<name>/__init__.py
# --------------------------------------------------------------------------- #

# json_type (highest-priority signal; mirrors _json_type_registry dispatch).
_THERMAL_JSON_TYPE = "prometheus.thermal_analysis.result.v1"

# Tag → hint (docs/docs/dev-docs/artifacts.md:161-167). Checked before MIME.
_TAG_HINTS: dict[str, RenderHint] = {
    "ifc": "ifc",
    "exodus": "mesh",
    "stl": "mesh",
    "vtk": "mesh",
    "mermaid": "mermaid",
    "reference": "reference",
    "citation": "reference",
    "pdf": "pdf",
    "data": "json",
    "image": "image",
}

_IFC_MIMETYPES = {"model/ifc", "application/ifc"}
_MESH_MIMETYPES = {
    "application/x-exodus",
    "application/exodus",
    # Exodus container MIMEs the old exodus inspector recognized (T-6): an upload
    # stored with its container type (not refined to x-exodus, since inspect_upload
    # is dropped) still classifies as mesh instead of falling to unknown/file.
    "application/x-hdf5",
    "application/x-netcdf",
    "application/netcdf",
    "model/stl",
    "application/stl",
    "application/x-stl",
    "application/sla",
    "application/vnd.ms-pki.stl",
    "model/x.stl-binary",
    "model/x.stl-ascii",
}
_MERMAID_MIMETYPES = {"text/x-mermaid", "application/vnd.mermaid", "text/mermaid"}
_IMAGE_MIMETYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/gif",
    "image/webp",
    "image/svg+xml",
}
_JSON_MIMETYPES = {"application/json"}
# Markdown / plain-text → inline-rendered report (old _classify_artifact "report"
# branch, message_handler.py:855). Kept out of _FILE_MIMETYPES so these render
# inline rather than downloading (A-1).
_REPORT_MIMETYPES = {"text/markdown", "text/plain"}
# Source / config text → inline-rendered, syntax-highlighted source (not Markdown:
# comments/indentation would mangle). Maps MIME → the extension used when inline text is
# served without a file name. Keep in step with MIME_LANGUAGES in
# frontend/src/lib/highlight/index.ts. ``application/json`` is deliberately absent: it
# keeps the interactive JSON tree viewer.
# text/x-moose is a vendor type (not IANA-registered) for MOOSE input files; agents may
# set it so a MOOSE input without a ".i" name still routes to the source viewer.
_CODE_MIME_EXTENSIONS: dict[str, str] = {
    "application/yaml": ".yaml",
    "application/x-yaml": ".yaml",
    "text/yaml": ".yaml",
    "text/x-yaml": ".yaml",
    "text/x-moose": ".i",
    "application/toml": ".toml",
    "application/xml": ".xml",
    "text/xml": ".xml",
    "text/x-python": ".py",
    "text/x-script.python": ".py",
    "application/x-python": ".py",
    "text/x-c": ".c",
    "text/x-csrc": ".c",
    "text/x-chdr": ".h",
    "text/x-c++src": ".cpp",
    "text/x-c++hdr": ".hpp",
    "text/x-fortran": ".f90",
    "text/x-cmake": ".cmake",
    "text/x-makefile": ".mk",
    "application/x-sh": ".sh",
    "text/x-shellscript": ".sh",
    "text/x-dockerfile": ".dockerfile",
    "application/sql": ".sql",
    "text/x-sql": ".sql",
    "text/javascript": ".js",
    "application/javascript": ".js",
    "application/typescript": ".ts",
    "text/x-typescript": ".ts",
    "text/x-diff": ".diff",
    "text/x-patch": ".patch",
}
_CODE_MIMETYPES = set(_CODE_MIME_EXTENSIONS)
# CSV / TSV → inline table viewer. Maps MIME → download extension (used when inline text
# is served without a file name). Keep in step with the delimiter handling in
# frontend/src/lib/table/csv.ts.
_TABLE_MIME_EXTENSIONS: dict[str, str] = {
    "text/csv": ".csv",
    "application/csv": ".csv",
    "text/tab-separated-values": ".tsv",
}
_TABLE_MIMETYPES = set(_TABLE_MIME_EXTENSIONS)
# CAD step MIMEs (message_handler.py:33) + archives → downloadable file. CSV is not
# here: it has its own table viewer (the JSONViewer can't parse it — A-9).
_FILE_MIMETYPES = {
    "application/octet-stream",
    "application/zip",
    "application/gzip",
    "model/step",
    "model/step+xml",
    "model/step+zip",
    "application/step",
    "application/x-step",
    "application/step+xml",
    "application/step+zip",
    "application/x-ipynb+json",
}

# Extension → hint (UPLOAD_EXTENSIONS across plugins + the download list in
# artifacts.md:166; used as a fallback when json_type/mime don't match).
_EXTENSION_HINTS: dict[str, RenderHint] = {
    ".ifc": "ifc",
    ".exo": "mesh",
    ".e": "mesh",
    ".stl": "mesh",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".webp": "image",
    ".svg": "image",
    ".pdf": "pdf",
    ".json": "json",
    ".csv": "table",  # A-9: not the JSONViewer; rendered by the table viewer
    ".tsv": "table",
    ".md": "report",
    ".i": "code",  # MOOSE input file (HIT/GetPot syntax)
    **{
        ext: "code"
        for ext in (
            ".yaml", ".yml", ".jsonc", ".toml", ".ini", ".cfg", ".conf",
            ".xml", ".xsd", ".xdmf", ".xmf",
            ".py", ".pyi",
            ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx",
            ".f", ".f90", ".f95", ".f03", ".f08", ".for",
            ".cmake", ".mk", ".dockerfile",
            ".sh", ".bash", ".zsh",
            ".sql",
            ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".mts",
            ".diff", ".patch",
            ".txt", ".log",
        )
    },
    ".inp": "file",  # ambiguous (Abaqus/MCNP/etc.) — stays a download
    ".zip": "file",
    ".tar": "file",
    ".gz": "file",
    ".ipynb": "file",
    ".xlsx": "file",
}

# Well-known source files identified by their whole file name rather than an extension.
# Checked before the extension, so ``CMakeLists.txt`` is cmake, not plain text.
_BASENAME_HINTS: dict[str, RenderHint] = {
    name: "code"
    for name in (
        "Dockerfile",
        "Containerfile",
        "Makefile",
        "makefile",
        "GNUmakefile",
        "CMakeLists.txt",
    )
}
# ``.txt`` / ``.log`` only route to ``code`` when nothing else decided. Agent text parts
# default to the name ``artifact.txt`` (prometheus_api ArtifactReference), so letting
# them override a text/plain or text/markdown MIME would pull every plain agent reply
# out of the report viewer.
_PLAINTEXT_EXTENSIONS = {".txt", ".log"}


def _is_conversation_message(artifact: dict[str, Any]) -> bool:
    """Whether an artifact is the internal conversation-transcript record.

    Ported from the two skip checks in ``render_artifacts``
    (message_handler.py:723-726): ``metadata.kind == "conversation_message"`` or
    ``name == "conversation_message"``. These are not user-facing artifacts.
    """
    metadata = artifact.get("metadata") or {}
    return metadata.get("kind") == "conversation_message" or artifact.get("name") == "conversation_message"


def _normalize_mime(mime: Optional[str]) -> str:
    """Strip parameters and lowercase a MIME value (matches plugin normalization)."""
    return (mime or "").split(";", 1)[0].strip().lower()


def artifact_identity(artifact: dict[str, Any]) -> str:
    """Stable, non-empty id for an artifact (A-4).

    Prefers the explicit ``artifact_id`` / ``id``. When neither is present (id-less
    inline artifacts), derives a deterministic synthetic id from the artifact's
    distinguishing fields so it is still routable via
    ``GET /api/artifacts/{id}/content`` and doesn't collide with other id-less
    artifacts. Both :func:`to_artifact_meta` (wire) and the content route's catalog
    lookup call this, so the frontend's id round-trips to the same raw dict.
    """
    explicit = str(artifact.get("artifact_id") or artifact.get("id") or "")
    if explicit:
        return explicit
    basis = "|".join(
        str(artifact.get(key) or "") for key in ("uri", "name", "json_type")
    )
    basis += "|" + repr(artifact.get("json_body"))
    return "art-" + hashlib.sha256(basis.encode("utf-8", "replace")).hexdigest()[:16]


def _extension_hint(artifact: dict[str, Any], *, include_plaintext: bool = True) -> Optional[RenderHint]:
    """Render hint from the file name of ``uri``, then ``name``, or ``None``.

    A well-known whole file name (``Dockerfile``) wins over the extension. With
    ``include_plaintext=False`` the generic ``.txt`` / ``.log`` extensions are ignored.
    """
    for source in (artifact.get("uri"), artifact.get("name")):
        if not source:
            continue
        path = Path(str(source))
        hint = _BASENAME_HINTS.get(path.name)
        if hint is not None:
            return hint
        suffix = path.suffix.lower()
        if not include_plaintext and suffix in _PLAINTEXT_EXTENSIONS:
            continue
        hint = _EXTENSION_HINTS.get(suffix)
        if hint is not None:
            return hint
    return None


def classify_render_hint(artifact: dict[str, Any]) -> RenderHint:
    """Derive the frontend ``render_hint`` for one artifact.

    First match wins, in this order:

    1. ``json_type`` — explicit semantic type (highest priority).
    2. **Specific** ``mime_type`` (ifc/mesh/mermaid/image/pdf/json/code/table/report).
    3. ``tags`` — explicit routing hints.
    4. file ``extension`` (of ``uri`` or ``name``).
    5. **Generic downloadable** ``mime_type`` (octet-stream/zip/step).
    6. a bare-``json_body`` fallback.

    A concrete MIME outranks tags (A-2): an artifact tagged ``data`` but typed
    ``application/pdf`` is a PDF, not JSON. But the *generic* download MIMEs are
    checked only after tags/extension, so an Exodus mesh tagged ``exodus`` yet stored
    as ``application/octet-stream`` still routes to ``mesh``. Returns ``"unknown"``
    when nothing matches so the frontend can fall back to raw fields.
    """
    metadata = artifact.get("metadata") or {}

    # 1. json_type — explicit semantic type (highest priority).
    json_type = artifact.get("json_type") or metadata.get("json_type")
    if json_type == _THERMAL_JSON_TYPE:
        return "thermal"

    # 2. specific mime_type — outranks tags.
    mime = _normalize_mime(artifact.get("mime_type"))
    if mime:
        if mime in _IFC_MIMETYPES:
            return "ifc"
        if mime in _MESH_MIMETYPES:
            return "mesh"
        if mime in _MERMAID_MIMETYPES:
            return "mermaid"
        if mime in _IMAGE_MIMETYPES:
            return "image"
        if mime == "application/pdf":
            return "pdf"
        if mime in _JSON_MIMETYPES:
            return "json"
        if mime in _CODE_MIMETYPES:
            return "code"
        if mime in _TABLE_MIMETYPES:
            return "table"
        if mime in _REPORT_MIMETYPES:
            # A source file mislabeled text/plain still gets the source viewer, not
            # Markdown (which would mangle its comments/indentation), and a CSV/TSV
            # mislabeled text/plain still gets the table viewer. Generic .txt/.log
            # names don't count: they'd capture every plain-text reply.
            hint = _extension_hint(artifact, include_plaintext=False)
            return hint if hint in ("code", "table") else "report"

    # 3. tags — explicit routing hints (only when a specific MIME didn't decide).
    tags = artifact.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            hint = _TAG_HINTS.get(str(tag).strip().lower())
            if hint is not None:
                return hint

    # 4. extension — of the URI first, then the name.
    hint = _extension_hint(artifact)
    if hint is not None:
        return hint

    # 5. generic downloadable MIME — after tags/extension so it can't mask a tag.
    if mime in _FILE_MIMETYPES:
        return "file"

    # 6. inline JSON with no other signal.
    if artifact.get("json_body") is not None:
        return "json"

    return "unknown"


def artifact_download_payload(
    artifact: dict[str, Any],
    mime_type: str = "",
) -> Optional[tuple[bytes, str, str]]:
    """Serialize inline artifact content for the content proxy (task 07).

    Ports ``_artifact_download_payload`` (message_handler.py:978): a ``json_body``
    becomes pretty-printed ``.json``; otherwise ``text_body`` (even when empty), or the
    first non-empty ``content`` / ``text`` / ``description``, is served with an
    extension chosen by MIME (``.yaml``, ``.i``, ``.py``, ...), ``.md``
    (markdown), or ``.txt``. Returns ``(bytes, extension, mime_type)`` or ``None`` when
    there is nothing inline to serve.
    """
    if artifact.get("json_body") is not None:
        content = json.dumps(artifact["json_body"], indent=2).encode("utf-8")
        return content + b"\n", ".json", "application/json"

    effective_mime = mime_type or "text/plain"
    normalized = _normalize_mime(effective_mime)
    if normalized == "text/markdown":
        extension = ".md"
    else:
        extension = _CODE_MIME_EXTENSIONS.get(normalized) or _TABLE_MIME_EXTENSIONS.get(normalized, ".txt")

    # ``text_body`` is the catalog's inline-text field. Check it by presence, not
    # truthiness: an empty file is still a file and must serve as 200 / zero bytes
    # rather than falling through to ``description``.
    text_body = artifact.get("text_body")
    if text_body is not None:
        return str(text_body).encode("utf-8"), extension, effective_mime

    for key in ("content", "text", "description"):
        value = artifact.get(key)
        if value:
            return str(value).encode("utf-8"), extension, effective_mime

    return None


def _citation_from(metadata: dict[str, Any]) -> Optional[Citation]:
    """Build a :class:`Citation` from an artifact's ``metadata`` (CON-1).

    Reads the same ``source`` / ``section`` / ``page`` keys the old inline citation
    renderer used (message_handler.py:1005-1007). Returns ``None`` unless at least
    one is present, so non-reference artifacts stay clean on the wire. ``page`` is
    coerced to ``str`` (agents emit it as either int or string).
    """
    source = metadata.get("source")
    section = metadata.get("section")
    page = metadata.get("page")
    if not (source or section or page):
        return None
    return Citation(
        source=str(source) if source else None,
        section=str(section) if section else None,
        page=str(page) if page else None,
    )


def to_artifact_meta(artifact: dict[str, Any]) -> Optional[ArtifactMeta]:
    """Map one raw catalog dict to :class:`ArtifactMeta`, or ``None`` to skip it.

    Returns ``None`` for ``conversation_message`` records (not user-facing) and
    for non-dict inputs, so callers can ``filter``/``None``-drop the result.
    """
    if not isinstance(artifact, dict):
        return None
    if _is_conversation_message(artifact):
        return None

    metadata = artifact.get("metadata") or {}
    tags = artifact.get("tags")
    return ArtifactMeta(
        artifact_id=artifact_identity(artifact),
        name=str(artifact.get("name") or ""),
        mime_type=artifact.get("mime_type"),
        json_type=artifact.get("json_type") or metadata.get("json_type"),
        description=str(artifact.get("description") or ""),
        uri=artifact.get("uri"),
        tags=list(tags) if isinstance(tags, list) else [],
        json_body=artifact.get("json_body"),
        render_hint=classify_render_hint(artifact),
        citation=_citation_from(metadata),
        producer_agent_id=artifact.get("producer_agent_id"),
        created_at=artifact.get("created_at"),
    )


def is_user_upload(artifact: dict[str, Any]) -> bool:
    """True for a file the user uploaded (``metadata.source == "user-upload"``).

    The Prometheus Artifact Contract keeps these in the catalog but excludes them from
    response rendering, so both the live turn and a restored transcript drop them.
    """
    return (artifact.get("metadata") or {}).get("source") == "user-upload"


def shape_artifacts(artifacts: list[dict[str, Any]]) -> list[ArtifactMeta]:
    """Shape a list of raw catalog dicts, dropping skipped/invalid entries."""
    shaped: list[ArtifactMeta] = []
    for artifact in artifacts:
        meta = to_artifact_meta(artifact)
        if meta is not None:
            shaped.append(meta)
    return shaped
