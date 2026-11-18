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

"""Request-scoped agent objects: one :class:`PrometheusRequest` per A2A request.

An agent that subclasses :class:`PrometheusRequestAgent` names a
:class:`PrometheusRequest` subclass in ``request_class``. For every request the
agent builds one instance with the params, context and event queue, and awaits
its :meth:`PrometheusRequest.execute`. The request's helper methods are thin
wrappers over the :class:`PrometheusAgent` helpers of the same name, with the
context, event queue and conversation ID filled in.

This is an additional way to write an agent. Overriding
``PrometheusAgent._execute(params, context, event_queue)`` keeps working.
"""

from __future__ import annotations

from pathlib import Path
from typing import (
    Any,
    ClassVar,
    Dict,
    Generic,
    List,
    Mapping,
    Optional,
    Sequence,
    Type,
    TypeVar,
)

from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from a2a.types import TaskState

from ..storage_client.connection import ConnectionConfig
from .artifacts import ArtifactReference
from .base import MissingInput, PrometheusAgent
from .events import context_id as event_context_id
from .events import context_task_id
from .identity import UserIdentity, get_current_identity
from .worker import PrometheusWorker

AgentT = TypeVar("AgentT", bound=PrometheusAgent)


class RequestClosedError(RuntimeError):
    """A request helper was called after the request's ``execute()`` returned."""


class PrometheusRequest(Generic[AgentT]):
    """State and helpers for one A2A request. Override :meth:`execute`.

    Attributes:
        agent: The long-lived agent. Expensive resources (models, clients,
            caches) belong there, never on the request.
        params: Parameters extracted from the A2A message.
        context: The A2A request context of this request.
        event_queue: The event queue of this request.
        task_id: The A2A task ID (stable across an INPUT_REQUIRED resume).
        conversation_id: The A2A context ID (the conversation).

    Example::

        class ThermalRequest(PrometheusRequest["ThermalAgent"]):
            async def execute(self) -> dict:
                await self.send_status_update(message="Loading mesh")
                return {"status": "success"}

        class ThermalAgent(PrometheusRequestAgent):
            request_class = ThermalRequest
    """

    def __init__(
        self,
        agent: AgentT,
        params: Dict[str, Any],
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        self.agent = agent
        self.params = params
        self.context = context
        self.event_queue = event_queue
        self.task_id = context_task_id(context)
        self.conversation_id = event_context_id(context)
        self._closed = False

    async def execute(self) -> Dict[str, Any]:
        """Do the work of this request. OVERRIDE THIS METHOD.

        The return value is handled exactly like the return value of
        ``PrometheusAgent._execute``.
        """
        raise NotImplementedError("Subclasses must implement execute()")

    def close(self) -> None:
        """Mark the request finished; every helper call afterwards raises."""
        self._closed = True

    def _check_open(self) -> None:
        if self._closed:
            raise RequestClosedError(
                f"{type(self).__name__} for task {self.task_id!r} is closed; "
                "its execute() has already returned"
            )

    # -- request-scoped values ------------------------------------------------

    @property
    def identity(self) -> Optional[UserIdentity]:
        """The verified identity of the caller, or ``None`` when none is bound."""
        return get_current_identity()

    @property
    def user_id(self) -> Optional[str]:
        """The verified user ID of the caller, or ``None``."""
        identity = get_current_identity()
        return identity.user_id if identity is not None else None

    @property
    def execution_record_id(self) -> Optional[int]:
        """The DeepLynx execution record ID of this request, if any."""
        return self.agent.execution_record_id

    # -- status and input -----------------------------------------------------

    async def send_status_update(
        self,
        state: TaskState = TaskState.TASK_STATE_WORKING,
        final: bool = False,
        message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """See :meth:`PrometheusAgent.send_status_update`."""
        self._check_open()
        await self.agent.send_status_update(
            self.context,
            self.event_queue,
            state=state,
            final=final,
            message=message,
            metadata=metadata,
        )

    async def send_input_required(
        self,
        *,
        missing_inputs: List[MissingInput],
        hint: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """See :meth:`PrometheusAgent.send_input_required`."""
        self._check_open()
        await self.agent.send_input_required(
            self.context,
            self.event_queue,
            missing_inputs=missing_inputs,
            hint=hint,
            metadata=metadata,
        )

    async def declare_long_running(
        self,
        *,
        estimate_seconds: Optional[float] = None,
        message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """See :meth:`PrometheusAgent.declare_long_running`."""
        self._check_open()
        await self.agent.declare_long_running(
            self.context,
            self.event_queue,
            estimate_seconds=estimate_seconds,
            message=message,
            metadata=metadata,
        )

    async def run_worker(
        self,
        worker: PrometheusWorker,
        *,
        poll_interval: float = 0.5,
    ) -> Dict[str, Any]:
        """See :meth:`PrometheusAgent.run_worker`."""
        self._check_open()
        return await self.agent.run_worker(
            worker,
            self.context,
            self.event_queue,
            poll_interval=poll_interval,
        )

    def get_input_sources(self) -> Dict[str, str]:
        """See :meth:`PrometheusAgent.get_input_sources`."""
        self._check_open()
        return self.agent.get_input_sources(self.context)

    def pending_hint(
        self,
        pending_subagent_requests: Optional[Any],
        default: str = "I need some additional information to proceed:",
    ) -> str:
        """See :meth:`PrometheusAgent.pending_hint`."""
        self._check_open()
        return self.agent.pending_hint(pending_subagent_requests, default=default)

    # -- artifacts and messages -----------------------------------------------

    async def send_json_artifact(
        self,
        payload: Any,
        name: str = "result",
        description: Optional[str] = None,
        json_type: Optional[str] = None,
        catalog_artifact: bool = False,
        artifact_id: Optional[str] = None,
        append: bool = False,
        last_chunk: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """See :meth:`PrometheusAgent.send_json_artifact`."""
        self._check_open()
        return await self.agent.send_json_artifact(
            self.context,
            self.event_queue,
            payload=payload,
            name=name,
            description=description,
            json_type=json_type,
            catalog_artifact=catalog_artifact,
            artifact_id=artifact_id,
            append=append,
            last_chunk=last_chunk,
            metadata=metadata,
        )

    async def send_text_artifact(
        self,
        text: str,
        name: str = "result",
        artifact_id: Optional[str] = None,
        append: bool = False,
        last_chunk: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """See :meth:`PrometheusAgent.send_text_artifact`."""
        self._check_open()
        return await self.agent.send_text_artifact(
            self.context,
            self.event_queue,
            text=text,
            name=name,
            artifact_id=artifact_id,
            append=append,
            last_chunk=last_chunk,
            metadata=metadata,
        )

    async def send_artifact_reference(
        self,
        *,
        name: str,
        description: str,
        uri: str,
        mime_type: Optional[str] = None,
        size_bytes: Optional[int] = None,
        artifact_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ArtifactReference:
        """See :meth:`PrometheusAgent.send_artifact_reference`."""
        self._check_open()
        return await self.agent.send_artifact_reference(
            self.context,
            self.event_queue,
            name=name,
            description=description,
            uri=uri,
            mime_type=mime_type,
            size_bytes=size_bytes,
            artifact_id=artifact_id,
            tags=tags,
            metadata=metadata,
        )

    async def send_deeplynx_artifact(
        self,
        *,
        file_path: Path,
        name: str,
        description: str,
        storage_config: ConnectionConfig,
        mime_type: Optional[str] = None,
        json_type: Optional[str] = None,
        artifact_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ArtifactReference:
        """See :meth:`PrometheusAgent.send_deeplynx_artifact`."""
        self._check_open()
        return await self.agent.send_deeplynx_artifact(
            self.context,
            self.event_queue,
            file_path=file_path,
            name=name,
            description=description,
            storage_config=storage_config,
            mime_type=mime_type,
            json_type=json_type,
            artifact_id=artifact_id,
            tags=tags,
            metadata=metadata,
        )

    async def send_conversation_message(
        self,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """See :meth:`PrometheusAgent.send_conversation_message`."""
        self._check_open()
        return await self.agent.send_conversation_message(
            self.context,
            self.event_queue,
            message=message,
            metadata=metadata,
        )

    def register_artifact_reference(self, reference: ArtifactReference) -> ArtifactReference:
        """See :meth:`PrometheusAgent.register_artifact_reference`."""
        self._check_open()
        return self.agent.register_artifact_reference(self.context, reference)

    def list_artifact_references(self, limit: Optional[int] = None) -> List[ArtifactReference]:
        """See :meth:`PrometheusAgent.list_artifact_references`."""
        self._check_open()
        return self.agent.list_artifact_references(self.conversation_id, limit=limit)

    def resolve_artifact_reference(self, artifact_id: str) -> Optional[ArtifactReference]:
        """See :meth:`PrometheusAgent.resolve_artifact_reference`."""
        self._check_open()
        return self.agent.resolve_artifact_reference(self.conversation_id, artifact_id)

    def resolve_artifact_by_name(self, name_or_alias: str) -> Optional[ArtifactReference]:
        """See :meth:`PrometheusAgent.resolve_artifact_by_name`."""
        self._check_open()
        return self.agent.resolve_artifact_by_name(self.conversation_id, name_or_alias)

    async def get_artifact_file_path(
        self,
        artifact_id: str,
        *,
        artifacts: Optional[Sequence[Mapping[str, Any]]] = None,
        cache_dir: Optional[Path] = None,
        allowed_file_roots: Optional[Sequence[Path | str]] = None,
        force_download: bool = False,
    ) -> Path:
        """See :meth:`PrometheusAgent.get_artifact_file_path`."""
        self._check_open()
        return await self.agent.get_artifact_file_path(
            artifact_id,
            context=self.context,
            artifacts=artifacts,
            cache_dir=cache_dir,
            allowed_file_roots=allowed_file_roots,
            force_download=force_download,
        )

    # -- clients, credentials, identity ---------------------------------------

    def llm_client(self, **kwargs: Any) -> Any:
        """See :meth:`PrometheusAgent.llm_client`."""
        self._check_open()
        return self.agent.llm_client(self.context, **kwargs)

    async def get_credential(self, resource: str, scope: Optional[dict] = None) -> Any:
        """See :meth:`PrometheusAgent.get_credential`."""
        self._check_open()
        return await self.agent.get_credential(resource, scope=scope)

    def identity_metadata(self) -> Dict[str, str]:
        """See :meth:`PrometheusAgent.identity_metadata`."""
        self._check_open()
        return self.agent.identity_metadata()

    def current_user_id(self) -> Optional[str]:
        """See :meth:`PrometheusAgent.current_user_id`."""
        self._check_open()
        return self.agent.current_user_id()


class PrometheusRequestAgent(PrometheusAgent):
    """An agent that handles each request with a new ``request_class`` instance.

    Set ``request_class`` to a :class:`PrometheusRequest` subclass and do not
    override ``_execute``. The executor lifecycle (identity, execution record,
    heartbeat, finalization) is the same as for :class:`PrometheusAgent`.
    """

    request_class: ClassVar[Optional[Type[PrometheusRequest[Any]]]] = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        request_class = type(self).request_class
        if not (isinstance(request_class, type) and issubclass(request_class, PrometheusRequest)):
            raise TypeError(
                f"{type(self).__name__}.request_class must be a PrometheusRequest "
                f"subclass, got {request_class!r}"
            )
        super().__init__(*args, **kwargs)

    async def _execute(
        self,
        params: Dict[str, Any],
        context: RequestContext,
        event_queue: EventQueue,
    ) -> Dict[str, Any]:
        """Build one request object for this request and await its ``execute()``."""
        request_class = type(self).request_class
        assert request_class is not None  # checked in __init__
        request = request_class(self, params, context, event_queue)
        try:
            return await request.execute()
        finally:
            request.close()
