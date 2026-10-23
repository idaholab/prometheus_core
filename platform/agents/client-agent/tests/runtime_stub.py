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

"""Stub the heavy prometheus_api agent runtime for client-agent unit tests.

Importing this module installs a minimal stand-in for ``prometheus_api.agent``
(a2a-sdk / starlette are not needed by the orchestrator logic under test) only
when the real module cannot be imported, so an environment with the agent
runtime (the container) tests against the real one.
"""
from __future__ import annotations

import importlib
import sys
import types
from types import SimpleNamespace


def _importable(name: str) -> bool:
    try:
        importlib.import_module(name)
    except ImportError:
        return False
    return True


if not _importable("prometheus_api.agent"):
    prometheus_api_module = sys.modules.get(
        "prometheus_api", types.ModuleType("prometheus_api")
    )
    agent_api_module = types.ModuleType("prometheus_api.agent")

    class _ArtifactReference:
        def __init__(self, **kwargs):
            self.artifact_id = kwargs.get("artifact_id")
            self.conversation_id = kwargs.get("conversation_id")
            self.name = kwargs.get("name")
            self.description = kwargs.get("description")
            self.uri = kwargs.get("uri")
            self.metadata = kwargs.get("metadata") or {}
            self.json_type = kwargs.get("json_type")
            self.json_body = kwargs.get("json_body")

        @classmethod
        def from_any(cls, artifact, conversation_id=None):
            if not isinstance(artifact, dict):
                return None
            metadata = dict(artifact.get("metadata") or {})
            parts = artifact.get("parts") or []
            uri = artifact.get("uri")
            json_type = artifact.get("json_type")
            json_body = artifact.get("json_body")
            for part in parts:
                if not isinstance(part, dict):
                    continue
                kind = str(part.get("kind") or "").strip().lower()
                if kind == "file":
                    file_payload = part.get("file") or {}
                    uri = file_payload.get("uri") or uri
                elif kind == "data":
                    json_body = part.get("data")
                    part_meta = dict(part.get("metadata") or {})
                    json_type = part_meta.get("json_type") or json_type
                    metadata = {**part_meta, **metadata}
            return cls(
                artifact_id=artifact.get("artifact_id") or artifact.get("artifactId"),
                conversation_id=conversation_id or metadata.get("conversation_id"),
                name=artifact.get("name"),
                description=artifact.get("description"),
                uri=uri,
                metadata=metadata,
                json_type=json_type,
                json_body=json_body,
            )

        def to_dict(self):
            payload = {
                "artifact_id": self.artifact_id,
                "conversation_id": self.conversation_id,
                "name": self.name,
                "description": self.description,
                "uri": self.uri,
                "metadata": self.metadata,
            }
            if self.json_type is not None:
                payload["json_type"] = self.json_type
            if self.json_body is not None:
                payload["json_body"] = self.json_body
            return payload

    class _PrometheusAgent:
        def __init__(self, *args, **kwargs):
            self.artifact_registry = SimpleNamespace(register=lambda reference: None)

        @staticmethod
        def pending_hint(pending_requests, hint):
            return hint

        @staticmethod
        def registry_url() -> str:
            return "http://backend:8000"

        def run(self, *args, **kwargs):
            return None

        def list_artifact_references(self, *args, **kwargs):
            return []

        async def send_status_update(self, *args, **kwargs):
            return None

    agent_api_module.ArtifactReference = _ArtifactReference
    agent_api_module.EventQueue = object
    agent_api_module.PrometheusAgent = _PrometheusAgent
    agent_api_module.RequestContext = object
    prometheus_api_module.agent = agent_api_module
    sys.modules["prometheus_api"] = prometheus_api_module
    sys.modules["prometheus_api.agent"] = agent_api_module
