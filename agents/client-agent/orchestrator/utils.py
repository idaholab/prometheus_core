from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from param_schema import set_nested_value


def extract_json_from_text(text: str):
    """Extract JSON from text that may contain markdown code blocks or extra text.

    Returns: Parsed JSON (can be dict, list, or other JSON type) or None
    """
    import re

    # Try to find JSON in code blocks first (objects or arrays)
    json_match = re.search(r'```json\s*(\{.*?\}|\[.*?\])\s*```', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find raw JSON array
    json_match = re.search(r'\[.*\]', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    # Try to find raw JSON object
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def extract_material_ids_from_text(text: str) -> List[str]:
    """Extract material identifiers like SS316/ss347 from free text."""
    if not text:
        return []
    ids: List[str] = []

    def add(material_id: str) -> None:
        normalized = material_id.upper().replace(" ", "")
        if normalized and normalized not in ids:
            ids.append(normalized)

    # SS316, ss347, SS 316, SS-316L
    for match in re.finditer(r"\bss[\s-]*(\d{3}[a-z]?)\b", text, flags=re.IGNORECASE):
        add(f"SS{match.group(1)}")

    # Stainless steel 316 / stainless steel 347
    for match in re.finditer(r"\bstainless\s+steel\s*(\d{3}[a-z]?)\b", text, flags=re.IGNORECASE):
        add(f"SS{match.group(1)}")

    return ids


def enrich_material_params(query: str, extracted_params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Infer and normalize material parameters from query and extracted params."""
    params = dict(extracted_params or {})

    candidate_texts: List[str] = [query or ""]
    material_id = params.get("material_id")
    if isinstance(material_id, str):
        candidate_texts.append(material_id)
    material_ids = params.get("material_ids")
    if isinstance(material_ids, list):
        candidate_texts.extend(str(value) for value in material_ids if value is not None)

    inferred: List[str] = []
    for text in candidate_texts:
        for parsed in extract_material_ids_from_text(text):
            if parsed not in inferred:
                inferred.append(parsed)

    if inferred:
        params["material_ids"] = inferred
        params["material_id"] = inferred[0]

    return params


def extract_result_text(result_data: Any) -> str:
    """Extract human-readable text from common agent response formats."""
    if isinstance(result_data, dict):
        for key in ("answer", "response", "report", "message", "result", "raw_response"):
            value = result_data.get(key)
            if isinstance(value, str) and value.strip():
                return value
            if value and not isinstance(value, (dict, list)):
                return str(value)
        return json.dumps(result_data, indent=2)
    return str(result_data)


def normalize_suggested_queries(raw: Any, limit: int = 3) -> List[Dict[str, str]]:
    """Normalize suggested query payloads into UI-friendly metadata entries."""
    if not isinstance(raw, list):
        return []

    results: List[Dict[str, str]] = []
    seen = set()
    for item in raw:
        if isinstance(item, dict):
            query = str(item.get("suggested_query") or item.get("query") or "").strip()
        else:
            query = str(item or "").strip()
        if not query:
            continue
        key = query.lower()
        if key in seen:
            continue
        seen.add(key)
        results.append({"suggested_query": query})
        if len(results) >= limit:
            break
    return results


def collect_suggested_queries(tool_results: Dict[str, Any], limit: int = 3) -> List[Dict[str, str]]:
    """Collect deduplicated suggested queries from skill result payloads."""
    merged: List[Dict[str, str]] = []
    seen = set()
    for result_data in tool_results.values():
        if not isinstance(result_data, dict):
            continue
        for suggestion in normalize_suggested_queries(result_data.get("suggested_queries"), limit=limit):
            query = suggestion.get("suggested_query", "")
            key = query.lower()
            if not query or key in seen:
                continue
            seen.add(key)
            merged.append({"suggested_query": query})
            if len(merged) >= limit:
                return merged
    return merged


def build_comparison_summary(user_query: str, by_material: Dict[str, Any]) -> Optional[str]:
    """Build deterministic comparison text for common comparison queries."""
    if not by_material or len(by_material) < 2:
        return None
    q = (user_query or "").lower()

    if "temperature" in q and ("max" in q or "maximum" in q):
        rows = []
        for material_id, result in by_material.items():
            data = result.get("material_data", {}) if isinstance(result, dict) else {}
            env = data.get("operating_environment", {}) if isinstance(data, dict) else {}
            temp_range = env.get("temperature_range_c")
            max_temp = None
            if isinstance(temp_range, list) and len(temp_range) >= 2:
                max_temp = temp_range[1]
            rows.append((material_id, max_temp))

        known = [r for r in rows if r[1] is not None]
        if not known:
            return None
        known.sort(key=lambda item: item[1], reverse=True)

        lines = ["Comparison (maximum operating temperature):"]
        for material_id, max_temp in known:
            lines.append(f"- {material_id}: {max_temp} C")
        if len(known) >= 2:
            delta = known[0][1] - known[-1][1]
            lines.append(f"Difference between highest and lowest: {delta} C")
        return "\n".join(lines)

    return None


def normalize_by_mode(value: Any, mode: Optional[str]) -> Any:
    """Normalize values based on a metadata-specified mode."""
    if mode == "upper_no_space_hyphen" and isinstance(value, str):
        return value.upper().replace(" ", "").replace("-", "")
    return value


def get_value_by_path(data: Any, path: Optional[str]) -> Any:
    """Read dotted path from dict/list structures, supporting numeric list indexes."""
    if not path:
        return data
    current = data
    for token in path.split("."):
        if isinstance(current, dict):
            if token not in current:
                return None
            current = current[token]
            continue
        if isinstance(current, list):
            if not token.isdigit():
                return None
            idx = int(token)
            if idx < 0 or idx >= len(current):
                return None
            current = current[idx]
            continue
        return None
    return current


def set_param_path(params: Dict[str, Any], path: str, value: Any) -> None:
    """Set a derived parameter on both dotted and nested forms."""
    if "." in path:
        set_nested_value(params, path, value)
    params[path] = value


def rule_matches_query(query: str, rule: Dict[str, Any]) -> bool:
    """Check metadata rule query conditions."""
    when = rule.get("when", {})
    if not isinstance(when, dict):
        return True
    phrases_any = when.get("phrases_any")
    if not phrases_any:
        return True
    q = (query or "").lower()
    return any(str(phrase).lower() in q for phrase in phrases_any)
