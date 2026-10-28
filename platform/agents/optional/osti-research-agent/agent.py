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
OSTI Research Agent - Performs literature search on OSTI database.

This agent:
1. Takes research questions and searches the OSTI scientific database
2. Assesses paper relevance using LLM-based abstract analysis
3. Downloads relevant papers and extracts answers
4. Synthesizes findings from multiple sources with provenance
5. Builds a self-learning knowledge base in Redis

This file is the A2A executor: the ONLY place in this agent that imports
prometheus_api or a2a. It adapts PrometheusAgent's task lifecycle, Bearer
auth, and status streaming to research_agent.core.runner.ResearchRunner,
which owns the actual research pipeline (research_agent/) and knows nothing
about either framework.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

import redis
from prometheus_api.agent import (
    ArtifactReference,
    EventQueue,
    PrometheusAgent,
    RequestContext,
    TaskState,
)
from prometheus_api.llm_client import LLMConfig

from research_agent.core.adapter import result_to_a2a_json
from research_agent.core.config import AgentConfig
from research_agent.core.events import ProgressEvent
from research_agent.core.model_profile import apply_model_profile
from research_agent.core.runner import ResearchRunner
from research_agent.core.search_artifacts import (
    evidence_citations,
    searched_papers_markdown,
)
from research_agent.memory import RedisCaches

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class OSTIResearchAgent(PrometheusAgent):
    """
    OSTI Research Agent - Searches scientific literature in OSTI database.

    Features:
    - Memory-first search (checks Redis before querying OSTI)
    - Multi-paper synthesis with conflict detection
    - Self-learning knowledge base
    - Progress updates throughout workflow
    - Provenance tracking for all findings
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._caches = RedisCaches(os.getenv("REDIS_URL"), os.getenv("REDIS_PASSWORD"))

    @property
    def redis_client(self) -> redis.Redis:
        """Text-data Redis client (atomic facts, cached answers, status updates)."""
        return self._caches.client

    @property
    def redis_binary_client(self) -> redis.Redis:
        """Binary-data Redis client (cached PDFs)."""
        return self._caches.binary_client

    def _store_status_in_redis(
        self, conversation_id: str, status_message: str, final: bool = False
    ) -> None:
        """Store status update in Redis for polling by frontend."""
        if not conversation_id:
            return

        try:
            status_data = {
                "message": status_message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "final": final,
            }
            # Store latest status with 10-minute TTL
            self.redis_client.set(
                f"agent:status:{conversation_id}",
                json.dumps(status_data),
                ex=600,
            )
            # Append to bounded status history so frontend can render full progress logs.
            history_key = f"agent:status_history:{conversation_id}"
            self.redis_client.rpush(history_key, json.dumps(status_data))
            self.redis_client.ltrim(history_key, -200, -1)
            self.redis_client.expire(history_key, 600)
            logger.debug(f"[STATUS] Stored in Redis: agent:status:{conversation_id}")
        except Exception as e:
            logger.warning(f"Failed to store status in Redis: {e}")

    async def _send_status(
        self,
        context: RequestContext,
        event_queue: EventQueue,
        status_message: str,
        final: bool = False,
        conversation_id: str = None,
    ) -> None:
        """Helper to send status updates and log progress."""
        # Log the status message for visibility
        logger.info(f"[STATUS] {status_message}")

        # Store in Redis for frontend polling (use explicit conversation_id if provided)
        status_id = conversation_id or context.context_id
        self._store_status_in_redis(status_id, status_message, final)

        await self.send_status_update(
            context=context,
            event_queue=event_queue,
            state=(
                TaskState.TASK_STATE_COMPLETED
                if final
                else TaskState.TASK_STATE_WORKING
            ),
            final=final,
            message=status_message,
        )

    async def _send_final_result(
        self,
        context: RequestContext,
        event_queue: EventQueue,
        result_text: str,
        conversation_id: str = None,
    ) -> None:
        """Send the final result to the event queue so it appears in history."""
        logger.info("[RESULT] Sending final result to event queue")

        # Store final status in Redis
        status_id = conversation_id or context.context_id
        self._store_status_in_redis(status_id, "Research complete", final=True)

        await self.send_status_update(
            context=context,
            event_queue=event_queue,
            state=TaskState.TASK_STATE_COMPLETED,
            final=True,
            message=result_text,
        )
        logger.info(
            f"[RESULT] Final result sent to event queue ({len(result_text)} chars)"
        )

    async def _send_search_artifacts(
        self,
        context: RequestContext,
        event_queue: EventQueue,
        final,
    ) -> None:
        """Show the run's searched papers and its evidence sources as artifacts.

        Registered and sent under one id each, like every inline artifact. The
        list is Markdown (report viewer); each source used as evidence is a
        citation card (reference viewer, routed by its tags, so it carries no
        MIME type). Never fails the run: the answer is already complete."""
        try:
            listing = searched_papers_markdown(final)
            if listing:
                await self._send_registered_text(
                    context,
                    event_queue,
                    ArtifactReference(
                        artifact_id=str(uuid.uuid4()),
                        conversation_id="",
                        name="searched_papers.md",
                        description=(
                            f"{len(final.searched_papers)} paper(s) and abstracts "
                            "returned by the literature searches"
                        ),
                        mime_type="text/markdown",
                        text_body=listing,
                        tags=["osti", "literature", "search_results"],
                    ),
                )
            for card in evidence_citations(final):
                await self._send_registered_text(
                    context,
                    event_queue,
                    ArtifactReference(
                        artifact_id=str(uuid.uuid4()),
                        conversation_id="",
                        name=card.name,
                        description=card.description,
                        uri=card.uri,
                        text_body=card.description,
                        tags=["reference", "citation", "osti", "literature"],
                        metadata={"source": card.source},
                    ),
                )
        except Exception as e:
            logger.warning("Failed to send literature search artifacts: %s", e)

    async def _send_registered_text(
        self,
        context: RequestContext,
        event_queue: EventQueue,
        reference: ArtifactReference,
    ) -> None:
        registered = self.register_artifact_reference(context, reference)
        await self.send_text_artifact(
            context,
            event_queue,
            text=registered.text_body or "",
            name=registered.name,
            artifact_id=registered.artifact_id,
        )

    async def _execute(
        self,
        params: Dict[str, Any],
        context: RequestContext,
        event_queue: EventQueue,
    ) -> Dict[str, Any]:
        """Main entry point: run the research_agent pipeline via ResearchRunner
        and bridge its event stream to A2A status updates."""
        logger.info("=" * 60)
        logger.info("OSTI Research Agent - _execute called")
        logger.info("Parameter keys: %s", sorted(params))
        logger.info(f"Context task_id: {context.task_id}")
        logger.info("=" * 60)

        question = params.get("question")
        conversation_id = (
            params.get("conversation_id") or context.context_id or str(uuid.uuid4())
        )

        if not question:
            logger.error("No question provided in params")
            error_result = {
                "status": "error",
                "error": "Parameter 'question' is required",
                "conversation_id": conversation_id,
            }
            await self._send_final_result(
                context,
                event_queue,
                json.dumps(error_result, indent=2, default=str),
                conversation_id,
            )
            return error_result

        config = AgentConfig.from_env()

        llm_config = LLMConfig.from_env()
        config = apply_model_profile(config, llm_config)

        final = None
        async with self.llm_client(context, config=llm_config) as llm:

            async def complete(prompt: str, *, max_tokens: int) -> str:
                response = await llm.medium(prompt, max_tokens=max_tokens)
                return response.text

            runner = ResearchRunner(
                config,
                complete=complete,
                redis_client=self.redis_client,
                pdf_cache=self._caches,
            )

            async for event in runner.run(question, run_id=conversation_id):
                if isinstance(event, ProgressEvent):
                    await self._send_status(
                        context, event_queue, event.message, False, conversation_id
                    )
                else:
                    final = event

        await self._send_search_artifacts(context, event_queue, final)

        result_text = result_to_a2a_json(final)
        await self._send_final_result(
            context, event_queue, result_text, conversation_id
        )

        return final.model_dump(mode="json")


if __name__ == "__main__":  # pragma: no cover - script entry point
    # Create and run the agent
    agent = OSTIResearchAgent(agent_name="OSTI Research Agent")
    agent.run()
