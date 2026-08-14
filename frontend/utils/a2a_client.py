"""
A2A JSON-RPC client for communicating with the client-agent.
"""
import asyncio
import json
import shutil
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Coroutine, Dict, List, Literal, Optional, Union

import httpx

# Shared A2A stream consumption (SSE/NDJSON parsing, heartbeats, artifact merge).
from prometheus_api.a2a_stream import consume_stream_response

# Canonical wire contract shared with the client-agent. Re-exported here so
# frontend modules keep importing ConversationResponse from utils.a2a_client.
from prometheus_api.contract import (  # noqa: F401
    ConversationResponse,
    ConversationStatus,
)


def response_from_payload(data: Dict[str, Any]) -> ConversationResponse:
    """Build a ConversationResponse from a client-agent response payload dict.

    Shared by the streaming parser and the background-task notifier (which
    renders a persisted result payload after a detached turn completes)."""
    return ConversationResponse.from_payload(data)


@dataclass(frozen=True)
class ChatProgressEvent:
    """One lifecycle status emitted while the client-agent handles a turn."""

    message: str
    kind: Literal["progress"] = "progress"


@dataclass(frozen=True)
class ChatFinalEvent:
    """The terminal typed response for a streamed chat turn."""

    response: ConversationResponse
    kind: Literal["final"] = "final"


ChatEvent = Union[ChatProgressEvent, ChatFinalEvent]


class A2AClient:
    """Async client for the A2A JSON-RPC protocol used by client-agent."""

    def __init__(self, agent_url: str, agent_secret: str, timeout: float = 900.0):
        self.agent_url = agent_url.rstrip("/")
        self.agent_secret = agent_secret
        self.timeout = timeout

    @property
    def _auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.agent_secret}"}

    def start_chat(
        self,
        conversation_id: Optional[str] = None,
        user_token: Optional[str] = None,
    ) -> "ChatSession":
        """Create a stateful local handle for one platform conversation."""
        return ChatSession(self, conversation_id or str(uuid.uuid4()), user_token=user_token)

    async def list_artifacts(self, conversation_id: str) -> List[Dict[str, Any]]:
        """Return artifact references for one conversation."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.agent_url}/api/artifacts/{conversation_id}",
                headers=self._auth_headers,
            )
            response.raise_for_status()
            payload = response.json()
        artifacts = payload.get("artifacts") if isinstance(payload, dict) else None
        if not isinstance(artifacts, list):
            raise ValueError("Artifact catalog response did not include an artifact list")
        return [item for item in artifacts if isinstance(item, dict)]

    async def download_artifact(
        self,
        artifact: Dict[str, Any],
        destination: Path,
    ) -> Path:
        """Materialize an artifact reference at an explicit local destination."""
        target = Path(destination)
        if target.exists():
            raise FileExistsError(f"Artifact destination already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.part")

        try:
            if artifact.get("json_body") is not None:
                content = (json.dumps(artifact["json_body"], indent=2) + "\n").encode("utf-8")
                await asyncio.to_thread(temporary.write_bytes, content)
            elif artifact.get("text_body") is not None:
                await asyncio.to_thread(
                    temporary.write_text,
                    str(artifact["text_body"]),
                    "utf-8",
                )
            else:
                uri = str(artifact.get("uri") or "").strip()
                if uri.startswith("http://") or uri.startswith("https://"):
                    async with httpx.AsyncClient(timeout=self.timeout) as client:
                        async with client.stream("GET", uri) as response:
                            response.raise_for_status()
                            with temporary.open("wb") as stream:
                                async for chunk in response.aiter_bytes():
                                    stream.write(chunk)
                elif uri.startswith("file://") or uri.startswith("/"):
                    source = Path(uri[7:] if uri.startswith("file://") else uri)
                    if not source.is_file():
                        raise FileNotFoundError(f"Artifact file does not exist: {source}")
                    await asyncio.to_thread(shutil.copyfile, source, temporary)
                elif uri.startswith("deeplynx://"):
                    from .uri_resolver import resolve_to_local_path

                    source = await resolve_to_local_path(
                        uri,
                        cache_dir=target.parent / ".prometheus-artifact-cache",
                        artifact=artifact,
                        artifact_id=artifact.get("artifact_id"),
                    )
                    if source is None:
                        raise FileNotFoundError(f"Could not resolve artifact URI: {uri}")
                    await asyncio.to_thread(shutil.copyfile, source, temporary)
                else:
                    raise ValueError("Artifact has no downloadable content or supported URI")

            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    async def stage_upload(
        self,
        file_path: Path,
        *,
        name: str,
        mime_type: str,
        conversation_id: str,
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
            raise ValueError(
                "Malformed A2A v1 response: task.status.message.parts must contain one part"
            )
        part = parts[0]
        if not isinstance(part, dict):
            raise ValueError("Malformed A2A v1 response: status part must be an object")
        unexpected = set(part) - {"text", "metadata", "filename", "mediaType"}
        if unexpected:
            raise ValueError(
                f"Malformed A2A v1 response: unsupported status part fields {sorted(unexpected)}"
            )
        text = part.get("text")
        if not isinstance(text, str):
            raise ValueError("Malformed A2A v1 response: status Part.text must be a string")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "Malformed client-agent response: status Part.text must contain JSON"
            ) from exc
        if not isinstance(data, dict) or "status" not in data:
            raise ValueError(
                "Malformed client-agent response: final payload must be an object with status"
            )
        return self._dict_to_response(data)

    def _dict_to_response(self, data: Dict) -> ConversationResponse:
        """Convert a dict to ConversationResponse."""
        return response_from_payload(data)


class ChatSession:
    """Stateful Python interface for submitting and streaming chat turns."""

    def __init__(self, client: A2AClient, conversation_id: str, user_token: Optional[str] = None):
        self._client = client
        self.conversation_id = conversation_id
        self._artifacts: List[Dict[str, Any]] = []
        self._user_token = user_token

    @property
    def artifacts(self) -> List[Dict[str, Any]]:
        return list(self._artifacts)

    async def submit(
        self,
        prompt: str,
        *,
        followup_answers: Optional[Dict] = None,
        plan_approved: bool = False,
        plan_rejected: bool = False,
        on_status: Optional[Callable[[str], Coroutine]] = None,
        user_token: Optional[str] = None,
    ) -> ConversationResponse:
        """Submit one turn and return its terminal response."""
        response = await self._client.send(
            query=prompt,
            conversation_id=self.conversation_id,
            artifacts=self._artifacts,
            followup_answers=followup_answers,
            plan_approved=plan_approved,
            plan_rejected=plan_rejected,
            on_status=on_status,
            user_token=user_token or self._user_token,
        )
        if response.artifacts is not None:
            self._artifacts = list(response.artifacts)
        return response

    async def stream(
        self,
        prompt: str,
        *,
        followup_answers: Optional[Dict] = None,
        plan_approved: bool = False,
        plan_rejected: bool = False,
    ) -> AsyncIterator[ChatEvent]:
        """Submit one turn and yield lifecycle statuses followed by one final event."""
        queue: asyncio.Queue = asyncio.Queue()
        finished = object()

        async def on_status(message: str) -> None:
            await queue.put(ChatProgressEvent(message=message))

        async def run_turn() -> ConversationResponse:
            try:
                return await self.submit(
                    prompt,
                    followup_answers=followup_answers,
                    plan_approved=plan_approved,
                    plan_rejected=plan_rejected,
                    on_status=on_status,
                )
            finally:
                await queue.put(finished)

        task = asyncio.create_task(run_turn())
        try:
            while True:
                event = await queue.get()
                if event is finished:
                    break
                yield event
            yield ChatFinalEvent(response=await task)
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    async def list_artifacts(self) -> List[Dict[str, Any]]:
        """Refresh and return this conversation's artifact catalog."""
        self._artifacts = await self._client.list_artifacts(self.conversation_id)
        return self.artifacts

    async def download_artifact(self, artifact_id: str, destination: Path) -> Path:
        """Download one catalog artifact by ID."""
        artifact = next(
            (
                item
                for item in self._artifacts
                if str(item.get("artifact_id") or "") == artifact_id
            ),
            None,
        )
        if artifact is None:
            await self.list_artifacts()
            artifact = next(
                (
                    item
                    for item in self._artifacts
                    if str(item.get("artifact_id") or "") == artifact_id
                ),
                None,
            )
        if artifact is None:
            raise KeyError(f"Artifact '{artifact_id}' is not in this conversation")
        return await self._client.download_artifact(artifact, destination)
