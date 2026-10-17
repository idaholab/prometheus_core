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

"""
A2A JSON-RPC client for communicating with the client-agent.
"""

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

import httpx

# Shared A2A stream consumption (SSE/NDJSON parsing, heartbeats, artifact merge).
from prometheus_api.a2a_stream import consume_stream_response

# Canonical wire contract shared with the client-agent. Re-exported here so
# callers keep importing ConversationResponse from app.a2a_client.
from prometheus_api.contract import (  # noqa: F401
    ConversationResponse,
    ConversationStatus,
)


def response_from_payload(data: Dict[str, Any]) -> ConversationResponse:
    """Build a ConversationResponse from a client-agent response payload dict.

    Shared by the streaming parser and the background-task notifier (which
    renders a persisted result payload after a detached turn completes)."""
    return ConversationResponse.from_payload(data)


class A2AClient:
    """Async client for the A2A JSON-RPC protocol used by client-agent."""

    def __init__(self, agent_url: str, agent_secret: str, timeout: float = 900.0):
        self.agent_url = agent_url.rstrip("/")
        self.agent_secret = agent_secret
        self.timeout = timeout

    async def stage_upload(
        self,
        file_path: Path,
        *,
        name: str,
        mime_type: str,
        conversation_id: str,
        user_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Stream upload bytes to the client-agent and return a staged upload token."""
        path = Path(file_path)
        headers = {
            "Content-Type": mime_type or "application/octet-stream",
            "Content-Length": str(path.stat().st_size),
            "Authorization": f"Bearer {self.agent_secret}",
        }
        params = {
            "name": name,
            "mime_type": mime_type or "application/octet-stream",
            "conversation_id": conversation_id,
        }
        if user_token:
            params["user_token"] = user_token

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.agent_url}/uploads/stage",
                params=params,
                headers=headers,
                content=self._file_chunks(path),
            )
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict) or not payload.get("upload_id"):
            raise ValueError("Upload staging response did not include upload_id")
        return payload

    async def get_llm_model(self) -> Optional[str]:
        """Return the provider model behind the orchestrator's flavor, or ``None``."""
        headers = {"Authorization": f"Bearer {self.agent_secret}"}
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{self.agent_url}/llm/model", headers=headers)
            response.raise_for_status()
            payload = response.json()
        model = payload.get("model") if isinstance(payload, dict) else None
        return model if isinstance(model, str) and model else None

    async def _file_chunks(self, file_path: Path, chunk_size: int = 1024 * 1024):
        with Path(file_path).open("rb") as stream:
            while True:
                chunk = await asyncio.to_thread(stream.read, chunk_size)
                if not chunk:
                    break
                yield chunk

    async def send(
        self,
        query: str,
        conversation_id: str,
        artifacts: Optional[List[Dict]] = None,
        followup_answers: Optional[Dict] = None,
        plan_approved: Optional[bool] = False,
        plan_rejected: Optional[bool] = False,
        workflow_id: Optional[str] = None,
        uploaded_files: Optional[List[Dict]] = None,
        on_status: Optional[Callable[[str], Coroutine]] = None,
        user_token: Optional[str] = None,
    ) -> ConversationResponse:
        """Send a message to the client-agent via A2A JSON-RPC streaming."""
        request_id = str(uuid.uuid4())
        message_id = str(uuid.uuid4())

        # Build the inner payload (ConversationRequest fields)
        payload: Dict[str, Any] = {
            "query": query,
            "conversation_id": conversation_id,
        }
        if artifacts:
            payload["artifacts"] = artifacts
        if followup_answers:
            payload["followup_answers"] = followup_answers
        if plan_approved:
            payload["plan_approved"] = True
        if plan_rejected:
            payload["plan_rejected"] = True
        if workflow_id:
            payload["workflow_id"] = workflow_id
        if uploaded_files:
            payload["uploaded_files"] = uploaded_files

        # Build message-level metadata.  The verified user token is carried
        # here so agents can extract and validate the caller's identity.
        message_metadata: Dict[str, Any] = {}
        if user_token:
            message_metadata["userToken"] = user_token

        # A2A JSON-RPC envelope
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "SendStreamingMessage",
            "params": {
                "message": {
                    "messageId": message_id,
                    "role": "ROLE_USER",
                    # contextId is the A2A-spec conversation scope; the a2a-sdk
                    # exposes it to the client-agent as RequestContext.context_id.
                    "contextId": conversation_id,
                    "metadata": message_metadata,
                    "parts": [
                        {
                            "text": json.dumps(payload),
                        }
                    ],
                },
                "configuration": {"returnImmediately": False},
            },
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/x-ndjson",
            "A2A-Version": "1.0",
            "Authorization": f"Bearer {self.agent_secret}",
        }

        result = await self._stream_request(message, headers, on_status=on_status)

        return self._parse_response(result)

    async def _stream_request(
        self,
        message: Dict[str, Any],
        headers: Dict[str, str],
        *,
        on_status: Optional[Callable[[str], Coroutine]] = None,
    ) -> Dict[str, Any]:
        """Stream A2A events and return a blocking-style JSON-RPC result."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                self.agent_url,
                json=message,
                headers=headers,
            ) as response:
                response.raise_for_status()
                a2a_result = await consume_stream_response(
                    response,
                    status_callback=on_status,
                )

        return {"result": a2a_result}

    def _parse_response(self, result: Dict[str, Any]) -> ConversationResponse:
        """Parse A2A JSON-RPC response into ConversationResponse.

        Expects the canonical final response in result.status.message.parts[].
        """
        a2a_result = result.get("result", {})

        return self._extract_from_status(a2a_result)

    def _extract_from_status(self, a2a_result: Dict) -> ConversationResponse:
        """Extract ConversationResponse from one exact A2A v1 Part.text."""
        status = a2a_result.get("status")
        if not isinstance(status, dict):
            raise ValueError("Malformed A2A v1 response: task.status must be an object")
        message = status.get("message")
        if not isinstance(message, dict):
            raise ValueError("Malformed A2A v1 response: task.status.message must be an object")
        parts = message.get("parts")
        if not isinstance(parts, list) or len(parts) != 1:
            raise ValueError("Malformed A2A v1 response: task.status.message.parts must contain one part")
        part = parts[0]
        if not isinstance(part, dict):
            raise ValueError("Malformed A2A v1 response: status part must be an object")
        unexpected = set(part) - {"text", "metadata", "filename", "mediaType"}
        if unexpected:
            raise ValueError(f"Malformed A2A v1 response: unsupported status part fields {sorted(unexpected)}")
        text = part.get("text")
        if not isinstance(text, str):
            raise ValueError("Malformed A2A v1 response: status Part.text must be a string")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("Malformed client-agent response: status Part.text must contain JSON") from exc
        if not isinstance(data, dict) or "status" not in data:
            raise ValueError("Malformed client-agent response: final payload must be an object with status")
        return self._dict_to_response(data)

    def _dict_to_response(self, data: Dict) -> ConversationResponse:
        """Convert a dict to ConversationResponse."""
        return response_from_payload(data)
