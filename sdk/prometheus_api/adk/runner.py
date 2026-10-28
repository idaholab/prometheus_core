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
"""``build_runner``: the one factory that wires ADK into a Prometheus agent.

Every runner gets the same services and plugins. The session and memory services are module
singletons over one async engine on ``ADK_SESSION_DB_URL``; when that is empty, the runner
uses ADK's in-memory session and memory services and logs one warning, because runs then
cannot resume after a restart. ``test=True`` gives in-memory session, artifact and memory
services shared per agent, so a test can run a stub model with no database or DeepLynx.

Plugin order matters: ADK stops at the first ``before_tool_callback`` that returns a value.
The order is bridge, provenance, ``ArtifactCallPlugin``, cancel, approval, credentials, the
caller's extra plugins, then compaction. Cancel blocks a call before approval pauses it, and
credentials come after approval, so no token is fetched for a call that pauses.
"""

import asyncio
import functools
import logging
import os
import weakref
from collections.abc import Sequence

from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from google.adk.apps import App, ResumabilityConfig
from google.adk.artifacts.base_artifact_service import BaseArtifactService
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.memory.base_memory_service import BaseMemoryService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.models.base_llm import BaseLlm
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.runners import Runner
from google.adk.sessions.base_session_service import BaseSessionService
from google.adk.sessions.database_session_service import DatabaseSessionService
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.sessions.session import Session
from google.adk.workflow import BaseNode
from sqlalchemy.ext.asyncio import create_async_engine

from ..agent.base import PrometheusAgent
from ..agent.events import normalize_producer_agent_id
from .artifacts import ArtifactCallPlugin, DeepLynxArtifactService
from .memory import PrometheusMemoryService
from .model import prometheus_model
from .plugins.approval import ApprovalPlugin
from .plugins.bridge import A2ABridgePlugin
from .plugins.cancel import CancelPlugin
from .plugins.compaction import CompactionPlugin, CompactionPolicy
from .plugins.credentials import CredentialPlugin
from .plugins.provenance import ProvenancePlugin

logger = logging.getLogger(__name__)

type _Services = tuple[BaseSessionService, BaseMemoryService]
type _TestServices = tuple[BaseSessionService, BaseArtifactService, BaseMemoryService]

_test_services: weakref.WeakKeyDictionary[PrometheusAgent, _TestServices] = (
    weakref.WeakKeyDictionary()
)


@functools.cache
def session_services() -> _Services:
    """Return the process-wide session and memory services for ``ADK_SESSION_DB_URL``.

    Both services share one async engine. The result is cached for the process, so the
    in-memory warning is logged once; ``session_services.cache_clear()`` resets it.
    """
    url = (os.getenv("ADK_SESSION_DB_URL") or "").strip()
    if not url:
        logger.warning(
            "ADK_SESSION_DB_URL is not set; ADK sessions and procedures are kept in memory "
            "and runs cannot resume after a restart"
        )
        return InMemorySessionService(), InMemoryMemoryService()
    engine = create_async_engine(url, pool_pre_ping=True)
    return DatabaseSessionService(db_engine=engine), PrometheusMemoryService(engine=engine)


def _in_memory_services(agent: PrometheusAgent) -> _TestServices:
    """Return the in-memory services of ``agent`` for test mode, shared by its runners."""
    services = _test_services.get(agent)
    if services is None:
        services = (InMemorySessionService(), InMemoryArtifactService(), InMemoryMemoryService())
        _test_services[agent] = services
    return services


def build_runner(
    agent: PrometheusAgent,
    context: RequestContext,
    root: BaseNode,
    *,
    event_queue: EventQueue,
    compaction: CompactionPolicy | None = CompactionPolicy(),
    extra_plugins: Sequence[BasePlugin] = (),
    test: bool = False,
    abort_signal: asyncio.Event | None = None,
    summarizer_model: BaseLlm | None = None,
    bridge_events: bool = True,
) -> Runner:
    """Build the resumable ADK runner of one request of ``agent`` running ``root``.

    Args:
        agent: The Prometheus agent whose request this runner serves.
        context: The A2A request context; the bridge emits its events for it.
        root: The ADK agent or ``Workflow`` of the requested skill.
        event_queue: The A2A event queue of the request.
        compaction: The compaction policy; ``None`` leaves the compaction plugin out.
        extra_plugins: Plugins to run after the Prometheus plugins and before compaction.
        test: Use in-memory session, artifact and memory services shared per agent.
        abort_signal: The event the cancel plugin watches; pass the same event to
            ``Runner.run_async``.
        summarizer_model: The compaction summarizer, owned by the caller. By default the
            runner builds the ``small`` flavor over ``agent.llm_client(context)`` and closes
            that client in ``Runner.close()``.
        bridge_events: Emit the run's status and input-required events on ``event_queue``;
            ``False`` keeps only artifact references, for an agent that sends its own final
            status.
    """
    bridge = A2ABridgePlugin(agent, context, event_queue, emit_events=bridge_events)
    provenance = ProvenancePlugin(agent)
    plugins: list[BasePlugin] = [
        bridge,
        provenance,
        ArtifactCallPlugin(),
        CancelPlugin(agent, provenance=provenance, abort_signal=abort_signal),
        ApprovalPlugin(agent),
        CredentialPlugin(agent),
        *extra_plugins,
    ]
    if compaction is not None:
        if summarizer_model is not None:
            plugins.append(CompactionPlugin(compaction, summarizer_model))
        else:
            # The plugin owns this request-scoped client and closes it with the runner.
            client = agent.llm_client(context)
            plugins.append(
                CompactionPlugin(compaction, prometheus_model("small", client), client=client)
            )

    session_service: BaseSessionService
    artifact_service: BaseArtifactService
    memory_service: BaseMemoryService
    if test:
        session_service, artifact_service, memory_service = _in_memory_services(agent)
    else:
        session_service, memory_service = session_services()
        artifact_service = DeepLynxArtifactService(agent, bridge=bridge, provenance=provenance)

    app = App(
        name=normalize_producer_agent_id(agent.agent_name),
        root_agent=root,
        plugins=plugins,
        events_compaction_config=None,
        resumability_config=ResumabilityConfig(is_resumable=True),
    )
    return Runner(
        app=app,
        session_service=session_service,
        artifact_service=artifact_service,
        memory_service=memory_service,
    )


async def ensure_session(runner: Runner, user_id: str, session_id: str) -> Session:
    """Return the runner's session ``session_id`` of ``user_id``, created when missing."""
    session = await runner.session_service.get_session(
        app_name=runner.app_name, user_id=user_id, session_id=session_id
    )
    if session is None:
        session = await runner.session_service.create_session(
            app_name=runner.app_name, user_id=user_id, session_id=session_id
        )
    return session


async def commit_run_to_memory(runner: Runner, user_id: str, session_id: str) -> None:
    """Hand the finished session to the runner's memory service (its commit gate decides).

    Call it after a run that ended with no pending long-running call.
    """
    if runner.memory_service is None:
        return
    session = await runner.session_service.get_session(
        app_name=runner.app_name, user_id=user_id, session_id=session_id
    )
    if session is not None:
        await runner.memory_service.add_session_to_memory(session)
