import asyncio
import json
import logging
import math
import mimetypes
import tempfile
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional

import chainlit as cl
import httpx

logger = logging.getLogger(__name__)

import plugins as _plugins  # noqa: E402
from utils.a2a_client import A2AClient, ConversationResponse, response_from_payload  # noqa: E402

_normalize_mime_type = _plugins.normalize_mime_type
GENERIC_UPLOAD_MIMETYPES = _plugins.GENERIC_UPLOAD_MIMETYPES
from utils.settings import settings  # noqa: E402
from utils.uri_resolver import resolve_to_local_path  # noqa: E402

MAX_UPLOAD_BYTES = settings.max_upload_bytes
MAX_UPLOAD_MB = max(1, math.ceil(MAX_UPLOAD_BYTES / (1024 * 1024)))

CAD_EXTENSION_MIMETYPES = {
    ".stp": "model/step",
    ".step": "model/step",
}

CAD_FILE_MIMETYPES = {
    "model/step",
    "model/step+xml",
    "model/step+zip",
    "application/step",
    "application/x-step",
    "application/step+xml",
    "application/step+zip",
}


def _upload_download_element(name: str, file_path: Path, mime_type: str = "") -> Any:
    """Create a downloadable Chainlit file element for an uploaded file."""
    return cl.File(
        name=name,
        path=str(file_path),
        display="inline",
        mime=mime_type or _guess_upload_mime(name),
    )


def _upload_limit_message(name: str) -> str:
    return f"**{name}** exceeds the {MAX_UPLOAD_MB} MB upload limit and will not be stored."


async def _send_upload_limit_message(name: str) -> None:
    await cl.Message(content=_upload_limit_message(name)).send()


def _guess_upload_mime(filename: str, element_mime: Optional[str] = None) -> str:
    """Return a stable MIME type for uploaded files, including CAD extensions."""
    mime = _normalize_mime_type(element_mime)
    if mime and mime not in GENERIC_UPLOAD_MIMETYPES:
        return mime

    suffix = Path(filename).suffix.lower()
    if suffix in CAD_EXTENSION_MIMETYPES:
        return CAD_EXTENSION_MIMETYPES[suffix]
    return mimetypes.guess_type(filename)[0] or mime or "application/octet-stream"


def _build_upload_context(element: Any, file_path: Path, size_bytes: int) -> _plugins.UploadContext:
    """Create the upload context used by plugin inspection and staging."""
    return _plugins.UploadContext(
        file_path=file_path,
        display_name=element.name,
        mime_type=_guess_upload_mime(element.name, getattr(element, "mime", None)),
        size_bytes=size_bytes,
    )


async def _capture_uploaded_file(
    element: Any,
    file_path: Path,
    client: A2AClient,
    conversation_id: str,
    mime_type: str = "",
    size_bytes: int | None = None,
) -> Optional[Dict[str, Any]]:
    """Stage one Chainlit upload and return metadata expected by the agent."""
    try:
        size = size_bytes if size_bytes is not None else file_path.stat().st_size
        if size > MAX_UPLOAD_BYTES:
            await _send_upload_limit_message(element.name)
            return None

        mime = mime_type or _guess_upload_mime(element.name, getattr(element, "mime", None))
        staged = await client.stage_upload(
            file_path,
            name=element.name,
            mime_type=mime,
            conversation_id=conversation_id,
        )
        upload_id = staged.get("upload_id")
        if not upload_id:
            raise ValueError("Upload staging response did not include upload_id")
        return {
            "name": staged.get("name") or element.name,
            "mime_type": staged.get("mime_type") or mime,
            "size_bytes": staged.get("size_bytes", size),
            "upload_id": upload_id,
        }
    except Exception as exc:
        logger.warning("Could not stage %r for upload: %s", element.name, exc)
        await cl.Message(content=f"Failed to upload **{element.name}** for storage: {exc}").send()
        return None


def _format_status_history(history: List[str]) -> str:
    if not history:
        return ""
    return "\n".join(f"{idx}. {item}" for idx, item in enumerate(history, start=1))


async def _update_status_step(
    step: cl.Step,
    history: List[str],
    message: str,
    *,
    history_limit: Optional[int] = None,
) -> None:
    text = str(message or "").strip()
    if not text:
        return
    if not history or history[-1] != text:
        history.append(text)
        if history_limit and len(history) > history_limit:
            del history[:-history_limit]
    step.name = text
    step.output = _format_status_history(history)
    await step.update()


def _get_a2a_client() -> A2AClient:
    return A2AClient(
        agent_url=settings.agent_url,
        agent_secret=settings.agent_secret,
    )


def _get_user_token() -> Optional[str]:
    """Mint a short-lived platform JWT for the current Chainlit session user.

    Returns ``None`` when ``USER_IDENTITY_SECRET`` is not configured so that
    single-user / dev deployments without identity config still work
    (agents must be started with ``USER_IDENTITY_REQUIRED=false`` in that case).
    """
    if not settings.user_identity_secret:
        return None
    user_id: Optional[str] = cl.user_session.get("user_id")
    if not user_id:
        return None
    try:
        from prometheus_api.agent.identity import mint_user_token
        return mint_user_token(user_id, ttl_seconds=settings.user_identity_ttl)
    except Exception as exc:
        logger.warning("Failed to mint user token for %r: %s", user_id, exc)
        return None


async def message_handler(message: cl.Message):
    # --- File upload handling ---
    uploaded_files: List[Dict] = []
    raw_content = message.content or ""
    if not raw_content.strip() and not message.elements:
        return

    conversation_id = cl.user_session.get("conversation_id")
    if not conversation_id:
        conversation_id = str(uuid.uuid4())
        cl.user_session.set("conversation_id", conversation_id)
    client = _get_a2a_client()
    user_token = _get_user_token()

    if message.elements:
        for element in message.elements:
            if not element.name or not element.path:
                continue

            file_path = Path(element.path)
            try:
                size_bytes = file_path.stat().st_size
                if size_bytes > MAX_UPLOAD_BYTES:
                    await _send_upload_limit_message(element.name)
                    continue
            except Exception as exc:
                logger.warning("Could not stat %r for upload: %s", element.name, exc)
                continue

            upload_context = _build_upload_context(element, file_path, size_bytes)
            upload_match = await _plugins.inspect_upload(upload_context)
            if upload_match is not None:
                upload_context = replace(upload_context, mime_type=upload_match.mime_type)
            upload_mime = upload_context.mime_type

            # Visualization plugins get a local preview first, but every readable
            # upload is staged for DeepLynx afterward.
            if upload_match is not None:
                try:
                    await cl.Message(content=f"Processing **{element.name}**…").send()
                    result = await _plugins.process_upload(
                        upload_context,
                        match=upload_match,
                    )
                    if result is not None:
                        elements = list(result.elements or [])
                        if result.add_download:
                            elements.append(_upload_download_element(element.name, file_path, upload_mime))
                        await cl.Message(content=result.description, elements=elements).send()
                except Exception as e:
                    await cl.Message(content=f"Failed to process **{element.name}**: {e}").send()
            elif upload_mime == "application/pdf":
                # PDF: render inline as a Chainlit native element
                try:
                    pdf_el = cl.Pdf(name=element.name, display="inline", path=element.path)
                    download_el = _upload_download_element(element.name, file_path, upload_mime)
                    await cl.Message(content=f"**PDF loaded:** {element.name}", elements=[pdf_el, download_el]).send()
                except Exception as e:
                    await cl.Message(content=f"Failed to display PDF: {e}").send()

            # Capture every readable file for DeepLynx storage via the agent, including
            # files already rendered locally by visualization plugins.
            uploaded = await _capture_uploaded_file(
                element,
                file_path,
                client,
                conversation_id,
                upload_mime,
                size_bytes=size_bytes,
            )
            if uploaded is not None:
                uploaded_files.append(uploaded)

    # Build the query; when files are uploaded with no text, use a neutral default so
    # the agent can still determine context and upload them.
    query = raw_content.strip()
    if not query and uploaded_files:
        query = "Please process the uploaded file(s)."
    if not query:
        return

    # --- Text query → A2A client-agent ---
    artifacts_catalog = cl.user_session.get("artifacts", [])

    status_history: List[str] = []
    status_step = cl.Step(name="Sending request to agent...", type="tool")

    async def _on_status(msg: str):
        await _update_status_step(status_step, status_history, msg)

    try:
        await status_step.__aenter__()
        await _update_status_step(status_step, status_history, "Sending request to agent...")

        response = await client.send(
            query=query,
            conversation_id=conversation_id,
            artifacts=artifacts_catalog,
            uploaded_files=uploaded_files or None,
            on_status=_on_status,
            user_token=user_token,
        )

        await status_step.__aexit__(None, None, None)
        await _handle_response(client, response, query, conversation_id)

    except Exception as e:
        await status_step.__aexit__(None, None, None)
        await cl.Message(content=f"Error communicating with agent: {e}").send()


_MAX_NEEDS_INFO_DEPTH = 5


async def _handle_response(
    client: A2AClient,
    response: ConversationResponse,
    original_query: str,
    conversation_id: str,
    _depth: int = 0,
):
    if response.status == "needs_info":
        await _handle_needs_info(client, response, original_query, conversation_id, _depth=_depth)
    elif response.status == "plan_ready":
        await _handle_plan_ready(client, response, original_query, conversation_id)
    elif response.status in ("completed", "answer", "recommendation"):
        await _handle_final_response(response)
    elif response.status == "executing":
        await cl.Message(content=response.message or "Agent is executing the plan…").send()
    elif response.status == "error":
        await cl.Message(content=f"**Error:** {response.message or 'An error occurred during processing.'}").send()
    elif response.status == "backgrounded":
        await _handle_backgrounded(response, conversation_id)
    else:
        text = response.message or response.response_text or str(response)
        await cl.Message(content=text).send()


# Key under which the set of backgrounded root task ids the user is waiting on is
# stored in cl.user_session. The per-session notifier (run_task_notifier) only
# announces completion for ids in this set, so internal sub-node transitions on
# the shared events channel don't generate spurious messages.
BACKGROUNDED_IDS_KEY = "backgrounded_task_ids"
BACKGROUND_PROGRESS_KEY = "background_progress_steps"
BACKGROUND_STATUS_HISTORY_LIMIT = 50


def _awaited_task_ids() -> set:
    ids = cl.user_session.get(BACKGROUNDED_IDS_KEY)
    return ids if isinstance(ids, set) else set()


def _background_progress_entries() -> Dict[str, Dict[str, Any]]:
    entries = cl.user_session.get(BACKGROUND_PROGRESS_KEY)
    if isinstance(entries, dict):
        return entries
    entries = {}
    cl.user_session.set(BACKGROUND_PROGRESS_KEY, entries)
    return entries


async def _ensure_background_progress(task_id: str) -> Dict[str, Any]:
    entries = _background_progress_entries()
    entry = entries.get(task_id)
    if isinstance(entry, dict):
        return entry

    step = cl.Step(name="Background task running…", type="tool")
    await step.send()
    entry = {"step": step, "history": []}
    entries[task_id] = entry
    cl.user_session.set(BACKGROUND_PROGRESS_KEY, entries)
    return entry


async def _update_background_progress(task_id: str, message: str) -> None:
    text = str(message or "").strip()
    if not text:
        return
    entry = await _ensure_background_progress(task_id)
    history = entry["history"]
    if history and history[-1] == text:
        return
    await _update_status_step(
        entry["step"],
        history,
        text,
        history_limit=BACKGROUND_STATUS_HISTORY_LIMIT,
    )


async def _finish_background_progress(task_id: str, state: str) -> None:
    entries = _background_progress_entries()
    entry = entries.pop(task_id, None)
    if not isinstance(entry, dict):
        return

    completed = state == "completed"
    step = entry["step"]
    step.is_error = not completed
    message = "Background task complete." if completed else f"Background task ended ({state})."
    await _update_status_step(
        step,
        entry["history"],
        message,
        history_limit=BACKGROUND_STATUS_HISTORY_LIMIT,
    )
    cl.user_session.set(BACKGROUND_PROGRESS_KEY, entries)


async def _handle_backgrounded(response: ConversationResponse, conversation_id: str) -> None:
    """The turn was detached to run in the background. Acknowledge it and register
    the task id so the per-session notifier announces its result on completion.

    Delivery is handled by ``run_task_notifier`` (one subscriber per chat session,
    started in ``@cl.on_chat_start``) rather than a per-turn watcher — a long-lived
    subscriber whose handle is retained in the session can't be GC'd mid-flight and
    has a guaranteed Chainlit context for out-of-band sends.
    """
    metadata = response.message_metadata or {}
    task_id = metadata.get("task_id")
    await cl.Message(
        content=response.message
        or "This is taking a while — it's now running in the background. "
        "I'll post the result here when it's ready (use /tasks to check progress)."
    ).send()
    if not task_id:
        return
    task_id = str(task_id)
    ids = _awaited_task_ids()
    ids.add(task_id)
    cl.user_session.set(BACKGROUNDED_IDS_KEY, ids)

    # Fast-finish guard: if the task already reached a terminal state before the
    # notifier saw an event for it (rare — detach normally precedes completion),
    # announce now. We're inside the request context here, so no init_ws_context.
    from utils import task_events

    try:
        node = await task_events.node_snapshot(settings.redis_url, conversation_id, task_id)
    except Exception:
        node = None
    state = str(node.get("state") or "") if node else ""
    if task_events.is_terminal(state):
        await _maybe_announce_completion(conversation_id, task_id, state)
        return
    await _update_background_progress(
        task_id,
        str(node.get("last_status_message") or "") if node else "Background task running…",
    )


async def _maybe_announce_completion(conversation_id: str, task_id: str, state: str) -> None:
    """Render a backgrounded task's result in the session, once.

    Idempotent via the awaited-ids set: the first caller to consume an id wins, so
    the notifier and the fast-finish guard can't both post for the same task.
    """
    from utils import task_events

    if not task_events.is_terminal(state):
        return
    ids = _awaited_task_ids()
    if task_id not in ids:
        return  # already announced (or never ours)
    await _finish_background_progress(task_id, state)
    ids.discard(task_id)
    cl.user_session.set(BACKGROUNDED_IDS_KEY, ids)

    if state != "completed":
        await cl.Message(content=f"⚠️ Background task ended ({state}).").send()
        return

    result = await task_events.fetch_result(settings.redis_url, conversation_id, task_id)
    if not result:
        await cl.Message(content="✅ Background task complete.").send()
        return
    await cl.Message(content="✅ Background task complete — here's the result:").send()
    await _handle_final_response(response_from_payload(result))


async def run_task_notifier(session: Any, conversation_id: str) -> None:
    """Per-session subscriber: announce completion of backgrounded turns the user
    is waiting on. Started once in ``@cl.on_chat_start`` (its handle retained in the
    session) and cancelled in ``@cl.on_chat_end``.

    ``session`` is the Chainlit ``WebsocketSession`` captured at chat start; we bind
    it as this coroutine's Chainlit context so ``cl.Message().send()`` and
    ``cl.user_session`` work out-of-band, after the originating request has returned.
    """
    from utils import task_events

    try:
        from chainlit.context import init_ws_context

        init_ws_context(session)
    except Exception as exc:  # context binding shouldn't be fatal; sends may still work
        logger.warning("Task notifier could not bind Chainlit context: %s", exc)

    try:
        async for event in task_events.subscribe(settings.redis_url, conversation_id):
            task_id = str(event.get("task_id") or "")
            root_task_id = str(event.get("root_task_id") or task_id)
            state = str(event.get("state") or "")
            # Child updates percolate to the root immediately. Render only the
            # root event so one specialist status does not appear twice.
            if not task_id or task_id != root_task_id or root_task_id not in _awaited_task_ids():
                continue
            try:
                if task_events.is_terminal(state):
                    await _maybe_announce_completion(conversation_id, root_task_id, state)
                else:
                    await _update_background_progress(
                        root_task_id,
                        str(event.get("message") or ""),
                    )
            except Exception as exc:
                logger.warning("Failed to update background task %s: %s", root_task_id, exc)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("Task notifier for %s stopped: %s", conversation_id, exc)


def _coerce_final_text(response: ConversationResponse, artifact_count: int) -> str:
    text = (response.report or response.response_text or response.message or "").strip()
    if text:
        return text
    if artifact_count:
        return f"{artifact_count} artifact(s) ready."
    return ""


async def _handle_needs_info(
    client: A2AClient,
    response: ConversationResponse,
    original_query: str,
    conversation_id: str,
    *,
    _depth: int = 0,
):
    if _depth >= _MAX_NEEDS_INFO_DEPTH:
        await cl.Message(content="Too many consecutive follow-up requests. Please start a new query.").send()
        return

    questions = response.followup_questions or []
    if not questions:
        if response.message:
            await cl.Message(content=response.message).send()
        return

    form_fields = []
    for q in questions:
        field = {
            "id": q.get("field", q.get("id", q.get("question", ""))),
            "label": q.get("question", q.get("label", "")),
            "input_type": q.get("type", q.get("input_type", "text")),
            "required": bool(q.get("required", True)),
        }
        if isinstance(q.get("options"), list):
            field["options"] = [
                opt if isinstance(opt, dict) else {"label": str(opt), "value": str(opt)} for opt in q["options"]
            ]
        if "default" in q:
            field["default"] = q["default"]
        if q.get("description"):
            field["help"] = q["description"]
        form_fields.append(field)

    element = cl.CustomElement(
        name="DynamicForm",
        display="inline",
        props={
            "title": response.message or "Additional information needed",
            "fields": form_fields,
            "submitLabel": "Submit",
            "formId": f"followup_{conversation_id}",
        },
    )
    ask = cl.AskElementMessage(
        content=response.message or "Please provide the following information:",
        element=element,
        timeout=600,
        raise_on_timeout=False,
    )
    submission = await ask.send()
    if not submission:
        await cl.Message(content="Follow-up form timed out.").send()
        return
    if not submission.get("submitted"):
        await cl.Message(content="Follow-up form cancelled.").send()
        return

    followup_answers = {key: value for key, value in submission.items() if key != "submitted"}
    followup_history: List[str] = []
    followup_step = cl.Step(name="Submitting follow-up answers...", type="tool")

    async def _on_followup_status(msg: str):
        await _update_status_step(followup_step, followup_history, msg)

    try:
        await followup_step.__aenter__()
        await _update_status_step(followup_step, followup_history, "Submitting follow-up answers...")
        next_response = await client.send(
            query=original_query,
            conversation_id=conversation_id,
            followup_answers=followup_answers,
            artifacts=cl.user_session.get("artifacts", []),
            on_status=_on_followup_status,
        )
        await followup_step.__aexit__(None, None, None)
    except Exception as exc:
        await followup_step.__aexit__(type(exc), exc, exc.__traceback__)
        await cl.Message(content=f"Error submitting follow-up answers: {exc}").send()
        return

    await _handle_response(client, next_response, original_query, conversation_id, _depth=_depth + 1)


async def _handle_plan_ready(
    client: A2AClient,
    response: ConversationResponse,
    original_query: str,
    conversation_id: str,
):
    plan = response.plan or {}

    plan_viewer = cl.CustomElement(
        name="PlanViewer",
        display="inline",
        props={"plan": plan, "stepStatuses": {}},
    )
    await cl.Message(
        content=response.message or "Here's the proposed execution plan:",
        elements=[plan_viewer],
    ).send()

    if not settings.auto_approve_steps:
        res = await cl.AskActionMessage(
            content="Do you want to proceed with this plan?",
            actions=[
                cl.Action(name="approve", payload={"value": "approve"}, label="Approve & Execute"),
                cl.Action(name="reject", payload={"value": "reject"}, label="Reject"),
            ],
            timeout=600,
        ).send()
        approved = res and res.get("name") == "approve"
    else:
        approved = True

    if not approved:
        # Tell the server so it clears awaiting_approval and the pending
        # routing decision; otherwise the conversation's next message
        # dead-ends in the continuation path.
        try:
            response = await client.send(
                query="",
                conversation_id=conversation_id,
                plan_rejected=True,
            )
            await cl.Message(content=response.message or "Plan rejected.").send()
        except Exception as exc:
            logger.warning("Failed to notify server of plan rejection: %s", exc)
            await cl.Message(content="Plan rejected.").send()
        return

    artifacts_catalog = cl.user_session.get("artifacts", [])
    exec_history: List[str] = []
    exec_step = cl.Step(name="Executing plan...", type="tool")
    step_statuses: dict = {}
    steps = plan.get("steps", []) if isinstance(plan, dict) else []

    async def _on_exec_status(msg: str):
        await _update_status_step(exec_step, exec_history, msg)
        _update_step_statuses(step_statuses, steps, msg)

    try:
        await exec_step.__aenter__()
        await _update_status_step(exec_step, exec_history, "Executing plan...")

        exec_response = await client.send(
            query=original_query,
            conversation_id=conversation_id,
            plan_approved=True,
            artifacts=artifacts_catalog,
            on_status=_on_exec_status,
        )

        await exec_step.__aexit__(None, None, None)
        await _handle_response(client, exec_response, original_query, conversation_id)
    except Exception as e:
        await exec_step.__aexit__(None, None, None)
        await cl.Message(content=f"Error during plan execution: {e}").send()


def _update_step_statuses(statuses: dict, steps: list, status_msg: str):
    msg_lower = status_msg.lower()
    for i, step in enumerate(steps):
        name = step if isinstance(step, str) else (step.get("name", "") or step.get("agent", ""))
        if not name:
            continue
        if name.lower() in msg_lower:
            if "complet" in msg_lower or "finish" in msg_lower or "done" in msg_lower:
                statuses[i] = "completed"
            elif "fail" in msg_lower or "error" in msg_lower:
                statuses[i] = "failed"
            else:
                statuses[i] = "running"
                for j in range(i):
                    if statuses.get(j) != "failed":
                        statuses[j] = "completed"


async def _handle_final_response(response: ConversationResponse):
    metadata = response.message_metadata or {}
    is_slash_command = bool(metadata.get("slash_command"))
    artifacts_to_render = (
        []
        if is_slash_command
        else [
            artifact
            for artifact in (response.new_artifacts or [])
            if (artifact.get("metadata") or {}).get("source") != "user-upload"
        ]
    )
    text = _coerce_final_text(response, len(artifacts_to_render))
    elements = []

    if response.artifacts:
        cl.user_session.set("artifacts", response.artifacts)

    with tempfile.TemporaryDirectory() as render_tmp:
        if artifacts_to_render:
            artifact_elements, artifact_text = await render_artifacts(artifacts_to_render, Path(render_tmp))
            elements.extend(artifact_elements)
            if artifact_text:
                text = f"{text}\n\n---\n{artifact_text}".strip() if text else artifact_text

        if response.recommended_materials:
            materials = "\n".join(f"- {m}" for m in response.recommended_materials)
            text += f"\n\n**Recommended Materials:**\n{materials}"

        suggestions = metadata.get("follow_up_suggestions", [])
        if suggestions:
            elements.append(
                cl.CustomElement(
                    name="FollowUpSuggestions",
                    props={"suggestions": suggestions, "title": "What would you like to do next?"},
                )
            )

        if text or elements:
            await cl.Message(content=text, elements=elements).send()


async def render_artifacts(
    artifacts: List[Dict[str, Any]],
    tmp_dir: Path,
) -> tuple[list, str]:
    """Render artifact references into Chainlit elements and inline text.

    Routes each artifact through the visualization plugin system first.
    Falls back to text rendering for data, reports, references, PDFs, and
    generic downloadable files.
    """
    elements: list = []
    text_parts: list[str] = []

    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        metadata = artifact.get("metadata") or {}
        if metadata.get("kind") == "conversation_message":
            continue
        if artifact.get("name") == "conversation_message":
            continue

        uri = artifact.get("uri") or ""
        name = artifact.get("name", "Artifact")
        mime_type = (artifact.get("mime_type") or "").lower()
        json_type = artifact.get("json_type") or (artifact.get("metadata") or {}).get("json_type")
        description = artifact.get("description", "")

        # Resolve deeplynx:// URIs to local files before plugin dispatch.
        # Plugins expect file:// or http(s):// URIs; deeplynx:// must be downloaded first.
        if uri.startswith("deeplynx://"):
            resolved = await resolve_to_local_path(
                uri,
                cache_dir=tmp_dir,
                artifact=artifact,
                artifact_id=artifact.get("artifact_id"),
            )
            if resolved is not None:
                artifact = dict(artifact)
                artifact["uri"] = f"file://{resolved}"
                uri = artifact["uri"]
            else:
                logger.warning("Could not resolve deeplynx:// artifact %r; falling back to text", name)

        # Try visualization plugin system first
        try:
            element = await _plugins.render_artifact(artifact)
        except Exception as e:
            logger.warning("Plugin rendering failed for artifact %r: %s", name, e)
            element = None
        if element is not None:
            elements.append(element)
            download_el = await _render_download_artifact(artifact, uri, name, tmp_dir, mime_type)
            if download_el:
                elements.append(download_el)
            continue

        # Fallback: text-based rendering for non-visual artifact types
        artifact_type = _classify_artifact(mime_type)

        if artifact_type == "pdf":
            el = await _render_pdf_artifact(uri, name, tmp_dir)
            if el:
                elements.append(el)
                download_el = await _render_download_artifact(artifact, uri, name, tmp_dir, mime_type)
                if download_el:
                    elements.append(download_el)
            else:
                text_parts.append(f"- **{name}** (PDF): `{uri}`")

        elif artifact_type == "data":
            data_content = artifact.get("json_body")
            # If json_body is absent, try fetching JSON from the URI
            if not data_content and uri and uri.startswith("http"):
                data_content = await _fetch_json_body(uri)
            if data_content is not None:
                elements.append(
                    cl.CustomElement(
                        name="CollapsibleJson",
                        display="inline",
                        props={
                            "data": data_content,
                            "name": name,
                            "description": description,
                            "json_type": json_type or "",
                        },
                    )
                )
                download_el = await _render_download_artifact(artifact, uri, name, tmp_dir, mime_type)
                if download_el:
                    elements.append(download_el)
            else:
                el = await _render_remote_file_artifact(uri, name, tmp_dir, mime_type)
                if el:
                    elements.append(_with_artifact_description(el, description))
                    line = f"- **{name}**"
                    if description:
                        line += f": {description}"
                    elif json_type:
                        line += f": `{json_type}`"
                    text_parts.append(line)
                else:
                    text_parts.append(f"- **{name}**: {description or uri or '(no URI)'}")

        elif artifact_type == "report":
            report_text = description
            if report_text:
                text_parts.append(f"### {name}\n{report_text}")
            else:
                text_parts.append(f"- **{name}**: {description or uri}")
            download_el = await _render_download_artifact(artifact, uri, name, tmp_dir, mime_type)
            if download_el:
                elements.append(download_el)

        elif artifact_type == "file":
            el = await _render_file_artifact(uri, name, tmp_dir, mime_type)
            if el:
                elements.append(_with_artifact_description(el, description))
            else:
                text_parts.append(f"- **{name}**: `{uri}`")

        elif artifact_type == "reference":
            text_parts.append(_render_reference_artifact(name, uri, description, metadata))
            download_el = await _render_download_artifact(artifact, uri, name, tmp_dir, mime_type)
            if download_el:
                elements.append(download_el)

        else:
            # No plugin and no known text type — tell the user and offer a download
            label = json_type or mime_type or "unknown"
            line = f"**{name}** — no viewer available for `{label}`"
            if description:
                line += f"\n  > {description}"
            el = await _render_download_artifact(artifact, uri, name, tmp_dir, mime_type)
            if el:
                elements.append(el)
            else:
                line += f"\n  `{uri}`" if uri else ""
            text_parts.append(line)

    return elements, "\n".join(text_parts)


def _classify_artifact(mime_type: str) -> str:
    """Classify artifact for MIME-driven fallback rendering."""
    if mime_type == "application/pdf":
        return "pdf"
    if mime_type in ("application/json", "text/csv"):
        return "data"
    if mime_type in ("text/markdown", "text/plain"):
        return "report"
    if (
        mime_type
        in (
            "application/octet-stream",
            "application/zip",
            "application/gzip",
        )
        or mime_type in CAD_FILE_MIMETYPES
    ):
        return "file"

    return "unknown"


async def _fetch_json_body(uri: str) -> Optional[Any]:
    """Download a JSON artifact from a remote URI and return its parsed content."""
    try:
        async with httpx.AsyncClient(timeout=60) as http:
            resp = await http.get(uri)
            resp.raise_for_status()
            return resp.json()
    except (httpx.HTTPError, json.JSONDecodeError) as e:
        logger.warning("Failed to fetch JSON body from %r: %s", uri, e)
    except Exception as e:
        logger.warning("Unexpected error fetching JSON from %r: %s", uri, e)
    return None


async def _render_pdf_artifact(uri: str, name: str, tmp_dir: Path) -> Optional[Any]:
    try:
        if uri.startswith("file://"):
            path = Path(uri[7:])
        elif uri.startswith("/"):
            path = Path(uri)
        else:
            path = None

        if path and path.exists():
            return cl.Pdf(name=name, display="inline", path=str(path))

        if uri.startswith("http"):
            async with httpx.AsyncClient(timeout=60) as http:
                resp = await http.get(uri)
                resp.raise_for_status()
            tmp = tmp_dir / (name or "document.pdf")
            tmp.write_bytes(resp.content)
            return cl.Pdf(name=name, display="inline", path=str(tmp))
    except Exception as e:
        logger.warning("Failed to render PDF artifact %r: %s", uri, e)
    return None


def _with_artifact_description(element: Any, description: Any) -> Any:
    """Add an artifact's display description without changing its filename."""
    if isinstance(description, str) and description.strip():
        element.props = {
            **(getattr(element, "props", None) or {}),
            "description": description.strip(),
        }
    return element


async def _render_remote_file_artifact(uri: str, name: str, tmp_dir: Path, mime_type: str = "") -> Optional[Any]:
    if not uri.startswith("http"):
        return None
    try:
        async with httpx.AsyncClient(timeout=60) as http:
            resp = await http.get(uri)
            resp.raise_for_status()
        filename = Path(name).name or "artifact"
        tmp = tmp_dir / filename
        tmp.write_bytes(resp.content)
        effective_mime = mime_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return cl.File(name=filename, path=str(tmp), display="inline", mime=effective_mime)
    except Exception as e:
        logger.warning("Failed to render remote file artifact %r: %s", uri, e)
        return None


async def _render_file_artifact(uri: str, name: str, tmp_dir: Path, mime_type: str = "") -> Optional[Any]:
    if uri.startswith("file://"):
        path = Path(uri[7:])
    elif uri.startswith("/"):
        path = Path(uri)
    else:
        return await _render_remote_file_artifact(uri, name, tmp_dir, mime_type)
    if path.exists():
        effective_mime = mime_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
        return cl.File(name=name, path=str(path), display="inline", mime=effective_mime)
    return None


async def _render_download_artifact(
    artifact: Dict[str, Any],
    uri: str,
    name: str,
    tmp_dir: Path,
    mime_type: str = "",
) -> Optional[Any]:
    """Create a downloadable file element for any artifact with bytes or inline content."""
    if uri:
        file_el = await _render_file_artifact(uri, name, tmp_dir, mime_type)
        if file_el:
            return _with_artifact_description(
                file_el, artifact.get("description", "")
            )

    payload = _artifact_download_payload(artifact, mime_type)
    if payload is None:
        return None

    content, extension, effective_mime = payload
    filename = _download_filename(name, extension)
    tmp = tmp_dir / f"{uuid.uuid4().hex}_{filename}"
    tmp.write_bytes(content)
    return _with_artifact_description(
        cl.File(name=filename, path=str(tmp), display="inline", mime=effective_mime),
        artifact.get("description", ""),
    )


def _artifact_download_payload(
    artifact: Dict[str, Any],
    mime_type: str = "",
) -> Optional[tuple[bytes, str, str]]:
    """Serialize inline artifact content so it can still be downloaded."""
    if "json_body" in artifact and artifact["json_body"] is not None:
        content = json.dumps(artifact["json_body"], indent=2).encode("utf-8")
        return content + b"\n", ".json", "application/json"

    for key in ("content", "text", "description"):
        value = artifact.get(key)
        if value:
            effective_mime = mime_type or "text/plain"
            extension = ".md" if effective_mime == "text/markdown" else ".txt"
            return str(value).encode("utf-8"), extension, effective_mime

    return None


def _download_filename(name: str, extension: str) -> str:
    filename = Path(str(name or "artifact")).name or "artifact"
    if extension and not Path(filename).suffix:
        filename = f"{filename}{extension}"
    return filename


def _render_reference_artifact(name: str, uri: str, description: str, metadata: dict) -> str:
    source = metadata.get("source", "")
    section = metadata.get("section", "")
    page = metadata.get("page", "")

    parts = [f"**[{name}]**"]
    if description:
        parts.append(f" {description}")
    citation_parts = []
    if source:
        citation_parts.append(source)
    if section:
        citation_parts.append(f"Section: {section}")
    if page:
        citation_parts.append(f"p. {page}")
    if uri:
        citation_parts.append(f"[link]({uri})" if uri.startswith("http") else f"`{uri}`")
    if citation_parts:
        parts.append(f" — *{', '.join(citation_parts)}*")

    return "".join(parts)
