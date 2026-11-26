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

"""Canonical helpers for nested params and JSON-schema input metadata."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def set_nested_value(data: Dict[str, Any], path: str, value: Any) -> None:
    """Set a dotted-path value inside a dictionary."""
    parts = str(path or "").split(".")
    current = data
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def get_nested_value(data: Any, path: str) -> Any:
    """Get a dotted-path value from a mapping-like structure."""
    if not path:
        return data
    if isinstance(data, dict) and path in data:
        return data[path]

    current = data
    for part in str(path).split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def has_param_path(params: Dict[str, Any], path: str) -> bool:
    """Check whether a parameter path exists and has a non-empty value."""
    if not isinstance(params, dict):
        return False

    if path == "material_id":
        material_ids = params.get("material_ids")
        if isinstance(material_ids, list) and any(str(v).strip() for v in material_ids):
            return True

    value = get_nested_value(params, path)
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def schema_input_source(prop: Dict[str, Any]) -> str:
    """Normalize schema-level input source annotations."""
    if not isinstance(prop, dict):
        return ""
    raw = prop.get("x_input_source") or prop.get("x-input-source") or prop.get("input_source") or ""
    return str(raw).strip().lower()


def is_user_input_schema(prop: Dict[str, Any]) -> bool:
    """Return True when a schema property should be requested from end users."""
    if not isinstance(prop, dict):
        return True
    if bool(prop.get("readOnly")):
        return False
    source = schema_input_source(prop)
    if source in {"runtime", "internal", "derived", "system", "agent"}:
        return False
    return True


def extract_required_param_paths(
    schema: Dict[str, Any],
    prefix: str = "",
    include_internal: bool = False,
) -> List[str]:
    """Extract required dotted parameter paths from a JSON schema."""
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return []
    properties = schema.get("properties", {}) or {}
    required = schema.get("required", []) or []
    paths: List[str] = []
    for field in required:
        field_path = f"{prefix}{field}"
        field_schema = properties.get(field, {})
        if not include_internal and not is_user_input_schema(field_schema):
            continue
        is_object = isinstance(field_schema, dict) and (
            field_schema.get("type") == "object" or "properties" in field_schema
        )
        if is_object:
            nested_paths = extract_required_param_paths(
                field_schema,
                prefix=f"{field_path}.",
                include_internal=include_internal,
            )
            if nested_paths:
                paths.extend(nested_paths)
            elif include_internal:
                paths.append(field_path)
        else:
            paths.append(field_path)
    return paths


def flatten_schema_properties(
    schema: Dict[str, Any],
    prefix: str = "",
) -> Dict[str, Dict[str, Any]]:
    """Flatten JSON-schema properties into dotted-path -> property schema map."""
    result: Dict[str, Dict[str, Any]] = {}
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return result

    for name, prop in (schema.get("properties", {}) or {}).items():
        path = f"{prefix}{name}"
        if isinstance(prop, dict):
            result[path] = prop
            is_object = prop.get("type") == "object" or "properties" in prop
            if is_object:
                result.update(flatten_schema_properties(prop, prefix=f"{path}."))
    return result


def normalize_params_for_input_schema(
    params: Dict[str, Any],
    input_schema: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Convert dotted keys into the nested structure expected by input schemas."""
    normalized: Dict[str, Any] = {}

    for key, value in (params or {}).items():
        if "." not in key:
            normalized[key] = value

    for key, value in (params or {}).items():
        if "." not in key or value is None:
            continue
        set_nested_value(normalized, key, value)

    return normalized
