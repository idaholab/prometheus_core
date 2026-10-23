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

"""Secret redaction helpers."""

from __future__ import annotations

import re
from typing import Any

SECRET_FIELD_FRAGMENTS = (
    "api_key",
    "llm_api_key",
    "authorization",
    "token",
    "secret",
    "password",
)
REDACTED = "[REDACTED]"

_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api_key|llm_api_key|authorization|token|secret|password)\b"
    r"(\s*[:=]\s*)([^,\s;]+)"
)


def _is_secret_key(key: Any) -> bool:
    normalized = str(key).strip().lower()
    return any(fragment in normalized for fragment in SECRET_FIELD_FRAGMENTS)


def redact_secrets(value: Any) -> Any:
    """Recursively redact common secret-bearing fields from debug payloads."""
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            redacted[key_text] = REDACTED if _is_secret_key(key_text) else redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(item) for item in value)
    if isinstance(value, str):
        return _SECRET_ASSIGNMENT_RE.sub(r"\1\2[REDACTED]", value)
    return value
