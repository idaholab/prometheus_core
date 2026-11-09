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

"""The OpenAPI document the backend serves is valid OpenAPI 3.1.

``tests/test_api_surface.py`` pins what the document says; this checks that it is
well-formed, so client generators and the published API reference can read it.
"""

from __future__ import annotations

import copy
from typing import Any

from fastapi.testclient import TestClient
from openapi_spec_validator import OpenAPIV31SpecValidator

from app.main import app


def _errors(document: dict[str, Any]) -> list[str]:
    return [
        f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
        for e in OpenAPIV31SpecValidator(document).iter_errors()
    ]


def test_served_document_is_valid_openapi_31() -> None:
    response = TestClient(app).get("/openapi.json")
    assert response.status_code == 200
    document = response.json()
    assert document["openapi"].startswith("3.1.")
    errors = _errors(document)
    assert not errors, "The OpenAPI document is invalid:\n" + "\n".join(errors)


def test_invalid_document_is_reported() -> None:
    """A malformed document must fail the check above, so it can't pass vacuously."""
    document = copy.deepcopy(app.openapi())
    # Every response object requires a description
    del document["paths"]["/healthz"]["get"]["responses"]["200"]["description"]
    assert any("'description' is a required property" in e for e in _errors(document))
