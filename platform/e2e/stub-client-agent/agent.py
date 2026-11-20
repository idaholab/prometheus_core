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
the same ConversationResponse shape, but its answer is fixed instead of reasoned.

It skips one step of the SDK's request lifecycle: the execution record every agent
writes to DeepLynx before it runs. The e2e stack has no DeepLynx, and the stub
stores nothing, so there's nothing to record. PPLT-389 will decide how test stacks
should do this; until then the stub replaces create_executor. Everything else (A2A
parsing, bearer auth, the identity token, streaming, finalization) is the SDK's own.
"""

import os
from typing import Any, Dict

from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from prometheus_api.agent import PrometheusAgent
from prometheus_api.agent.base import DelegatingPrometheusAgentExecutor, PrometheusAgentExecutor
from prometheus_api.contract import ConversationResponse, ConversationStatus

# The e2e tests look for this text, so changing it means changing them too
TEXT_ANSWER = "This is the e2e stub agent. It gives this same answer to every message."
STATUS_MESSAGE = "Stub agent is answering."


def answer(conversation_id: str) -> ConversationResponse:
    """The fixed reply to any prompt."""
    return ConversationResponse(
        conversation_id=conversation_id,
        status=ConversationStatus.ANSWER,
        response_text=TEXT_ANSWER,
    )


class StubClientAgent(PrometheusAgent):
    """Answers every chat turn with a fixed reply."""

    def create_executor(self) -> PrometheusAgentExecutor:
        """The SDK's executor without the DeepLynx execution record (see the module docstring)."""
        return DelegatingPrometheusAgentExecutor(agent_name=self.agent_name, execute_fn=self._execute)

    async def _execute(
        self,
        params: Dict[str, Any],
        context: RequestContext,
        event_queue: EventQueue,
    ) -> Dict[str, Any]:
        conversation_id = str(params.get("conversation_id") or context.context_id or "")
        # One status update first, so the reply streams in the way a real agent's does
        await self.send_status_update(context=context, event_queue=event_queue, message=STATUS_MESSAGE)
        return answer(conversation_id).model_dump(exclude_none=True)


def main() -> None:
    """Start the agent on AGENT_PORT."""
    agent = StubClientAgent(agent_name="Stub Client Agent")
    agent.run(port=int(os.getenv("AGENT_PORT", "8000")))


if __name__ == "__main__":  # pragma: no cover - the container's entry point; main() is tested
    main()
