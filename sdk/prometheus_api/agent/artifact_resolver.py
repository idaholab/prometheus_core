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

"""Resolve catalog artifacts to local file paths.

Extracted from ``PrometheusAgent`` so artifact materialization (cache layout,
local-file validation, fsspec downloads, inline materialization) lives in one
focused class. ``PrometheusAgent.get_artifact_file_path`` delegates here.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import unquote, urlparse

from .artifacts import ArtifactReference, ArtifactRegistry

logger = logging.getLogger(__name__)


class ArtifactResolver:
    """Resolves artifact references into reachable local file paths.

    URI-backed artifacts are downloaded through fsspec into a deterministic
    cache path, except for ``file://`` artifacts which are validated in place
    against allowed local roots. Inline JSON and text artifacts are
    materialized as UTF-8 cache files so downstream code can consume all
    artifact kinds through one file-path workflow.
    """

    def __init__(self, registry: ArtifactRegistry):
        self._registry = registry

    async def get_artifact_file_path(
        self,
        artifact_id: str,
        *,
        conversation_id: str,
        artifacts: Optional[Sequence[Mapping[str, Any]]] = None,
        cache_dir: Optional[Path] = None,
        allowed_file_roots: Optional[Sequence[Path | str]] = None,
        force_download: bool = False,
    ) -> Path:
        """Resolve an artifact ID to a reachable local file path."""
        reference = self.require_reference(
            artifact_id, conversation_id=conversation_id, artifacts=artifacts
        )
        return await self.get_reference_file_path(
            reference,
            cache_dir=cache_dir,
            allowed_file_roots=allowed_file_roots,
            force_download=force_download,
        )

    def require_reference(
        self,
        artifact_id: str,
        *,
        conversation_id: str,
        artifacts: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> ArtifactReference:
        """Return the catalog reference for *artifact_id*, raising when it is unknown.

        Raises:
            ValueError: When *artifact_id* or *conversation_id* is blank.
            FileNotFoundError: When the conversation has no such artifact.
        """
        normalized_artifact_id = str(artifact_id or "").strip()
        if not normalized_artifact_id:
            raise ValueError("artifact_id is required")
        resolved_conversation_id = str(conversation_id or "").strip()
        if not resolved_conversation_id:
            raise ValueError("conversation_id is required")
        reference = self.resolve_reference(
            normalized_artifact_id,
            conversation_id=resolved_conversation_id,
            artifacts=artifacts,
        )
        if reference is None:
            raise FileNotFoundError(
                f"Artifact '{normalized_artifact_id}' was not found in conversation "
                f"'{resolved_conversation_id}'."
            )
        return reference

    def resolve_reference(
        self,
        artifact_id: str,
        *,
        conversation_id: str,
        artifacts: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> Optional[ArtifactReference]:
        """Return the catalog reference for *artifact_id*, or ``None`` when it is unknown.

        Looks in the conversation's registry first, then in the provided catalog,
        caching a catalog hit in the registry.
        """
        return self._resolve_artifact_for_retrieval(
            conversation_id=conversation_id,
            artifact_id=artifact_id,
            artifacts=artifacts,
        )

    async def get_reference_file_path(
        self,
        reference: ArtifactReference,
        *,
        cache_dir: Optional[Path] = None,
        allowed_file_roots: Optional[Sequence[Path | str]] = None,
        force_download: bool = False,
    ) -> Path:
        """Resolve an already-found artifact reference to a reachable local file path."""
        root = self._artifact_cache_root(cache_dir)
        uri = str(reference.uri or "").strip()
        if uri:
            if self._is_local_file_uri(uri):
                return self._resolve_local_artifact_file(
                    uri,
                    cache_root=root,
                    allowed_file_roots=allowed_file_roots,
                    expected_size=reference.size_bytes,
                )
            return await asyncio.to_thread(
                self._download_artifact_uri_to_cache,
                reference,
                cache_root=root,
                force_download=force_download,
            )

        return self._materialize_inline_artifact(
            reference,
            cache_root=root,
            force_download=force_download,
        )

    def _resolve_artifact_for_retrieval(
        self,
        *,
        conversation_id: str,
        artifact_id: str,
        artifacts: Optional[Sequence[Mapping[str, Any]]],
    ) -> Optional[ArtifactReference]:
        """Resolve a catalog artifact from Redis/memory or a provided catalog."""
        reference = self._registry.resolve_by_id(conversation_id, artifact_id)
        if reference is not None:
            return reference

        for artifact in artifacts or []:
            if not isinstance(artifact, Mapping):
                continue
            candidate_id = str(artifact.get("artifact_id") or "").strip()
            if candidate_id != artifact_id:
                continue
            try:
                reference = ArtifactReference.from_any(
                    dict(artifact),
                    conversation_id=conversation_id,
                )
            except Exception:
                reference = None
            if reference is None:
                continue
            if not reference.conversation_id:
                reference.conversation_id = conversation_id
            try:
                self._registry.register(reference)
            except Exception as exc:
                logger.debug("Failed to cache artifact reference %s: %s", artifact_id, exc)
            return reference

        return None

    @staticmethod
    def _artifact_cache_root(cache_dir: Optional[Path]) -> Path:
        configured = cache_dir or Path(
            os.getenv("PROMETHEUS_ARTIFACT_CACHE_DIR", "/tmp/prometheus-artifact-cache")
        )
        root = Path(configured).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    @staticmethod
    def _is_local_file_uri(uri: str) -> bool:
        parsed = urlparse(uri)
        if parsed.scheme == "file":
            return True
        return parsed.scheme == "" and Path(uri).is_absolute()

    @staticmethod
    def _safe_artifact_filename(name: str, *, fallback: str, suffix: str = "") -> str:
        basename = Path(str(name or "")).name
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", basename).strip("._-")
        if not cleaned:
            cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", fallback).strip("._-")
        if not cleaned:
            cleaned = "artifact"
        if suffix and not Path(cleaned).suffix:
            cleaned = f"{cleaned}{suffix}"
        return cleaned

    @staticmethod
    def _cache_digest(reference: ArtifactReference, inline_bytes: Optional[bytes] = None) -> str:
        payload = {
            "artifact_id": reference.artifact_id,
            "uri": reference.uri,
            "created_at": reference.created_at,
            "size_bytes": reference.size_bytes,
            "json_type": reference.json_type,
            "mime_type": reference.mime_type,
        }
        if inline_bytes is not None:
            payload["inline_sha256"] = hashlib.sha256(inline_bytes).hexdigest()
        raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]

    def _artifact_cache_path(
        self,
        reference: ArtifactReference,
        *,
        cache_root: Path,
        suffix: str = "",
        inline_bytes: Optional[bytes] = None,
    ) -> Path:
        safe_id = self._safe_artifact_filename(reference.artifact_id, fallback="artifact")
        safe_name = self._safe_artifact_filename(
            reference.name,
            fallback=reference.artifact_id,
            suffix=suffix,
        )
        digest = self._cache_digest(reference, inline_bytes=inline_bytes)
        return cache_root / safe_id / f"{digest}-{safe_name}"

    def _allowed_local_file_roots(
        self,
        *,
        cache_root: Path,
        allowed_file_roots: Optional[Sequence[Path | str]],
    ) -> List[Path]:
        raw_roots: List[Path | str] = []
        if allowed_file_roots is not None:
            raw_roots.extend(allowed_file_roots)
        else:
            configured = os.getenv("PROMETHEUS_ARTIFACT_FILE_ALLOWED_ROOTS", "").strip()
            if configured:
                raw_roots.extend(item for item in configured.split(os.pathsep) if item)

        raw_roots.append(cache_root)
        roots: List[Path] = []
        for root in raw_roots:
            try:
                roots.append(Path(root).expanduser().resolve())
            except Exception:
                continue
        return roots

    @staticmethod
    def _ensure_readable_file(path: Path, *, expected_size: Optional[int] = None) -> Path:
        resolved = path.expanduser().resolve(strict=True)
        if not resolved.is_file():
            raise FileNotFoundError(f"Artifact path is not a file: {resolved}")
        try:
            stat = resolved.stat()
            with open(resolved, "rb"):
                pass
        except OSError as exc:
            raise PermissionError(f"Artifact path is not readable: {resolved}") from exc
        if expected_size is not None and stat.st_size != int(expected_size):
            raise ValueError(
                f"Artifact cache size mismatch for {resolved}: "
                f"expected {expected_size}, got {stat.st_size}"
            )
        return resolved

    @staticmethod
    def _is_relative_to(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def _resolve_local_artifact_file(
        self,
        uri: str,
        *,
        cache_root: Path,
        allowed_file_roots: Optional[Sequence[Path | str]],
        expected_size: Optional[int],
    ) -> Path:
        parsed = urlparse(uri)
        if parsed.scheme == "file":
            if parsed.netloc and parsed.netloc not in {"localhost", "127.0.0.1"}:
                raise ValueError(f"Remote file URI hosts are not supported: {uri}")
            candidate = Path(unquote(parsed.path))
        else:
            candidate = Path(uri)

        resolved = self._ensure_readable_file(candidate, expected_size=expected_size)
        allowed_roots = self._allowed_local_file_roots(
            cache_root=cache_root,
            allowed_file_roots=allowed_file_roots,
        )
        if not any(self._is_relative_to(resolved, root) for root in allowed_roots):
            configured_hint = "PROMETHEUS_ARTIFACT_FILE_ALLOWED_ROOTS"
            raise PermissionError(
                f"Local artifact path is outside allowed roots: {resolved}. "
                f"Configure {configured_hint} or pass allowed_file_roots."
            )
        return resolved

    def _download_artifact_uri_to_cache(
        self,
        reference: ArtifactReference,
        *,
        cache_root: Path,
        force_download: bool,
    ) -> Path:
        uri = str(reference.uri or "").strip()
        destination = self._artifact_cache_path(reference, cache_root=cache_root)
        if destination.exists() and not force_download:
            try:
                return self._ensure_readable_file(
                    destination,
                    expected_size=reference.size_bytes,
                )
            except ValueError:
                pass

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            import fsspec

            fs, path = fsspec.core.url_to_fs(uri)
            fs.get(path, str(temporary))
            os.replace(temporary, destination)
            return self._ensure_readable_file(
                destination,
                expected_size=reference.size_bytes,
            )
        except Exception:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise

    def _materialize_inline_artifact(
        self,
        reference: ArtifactReference,
        *,
        cache_root: Path,
        force_download: bool,
    ) -> Path:
        if reference.json_body is not None:
            content = json.dumps(reference.json_body, indent=2, sort_keys=True).encode("utf-8")
            suffix = ".json"
        elif reference.text_body is not None:
            content = str(reference.text_body).encode("utf-8")
            suffix = ".txt"
        else:
            raise ValueError(
                f"Artifact '{reference.artifact_id}' has neither a URI nor inline content."
            )

        destination = self._artifact_cache_path(
            reference,
            cache_root=cache_root,
            suffix=suffix,
            inline_bytes=content,
        )
        if destination.exists() and not force_download:
            return self._ensure_readable_file(destination, expected_size=len(content))

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(content)
            os.replace(temporary, destination)
            return self._ensure_readable_file(destination, expected_size=len(content))
        except Exception:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise
