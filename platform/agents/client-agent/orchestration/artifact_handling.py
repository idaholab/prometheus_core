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

"""Conversation artifact catalog helpers and artifact-reference schema metadata."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

ARTIFACT_REF_KEYS = ("x_artifact_ref", "x-artifact-ref", "artifact_ref")


def summarize_artifacts_for_context(
    artifacts: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Build compact artifact metadata for the orchestration context."""
    summary: List[Dict[str, Any]] = []
    seen_ids = set()
    for artifact in artifacts or []:
        if not isinstance(artifact, dict):
            continue
        artifact_id = str(artifact.get("artifact_id") or "").strip()
        name = str(artifact.get("name") or "").strip()
        if not artifact_id or not name or artifact_id in seen_ids:
            continue
        seen_ids.add(artifact_id)
        summary.append(
            {
                "artifact_id": artifact_id,
                "name": name,
                "description": str(artifact.get("description") or "")[:280],
                "uri": str(artifact.get("uri") or ""),
                "mime_type": artifact.get("mime_type"),
                "size_bytes": artifact.get("size_bytes"),
                "producer_agent_id": artifact.get("producer_agent_id"),
                "created_at": artifact.get("created_at"),
                "tags": artifact.get("tags") or [],
                "metadata": artifact.get("metadata") or {},
            }
        )
    return summary


def merge_artifacts_into_context(
    existing_context: Optional[Dict[str, Any]],
    artifacts: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Merge artifact catalogs into context without dropping prior entries."""
    merged = dict(existing_context or {})
    current_catalog = summarize_artifacts_for_context((existing_context or {}).get("artifacts"))
    next_catalog = summarize_artifacts_for_context(artifacts)
    existing_ids = {item["artifact_id"] for item in current_catalog}
    combined = current_catalog + [item for item in next_catalog if item["artifact_id"] not in existing_ids]
    if combined:
        merged["artifacts"] = combined
    return merged


def merge_artifact_catalogs(
    existing_artifacts: Optional[List[Dict[str, Any]]],
    incoming_artifacts: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Merge two external artifact catalogs using artifact_id as the key."""
    merged: List[Dict[str, Any]] = []
    seen_ids = set()
    for item in summarize_artifacts_for_context(existing_artifacts) + summarize_artifacts_for_context(
        incoming_artifacts
    ):
        artifact_id = item["artifact_id"]
        if artifact_id in seen_ids:
            continue
        seen_ids.add(artifact_id)
        merged.append(item)
    return merged


def _artifact_binding_mode(prop: Dict[str, Any]) -> Optional[str]:
    for key in ARTIFACT_REF_KEYS:
        raw = prop.get(key)
        if raw is None:
            continue
        text = str(raw).strip().lower()
        if text in {"single", "multiple"}:
            return text
        if text in {"true", "1", "yes"}:
            return "single"
    return None


def extract_artifact_field_paths(
    schema: Dict[str, Any],
    prefix: str = "",
) -> Dict[str, str]:
    """Return dotted artifact-capable field paths declared in an input schema."""
    result: Dict[str, str] = {}
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return result

    for key, prop in (schema.get("properties", {}) or {}).items():
        path = f"{prefix}{key}"
        if not isinstance(prop, dict):
            continue
        mode = _artifact_binding_mode(prop)
        if mode:
            result[path] = mode
        is_object = prop.get("type") == "object" or "properties" in prop
        if is_object:
            result.update(extract_artifact_field_paths(prop, prefix=f"{path}."))
    return result
