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
Stub client-agent for the frontend's end-to-end tests.

It stands in for the real client-agent in the e2e stack (docker-compose.e2e.yml),
so the tests can drive a chat through the real browser, nginx and backend without
an LLM. It speaks the same A2A protocol through PrometheusAgent and answers with
the same ConversationResponse shape, but its answer is fixed instead of reasoned:

- a prompt naming "mesh", "ifc", "diagram" or "json" gets an answer with that viewer
  sample as an artifact, the way a specialist agent's output reaches the user;
- anything else gets the same text answer.

The samples are the shared viewer samples (platform/frontend/e2e/samples), which
the image copies in. The mesh, IFC and JSON samples are served over plain HTTP on
SAMPLES_PORT, and the artifact's uri points there, so the backend downloads them
as it would a real agent's file: it converts the STL to the mesh viewer's VTP
itself, and streams the IFC model and the JSON to the browser through its artifact
content proxy. The JSON goes by uri, not inline, because a stored JSON file once
showed an empty viewer (PPLT-374). The samples are public test files, so that port takes no bearer token; the
A2A port keeps the agent's usual auth. The Mermaid sample travels inline, in
json_body, as Mermaid artifacts do.

Like the real client-agent, it registers each artifact in the conversation's catalog
(``artifacts:conv:{id}:by_id``) before replying, because the backend's
conversation-scoped content route reads the artifact from there.

It skips one step of the SDK's request lifecycle: the execution record every agent
writes to DeepLynx before it runs. The e2e stack has no DeepLynx, and the stub
stores nothing, so there's nothing to record. PPLT-389 will decide how test stacks
should do this; until then the stub replaces create_executor. Everything else (A2A
parsing, bearer auth, the identity token, streaming, finalization) is the SDK's own.
"""

import asyncio
import os
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from prometheus_api.agent import PrometheusAgent
from prometheus_api.agent.base import DelegatingPrometheusAgentExecutor, PrometheusAgentExecutor
from prometheus_api.agent.artifacts import ArtifactReference
from prometheus_api.contract import ConversationResponse, ConversationStatus

SAMPLES_DIR = Path(os.getenv("SAMPLES_DIR", str(Path(__file__).resolve().parent / "samples")))
SAMPLES_PORT = int(os.getenv("SAMPLES_PORT", "8100"))
# How the backend reaches the samples server, on the compose network
SAMPLES_BASE_URL = os.getenv("SAMPLES_BASE_URL", f"http://stub-client-agent:{SAMPLES_PORT}")

# The e2e tests look for these texts, so changing one means changing them too
TEXT_ANSWER = "This is the e2e stub agent. It gives this same answer to every message."
STATUS_MESSAGE = "Stub agent is answering."


@dataclass(frozen=True)
class Sample:
    """One viewer sample and how it reaches the user as an artifact."""

    keyword: str  # a prompt containing this word gets this sample
    filename: str  # in SAMPLES_DIR
    mime_type: str
    answer: str
    inline: bool = False  # Mermaid travels in json_body; the others by uri

    @property
    def path(self) -> Path:
        return SAMPLES_DIR / self.filename


SAMPLES = (
    Sample("mesh", "part.stl", "model/stl", "Here is the mesh."),
    Sample("ifc", "model.ifc", "model/ifc", "Here is the IFC model."),
    Sample("diagram", "diagram.mmd", "text/x-mermaid", "Here is the diagram.", inline=True),
    Sample("json", "results.json", "application/json", "Here are the results."),
)


def pick_sample(query: str) -> Optional[Sample]:
    """The sample a prompt asks for, or None for the text answer."""
    words = query.lower()
    return next((sample for sample in SAMPLES if sample.keyword in words), None)


def artifact_for(sample: Sample, conversation_id: str) -> Dict[str, Any]:
    """The artifact dict the backend expects in new_artifacts and artifacts."""
    artifact: Dict[str, Any] = {
        # Unique per turn, so two turns' artifacts never share a viewer or a cache entry
        "artifact_id": f"e2e-{sample.keyword}-{uuid.uuid4().hex[:12]}",
        "conversation_id": conversation_id,
        "name": sample.filename,
        "description": f"E2E sample {sample.keyword}",
        "mime_type": sample.mime_type,
        "tags": ["e2e", sample.keyword],
        "producer_agent_id": "stub-client-agent",
    }
    if sample.inline:
        artifact["json_body"] = {"diagram": sample.path.read_text(encoding="utf-8")}
    else:
        artifact["uri"] = f"{SAMPLES_BASE_URL}/{sample.filename}"
    return artifact


def answer(query: str, conversation_id: str) -> ConversationResponse:
    """The fixed reply to one prompt."""
    sample = pick_sample(query)
    if sample is None:
        return ConversationResponse(
            conversation_id=conversation_id,
            status=ConversationStatus.ANSWER,
            response_text=TEXT_ANSWER,
        )
    artifact = artifact_for(sample, conversation_id)
    return ConversationResponse(
        conversation_id=conversation_id,
        status=ConversationStatus.ANSWER,
        response_text=sample.answer,
        new_artifacts=[artifact],
        artifacts=[artifact],
    )


class StubClientAgent(PrometheusAgent):
    """Answers chat turns with fixed replies and viewer samples."""

    def create_executor(self) -> PrometheusAgentExecutor:
        """The SDK's executor without the DeepLynx execution record (see the module docstring)."""
        return DelegatingPrometheusAgentExecutor(agent_name=self.agent_name, execute_fn=self._execute)

    async def _execute(
        self,
        params: Dict[str, Any],
        context: RequestContext,
        event_queue: EventQueue,
    ) -> Dict[str, Any]:
        query = str(params.get("query") or "")
        conversation_id = str(params.get("conversation_id") or context.context_id or "")
        # One status update first, so the reply streams in the way a real agent's does
        await self.send_status_update(context=context, event_queue=event_queue, message=STATUS_MESSAGE)
        reply = answer(query, conversation_id)
        for artifact in reply.new_artifacts or []:
            reference = ArtifactReference.from_any(artifact, conversation_id=conversation_id)
            # from_any returns None for a payload with no uri/json_body/text_body; fail
            # here with the sample named, not later as a viewer 404 in the e2e run.
            if reference is None:
                raise ValueError(f"sample artifact {artifact.get('artifact_id')!r} has no content to register")
            self.artifact_registry.register(reference)
        return reply.model_dump(exclude_none=True)


async def serve_samples() -> None:
    """Serve SAMPLES_DIR over plain HTTP so the backend can download the samples."""
    import uvicorn
    from starlette.applications import Starlette
    from starlette.staticfiles import StaticFiles

    app = Starlette()
    app.mount("/", StaticFiles(directory=SAMPLES_DIR))
    config = uvicorn.Config(app, host="0.0.0.0", port=SAMPLES_PORT, log_level="warning")
    await uvicorn.Server(config).serve()


def start_samples_server() -> None:
    """Run serve_samples on a daemon thread, beside the agent's own server."""
    threading.Thread(target=lambda: asyncio.run(serve_samples()), daemon=True).start()


def main() -> None:
    """Start the samples server, then the agent on AGENT_PORT."""
    start_samples_server()
    agent = StubClientAgent(agent_name="Stub Client Agent")
    agent.run(port=int(os.getenv("AGENT_PORT", "8000")))


if __name__ == "__main__":  # pragma: no cover - the container's entry point; main() is tested
    main()
