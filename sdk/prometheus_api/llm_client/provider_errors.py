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

"""Turn LLM provider error responses into short, readable messages."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .security import redact_secrets

MAX_DETAIL_CHARS = 300

_HTML_RE = re.compile(r"^\s*(<!--.*?-->\s*)*<(!doctype\s+html|html)\b", re.IGNORECASE | re.DOTALL)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
# LiteLLM prefixes provider text with e.g. "litellm.APIError: APIError: OpenAIException - ".
_LITELLM_PREFIX_RE = re.compile(r"^litellm\.\w+:\s*(\w+:\s*)?\w*Exception\s*-\s*")
_BEARER_RE = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]+")


def _clip(text: str) -> str:
    text = " ".join(text.split())
    if len(text) > MAX_DETAIL_CHARS:
        return text[: MAX_DETAIL_CHARS - 1].rstrip() + "…"
    return text


def _from_mapping(body: dict[str, Any]) -> str | None:
    error = body.get("error", body)
    if isinstance(error, str):
        return error
    if not isinstance(error, dict):
        return None
    message = error.get("message") or error.get("detail") or body.get("detail")
    if isinstance(message, (list, dict)):
        message = json.dumps(message, default=str)
    if not message:
        return None
    extras = [f"{key}={error[key]}" for key in ("type", "code") if error.get(key)]
    return f"{message} ({', '.join(extras)})" if extras else str(message)


def summarize_body(body: Any) -> str:
    """One line describing a provider error body (JSON, HTML page, or plain text)."""
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8", errors="replace")
    if isinstance(body, str):
        stripped = body.strip()
        if not stripped:
            return "empty response body"
        if stripped[0] in "{[":
            try:
                return summarize_body(json.loads(stripped))
            except ValueError:
                pass
        if _HTML_RE.match(stripped):
            title = _TITLE_RE.search(stripped)
            name = f" {_clip(title.group(1))!r}" if title and title.group(1).strip() else ""
            return (
                f"HTML page{name} instead of an API response "
                "(often a firewall, proxy, or login page)"
            )
        text = stripped
    elif isinstance(body, dict):
        text = _from_mapping(body) or json.dumps(body, default=str)
    elif body is None:
        return "no response body"
    else:
        text = json.dumps(body, default=str)
    # Redact bearer tokens first: the generic rule would only replace the word "Bearer".
    return _clip(redact_secrets(_BEARER_RE.sub(r"\1[REDACTED]", text)))


def litellm_error_body(exc: BaseException) -> Any:
    """The provider body behind a LiteLLM exception, or its message without LiteLLM's prefix."""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        body = getattr(current, "body", None)
        if body:
            return body
        current = current.__cause__ or current.__context__
    message = str(getattr(exc, "message", "") or exc)
    return _LITELLM_PREFIX_RE.sub("", message)


def format_provider_error(
    *,
    status_code: int,
    detail: str,
    source: str,
    endpoint: str | None,
    alias: str | None,
    provider_model: str | None,
) -> str:
    """The multi-line message carried by ``LLMProviderError``."""
    reason = httpx.codes.get_reason_phrase(status_code)
    lines = [f"LLM request failed: {status_code} {reason}".rstrip()]
    if alias:
        target = f"{alias!r} -> {provider_model}" if provider_model else repr(alias)
        lines.append(f"  alias:    {target}")
    lines.append(f"  config:   {source}")
    if endpoint:
        lines.append(f"  endpoint: {endpoint}")
    lines.append(f"  provider: {detail}")
    return "\n".join(lines)
