from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from prometheus_api.agent import ArtifactReference, EventQueue, PrometheusAgent, RequestContext
from starlette.requests import Request
from starlette.responses import JSONResponse

from artifact_handling import merge_artifact_catalogs
from capability_cache import get_capability_cache
from conversation_store import get_conversation
from workflow_library import get_workflow_registry, verify_workflow_source_health

from . import runtime, task_tracking
from .chat_flow import chat
from .debug_commands import _is_supported_slash_command_query
from .models import ConversationRequest, ConversationResponse

# Strong references to detached background orchestration tasks, so the event
# loop does not garbage-collect them while they run past the request that
# started them.
_BACKGROUND_TASKS: set = set()


class OrchestratorAgent(PrometheusAgent):
    """A2A-native orchestrator using the shared PrometheusAgent base class."""

    def __init__(self):
        super().__init__(
            agent_name="Nuclear Analysis Client Agent",
            agent_card_path="agent_card.json",
        )

    async def _on_startup(self) -> None:
        """Initialize dynamic discovery state when the HTTP app starts."""
        print("Client Agent starting up...")
        await runtime.refresh_dynamic_components(trigger="startup")

        if runtime.DISCOVERY_REFRESH_SECONDS > 0 and runtime._refresh_task is None:
            runtime._refresh_task = asyncio.create_task(runtime.discovery_refresh_loop())
            print(
                f"Background discovery refresh enabled "
                f"({runtime.DISCOVERY_REFRESH_SECONDS}s interval)"
            )

        print("Client Agent ready!")

    async def _on_shutdown(self) -> None:
        """Cleanup background refresh task on server shutdown."""
        print("Client Agent shutting down...")
        if runtime._refresh_task:
            runtime._refresh_task.cancel()
            try:
                await runtime._refresh_task
            except asyncio.CancelledError:
                pass
            runtime._refresh_task = None

    @asynccontextmanager
    async def lifespan(self, app) -> AsyncIterator[None]:
        """Use Starlette lifespan hooks instead of deprecated event handlers."""
        await self._on_startup()
        try:
            yield
        finally:
            await self._on_shutdown()

    async def _refresh_endpoint(self, request) -> JSONResponse:
        """Manual refresh endpoint for capability/tool discovery."""
        payload = await runtime.refresh_discovery()
        return JSONResponse(payload)

    async def _stage_upload_endpoint(self, request: Request) -> JSONResponse:
        """Stage upload bytes server-side and return a metadata token for A2A."""
        from file_upload_handler import (
            MAX_UPLOAD_BYTES,
            cleanup_stale_staged_uploads,
            new_staged_upload_id,
            staged_upload_paths,
            write_staged_upload_metadata,
        )

        cleanup_stale_staged_uploads()

        raw_name = (
            request.query_params.get("name")
            or request.headers.get("x-upload-name")
            or "upload"
        )
        name = Path(str(raw_name).replace("\\", "/")).name or "upload"
        mime_type = (
            request.query_params.get("mime_type")
            or request.headers.get("content-type")
            or "application/octet-stream"
        ).split(";", 1)[0].strip().lower() or "application/octet-stream"
        conversation_id = request.query_params.get("conversation_id") or ""

        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_UPLOAD_BYTES:
                    return JSONResponse(
                        {"error": f"{name} exceeds the {MAX_UPLOAD_BYTES} byte upload limit"},
                        status_code=413,
                    )
            except ValueError:
                pass

        upload_id = new_staged_upload_id()
        data_path, _ = staged_upload_paths(upload_id)
        data_path.parent.mkdir(parents=True, exist_ok=True)
        size = 0

        try:
            with data_path.open("wb") as stream:
                async for chunk in request.stream():
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise ValueError(f"{name} exceeds the {MAX_UPLOAD_BYTES} byte upload limit")
                    await asyncio.to_thread(stream.write, chunk)
        except ValueError as exc:
            try:
                data_path.unlink()
            except FileNotFoundError:
                pass
            return JSONResponse({"error": str(exc)}, status_code=413)
        except Exception as exc:
            try:
                data_path.unlink()
            except FileNotFoundError:
                pass
            return JSONResponse({"error": f"Failed to stage upload: {exc}"}, status_code=500)

        # Stamp the verified user_id into metadata so uploads can be rejected
        # when a different user attempts to consume them.
        from prometheus_api.agent.identity import current_user_id as _current_user_id
        staged_user_id = _current_user_id() or ""

        payload = {
            "upload_id": upload_id,
            "name": name,
            "mime_type": mime_type,
            "size_bytes": size,
            "conversation_id": conversation_id,
            "user_id": staged_user_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        write_staged_upload_metadata(upload_id, payload)
        return JSONResponse(payload)

    async def _workflow_catalog_endpoint(self, request: Request) -> JSONResponse:
        """Return workflow catalog cards for frontend workflow picker."""
        if not runtime.ENABLE_WORKFLOW_LIBRARY:
            return JSONResponse({"workflows": [], "enabled": False})
        registry = get_workflow_registry()
        return JSONResponse(
            {
                "enabled": True,
                "workflows": registry.get_catalog(),
                "errors": registry.snapshot.errors,
            }
        )

    async def _workflow_input_form_endpoint(self, request: Request) -> JSONResponse:
        """Return unresolved required inputs for a workflow template."""
        if not runtime.ENABLE_WORKFLOW_LIBRARY:
            return JSONResponse({"error": "Workflow library disabled"}, status_code=404)

        workflow_id = str(request.path_params.get("workflow_id") or "").strip()
        version = request.query_params.get("version")
        conversation_id = request.query_params.get("conversation_id")
        state = get_conversation(conversation_id) if conversation_id else None
        params = {}
        if isinstance(state, dict):
            params = dict((state.get("routing_decision") or {}).get("extracted_params", {}) or {})
        context = dict((state or {}).get("context", {}) or {})

        cache = get_capability_cache()
        capabilities = await cache.get_capabilities()
        capabilities_by_skill = {cap.skill_id: cap for cap in capabilities}

        registry = get_workflow_registry()
        try:
            payload = registry.build_input_form(
                workflow_id=workflow_id,
                version=version,
                capabilities_by_skill=capabilities_by_skill,
                params=params,
                context=context,
            )
        except KeyError:
            return JSONResponse({"error": f"Workflow '{workflow_id}' not found"}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Failed to build workflow form: {exc}"}, status_code=500)

        return JSONResponse(payload)

    async def _workflow_start_endpoint(self, request: Request) -> JSONResponse:
        """Start a workflow-based conversation turn from catalog selections."""
        if not runtime.ENABLE_WORKFLOW_LIBRARY:
            return JSONResponse({"error": "Workflow library disabled"}, status_code=404)

        workflow_id = str(request.path_params.get("workflow_id") or "").strip()
        body = await request.json()
        query = body.get("query") or f"Start workflow {workflow_id}"
        conversation_id = body.get("conversation_id")
        workflow_version = body.get("workflow_version")
        form_values = body.get("inputs") if isinstance(body.get("inputs"), dict) else None
        artifacts = body.get("artifacts") if isinstance(body.get("artifacts"), list) else None
        registry = get_workflow_registry()
        workflow = registry.get(workflow_id, version=workflow_version)
        if not workflow:
            return JSONResponse(
                {"error": f"Workflow '{workflow_id}' not found"},
                status_code=404,
            )
        health_error = await verify_workflow_source_health(workflow)
        if health_error:
            return JSONResponse({"error": health_error}, status_code=409)

        chat_request = ConversationRequest(
            query=query,
            conversation_id=conversation_id,
            followup_answers=form_values,
            artifacts=artifacts,
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            selection_source="catalog",
        )
        response = await chat(chat_request)
        return JSONResponse(response.model_dump(exclude_none=True))

    def _collect_artifact_reference_payloads(self, payload: Any) -> List[Any]:
        """Recursively collect artifact payloads from tool responses.

        Used by `_execute` after `chat(...)` so orchestrator conversation state can
        track artifacts produced by downstream agents.
        """
        collected: List[Any] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                if (
                    isinstance(node.get("parts"), list)
                    or node.get("uri")
                    or node.get("json_body") is not None
                ):
                    collected.append(node)
                artifact_node = node.get("artifact")
                if artifact_node is not None:
                    walk(artifact_node)
                artifacts_node = node.get("artifacts")
                if isinstance(artifacts_node, list):
                    for item in artifacts_node:
                        walk(item)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(payload)
        return collected

    def _ingest_response_artifacts(self, conversation_id: str, payload: Dict[str, Any]) -> int:
        """Register downstream artifact refs into this orchestrator conversation scope."""
        if not conversation_id:
            return 0

        ingested = 0
        for candidate in self._collect_artifact_reference_payloads(payload):
            try:
                reference = ArtifactReference.from_any(
                    candidate,
                    conversation_id=conversation_id,
                )
            except Exception:
                continue
            if reference is None or not reference.name:
                continue
            if not reference.uri and reference.json_body is None:
                continue
            metadata = dict(reference.metadata or {})
            if metadata.get("kind") == "conversation_message":
                continue
            if reference.name == "conversation_message":
                continue

            if reference.conversation_id and reference.conversation_id != conversation_id:
                metadata.setdefault("source_conversation_id", reference.conversation_id)
                reference.metadata = metadata
            reference.conversation_id = conversation_id

            try:
                self.artifact_registry.register(reference)
                ingested += 1
            except Exception as exc:
                print(f"[WARN] Failed to ingest artifact reference: {exc}")

        return ingested

    def _response_payload_with_artifacts(
        self,
        conversation_id: str,
        response: ConversationResponse,
        artifact_ids_before_turn: set[str],
    ) -> Dict[str, Any]:
        """Serialize chat response and attach the current conversation artifact catalog."""
        response_payload = response.model_dump(exclude_none=True)
        try:
            ingested = self._ingest_response_artifacts(conversation_id, response_payload)
            if ingested:
                print(f"[DEBUG] Ingested {ingested} artifact reference(s) for {conversation_id}")
        except Exception as exc:
            print(f"[WARN] Failed to ingest artifacts from response payload: {exc}")
        try:
            all_refs = [
                ref.to_dict() for ref in self.list_artifact_references(conversation_id, limit=50)
            ]
            response_payload["artifacts"] = all_refs
            # new_artifacts = refs not present at the start of this turn
            response_payload["new_artifacts"] = [
                r for r in all_refs
                if (r.get("artifact_id") or r.get("id")) not in artifact_ids_before_turn
            ]
        except Exception as exc:
            print(f"[WARN] Failed to attach artifacts to response: {exc}")
        return response_payload

    async def _handle_uploaded_files(
        self,
        request_payload: Dict[str, Any],
        conversation_id: str,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> List[str]:
        """Pre-process files attached by the user this turn.

        Infers descriptions via a single LLM call, uploads all files to DeepLynx,
        and returns the list of newly-created artifact IDs so the planner can treat
        them as freshly-uploaded for this turn.  Always returns (possibly empty);
        never raises.
        """
        from file_upload_handler import (
            UploadedFile,
            infer_file_descriptions,
            mime_type_label,
            upload_files_to_deeplynx,
        )

        raw_uploads = request_payload.pop("uploaded_files", None) or []
        uploaded_files = []
        for raw in raw_uploads:
            if not isinstance(raw, dict):
                continue
            try:
                uploaded_files.append(UploadedFile.model_validate(raw))
            except Exception as exc:
                print(f"[WARN] Ignoring invalid uploaded file payload: {exc}")

        if not uploaded_files:
            return []

        async def emit_upload_status(message: str) -> None:
            try:
                await self.send_status_update(
                    context=context,
                    event_queue=event_queue,
                    message=message,
                )
            except Exception as exc:
                print(f"[WARN] Failed to emit upload status update: {exc}")
            runtime.store_status_update(conversation_id, message)

        received_summaries = [
            {
                "name": f.name,
                "mime_type": f.mime_type,
                "size_bytes": f.size_bytes,
            }
            for f in uploaded_files
        ]

        try:
            from prometheus_api.storage_client.connection import ConnectionConfig
            storage_config = ConnectionConfig.from_env()
        except Exception as exc:
            print(f"[WARN] DeepLynx storage is unavailable; uploaded files will not be stored: {exc}")
            request_payload["received_files"] = received_summaries
            msg = f"Received {len(uploaded_files)} uploaded file(s), but DeepLynx storage is not configured."
            await emit_upload_status(msg)
            return []

        await emit_upload_status(f"Analyzing {len(uploaded_files)} uploaded file(s).")

        try:
            async with runtime.create_llm(context) as llm:
                descriptions = await infer_file_descriptions(
                    request_payload.get("query") or "", uploaded_files, llm,
                )
        except Exception as exc:
            print(f"[WARN] Failed to infer uploaded file descriptions; using fallbacks: {exc}")
            descriptions = {
                f.name: f"User-uploaded {mime_type_label(f.mime_type, f.name)}: {f.name}"
                for f in uploaded_files
            }

        await emit_upload_status(f"Uploading {len(uploaded_files)} file(s) to DeepLynx.")

        try:
            from prometheus_api.agent.identity import current_user_id as _current_user_id
            _upload_user_id = _current_user_id() or None
            refs = await upload_files_to_deeplynx(
                self, uploaded_files, descriptions, context, event_queue, storage_config,
                user_id=_upload_user_id,
            )
        except Exception as exc:
            print(f"[WARN] Uploaded file persistence failed: {exc}")
            refs = []

        if not refs:
            request_payload["received_files"] = received_summaries
            msg = f"{len(uploaded_files)} file(s) could not be saved to DeepLynx."
            await emit_upload_status(msg)
            return []

        if len(refs) < len(uploaded_files):
            uploaded_names = {str(getattr(ref, "name", "") or "") for ref in refs}
            request_payload["received_files"] = [
                item for item in received_summaries if item["name"] not in uploaded_names
            ]
            failed = len(uploaded_files) - len(refs)
            msg = f"{failed} of {len(uploaded_files)} file(s) could not be saved to DeepLynx."
            await emit_upload_status(msg)

        new_dicts = [r.to_dict() for r in refs]
        request_payload["artifacts"] = merge_artifact_catalogs(
            new_dicts,
            request_payload.get("artifacts") if isinstance(request_payload.get("artifacts"), list) else None,
        )
        return [r.artifact_id for r in refs]

    async def _execute(
        self,
        params: Dict[str, Any],
        context: RequestContext,
        event_queue: EventQueue,
    ) -> Dict[str, Any]:
        """A2A entry point mapped to conversational orchestrator behavior."""
        request_payload = dict(params or {})
        if "query" not in request_payload and isinstance(request_payload.get("message"), str):
            request_payload["query"] = request_payload["message"]
        if "conversation_id" not in request_payload:
            request_payload["conversation_id"] = (
                request_payload.get("context_id")
                or context.context_id
                or str(uuid.uuid4())
            )
        conversation_id = str(request_payload.get("conversation_id") or context.context_id or "")
        user_id: str = str(request_payload.get("user_id") or "")

        # Enforce conversation ownership: the verified user_id (injected into
        # params["user_id"] by PrometheusAgentExecutor._extract_params after
        # JWT verification) must own this conversation.  On first touch, record
        # the ownership so subsequent turns can be verified.
        if user_id and conversation_id:
            try:
                from prometheus_api.agent.ownership import (
                    assert_conversation_owner,
                    record_conversation_owner,
                )
                assert_conversation_owner(conversation_id, user_id)
                record_conversation_owner(conversation_id, user_id)
            except PermissionError as exc:
                return {"status": "error", "message": str(exc)}
            except Exception as exc:
                print(f"[WARN] Ownership check failed (non-fatal): {exc}")

        # Snapshot artifact IDs before this turn so we can diff new_artifacts at the end.
        # Must happen before _handle_uploaded_files so uploaded files appear in new_artifacts.
        try:
            artifact_ids_before_turn = {
                ref.artifact_id
                for ref in self.list_artifact_references(conversation_id, limit=50)
            }
        except Exception:
            artifact_ids_before_turn = set()

        await self.send_status_update(
            context=context,
            event_queue=event_queue,
            message="Processing orchestration request.",
        )
        runtime.store_status_update(conversation_id, "Processing orchestration request.")

        existing_artifacts = []
        try:
            existing_artifacts = [
                ref.to_dict() for ref in self.list_artifact_references(conversation_id, limit=50)
            ]
        except Exception as exc:
            print(f"[WARN] Failed to list artifacts for {conversation_id}: {exc}")
        if existing_artifacts:
            request_payload["artifacts"] = merge_artifact_catalogs(
                existing_artifacts,
                request_payload.get("artifacts") if isinstance(request_payload.get("artifacts"), list) else None,
            )

        if _is_supported_slash_command_query(request_payload.get("query")):
            chat_request = ConversationRequest.model_validate(request_payload)
            response = await chat(chat_request)
            return self._response_payload_with_artifacts(
                conversation_id,
                response,
                artifact_ids_before_turn,
            )

        if runtime._tools_cache is None:
            await self.send_status_update(
                context=context,
                event_queue=event_queue,
                message="Refreshing capability and workflow caches.",
            )
            runtime.store_status_update(conversation_id, "Refreshing capability and workflow caches.")
            await runtime.refresh_dynamic_components(trigger="lazy-init")
            await self.send_status_update(
                context=context,
                event_queue=event_queue,
                message="Capability refresh complete. Continuing request.",
            )
            runtime.store_status_update(conversation_id, "Capability refresh complete. Continuing request.")

        # Infer descriptions and upload any files attached this turn before routing.
        newly_uploaded_ids = await self._handle_uploaded_files(
            request_payload, conversation_id, context, event_queue
        )
        if newly_uploaded_ids:
            request_payload["newly_uploaded_artifact_ids"] = newly_uploaded_ids

        chat_request = ConversationRequest.model_validate(request_payload)

        async def emit_chat_status(message: str) -> None:
            await self.send_status_update(
                context=context,
                event_queue=event_queue,
                message=message,
            )

        async def _run_chat() -> ConversationResponse:
            with runtime.llm_request_context(context):
                with runtime.status_stream(emit_chat_status) as status_tasks:
                    try:
                        return await chat(chat_request)
                    finally:
                        await runtime.wait_for_status_stream(status_tasks)

        task_tracking.begin_turn(conversation_id, chat_request.query or "request")
        deadline = task_tracking.background_deadline_seconds()
        background_evt = task_tracking.background_event()

        # Detach is triggered by either the soft deadline (time-based promotion,
        # gated by PROMETHEUS_BACKGROUND_DEADLINE_SECONDS) or an agent calling
        # declare_long_running mid-turn (agent-driven, always active). With both
        # disabled — no deadline and no signaling turn — this awaits chat() to
        # completion, exactly the synchronous path.
        chat_task = asyncio.create_task(_run_chat())
        waiters: set = {chat_task}
        bg_wait = asyncio.create_task(background_evt.wait()) if background_evt is not None else None
        if bg_wait is not None:
            waiters.add(bg_wait)
        done, _pending = await asyncio.wait(
            waiters,
            timeout=deadline if deadline > 0 else None,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if bg_wait is not None and not bg_wait.done():
            bg_wait.cancel()

        if chat_task in done:
            response = chat_task.result()
            task_tracking.finish_turn(getattr(response, "status", "") or "")
            return self._response_payload_with_artifacts(
                conversation_id, response, artifact_ids_before_turn
            )

        # Detach (soft deadline exceeded, or an agent declared itself long-running):
        # the orchestration keeps running in a background task; the user regains
        # control and is notified on completion.
        root_id = task_tracking.ensure_background_root()
        self._spawn_background_finisher(
            chat_task, conversation_id, root_id, artifact_ids_before_turn
        )
        runtime.store_status_update(
            conversation_id, "Task is now running in the background.", final=True
        )
        backgrounded = ConversationResponse(
            conversation_id=conversation_id,
            status="backgrounded",
            message=(
                "This is taking a while, so it's now running in the background. "
                "I'll post the result here when it's ready — use /tasks to check progress."
            ),
            message_metadata={"task_id": root_id} if root_id else None,
        )
        return self._response_payload_with_artifacts(
            conversation_id, backgrounded, artifact_ids_before_turn
        )

    def _spawn_background_finisher(
        self,
        chat_task: "asyncio.Task",
        conversation_id: str,
        root_id: Optional[str],
        artifact_ids_before_turn: set,
    ) -> None:
        """Detach a slow orchestration task: await it in the background, finalize
        its Task Graph root, and persist the result for delivery on completion."""

        def _build_payload(response: ConversationResponse) -> Dict[str, Any]:
            return self._response_payload_with_artifacts(
                conversation_id, response, artifact_ids_before_turn
            )

        def _emit(message: str) -> None:
            runtime.store_status_update(conversation_id, message, final=True)

        bg = asyncio.create_task(
            task_tracking.run_background_finish(
                chat_task=chat_task,
                conversation_id=conversation_id,
                root_id=root_id,
                build_payload=_build_payload,
                on_status=_emit,
            )
        )
        _BACKGROUND_TASKS.add(bg)
        bg.add_done_callback(_BACKGROUND_TASKS.discard)

    def configure_app(self, app) -> None:
        """Add custom orchestrator endpoints."""
        app.add_route("/uploads/stage", self._stage_upload_endpoint, methods=["POST"])
        app.add_route("/discovery/refresh", self._refresh_endpoint, methods=["POST"])
        app.add_route("/workflows/catalog", self._workflow_catalog_endpoint, methods=["GET"])
        app.add_route("/workflows/{workflow_id}/input-form", self._workflow_input_form_endpoint, methods=["GET"])
        app.add_route("/workflows/{workflow_id}/start", self._workflow_start_endpoint, methods=["POST"])
