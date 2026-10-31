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

"""The local DeepLynx API: health, projects and API keys.

The server runs with authentication disabled, so none of these calls needs credentials. Never prints
a request or response (a response holds the new API key and secret); errors name the status only.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from platformctl.system import http

INTERNAL_URL = "http://deeplynx-server:5000/api/v1"
"""deeplynx-server on the compose network, as the agents and backend reach it."""
ORG_ID = 1
"""The organization DeepLynx's migrations create."""
PROJECT_NAME = "Prometheus"
"""The project the platform uses."""


class DeepLynxError(RuntimeError):
    """A DeepLynx call failed. The message names the step and the HTTP status, never a body."""


class DeepLynx:
    """The DeepLynx API at one base URL, such as `http://localhost:5000/api/v1`."""

    def __init__(self, api: str) -> None:
        """Keep the base URL of the API."""
        self.api = api.rstrip("/")

    def _request(self, method: str, path: str, body: dict | None = None) -> tuple[int | None, object]:
        """Send one request to the API; the status is None when nothing answers."""
        return http.request_json(method, f"{self.api}{path}", body)

    def healthy(self) -> bool:
        """Whether the server reports itself healthy."""
        code, body = self._request("GET", "/health")
        return code == 200 and isinstance(body, dict) and body.get("status") == "healthy"

    def wait_healthy(
        self,
        timeout: float,
        interval: float = 2,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> bool:
        """Whether the server reports healthy within `timeout` seconds."""
        deadline = clock() + timeout
        while True:
            if self.healthy():
                return True
            if clock() >= deadline:
                return False
            sleep(interval)

    def configured(self, env: dict[str, str]) -> bool:
        """Whether `.env` already points at this server with a key it accepts, for a project that exists."""
        key, secret, project = env.get("DEEPLYNX_KEY"), env.get("DEEPLYNX_SECRET"), env.get("DEEPLYNX_PROJECT_ID")
        if env.get("DEEPLYNX_BASE_URL", "").rstrip("/") != INTERNAL_URL or not (key and secret and project):
            return False
        code, _ = self._request("POST", "/oauth/tokens", {"apiKey": key, "apiSecret": secret, "expirationMinutes": 1})
        if code != 200:
            return False
        code, _ = self._request("GET", f"/organizations/{ORG_ID}/projects/{project}")
        return code == 200

    def find_or_create_project(self) -> tuple[int, bool]:
        """The ID of the `PROJECT_NAME` project and whether it was just created."""
        code, projects = self._request("GET", f"/organizations/{ORG_ID}/projects")
        if code != 200 or not isinstance(projects, list):
            raise DeepLynxError(f"Listing the projects returned {_describe(code)}")
        for project in projects:
            if project.get("name") == PROJECT_NAME and not project.get("isArchived"):
                return int(project["id"]), False
        code, project = self._request("POST", f"/organizations/{ORG_ID}/projects", {"name": PROJECT_NAME})
        if code != 200 or not isinstance(project, dict):
            raise DeepLynxError(f"Creating the project returned {_describe(code)}")
        return int(project["id"]), True

    def create_key(self) -> tuple[str, str]:
        """A new API key and secret for the local developer."""
        code, body = self._request("POST", "/oauth/keys")
        if code != 200 or not isinstance(body, dict) or not body.get("apiKey"):
            raise DeepLynxError(f"Creating an API key returned {_describe(code)}")
        return str(body["apiKey"]), str(body["apiSecret"])


def _describe(code: int | None) -> str:
    """`HTTP 500`, or `no answer` when the server did not respond."""
    return "no answer" if code is None else f"HTTP {code}"
