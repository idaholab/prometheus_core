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
Artifact Debug Agent.

Purpose:
- Produce deterministic test artifacts backed by DeepLynx so the full artifact
  plumbing — upload, deeplynx:// URI emission, frontend resolution — can be
  exercised end-to-end.
- Convert SVG artifacts into PNG artifacts by fetching from DeepLynx, converting
  locally, and re-uploading.

Primary users:
- Orchestrator skill routing (client-agent) when testing artifact-aware tool calls.
- Frontend developers validating deeplynx:// artifact link rendering and resolution.
"""

import asyncio
import os
import re
import tempfile
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Dict, Optional
from xml.sax.saxutils import escape as xml_escape

from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from langchain.tools import ToolRuntime, tool
from langchain_core.tools import BaseTool
from prometheus_api.agent import ArtifactReference
from prometheus_api.agent.events import context_id
from prometheus_api.langgraph import LangGraphPrometheusAgent, PrometheusContext, load_artifact, save_artifact
from prometheus_api.langgraph.artifacts import SavedArtifact

# The A2A params of the running request. The tools read the parts the model does not
# pass as arguments: the client-agent's "artifacts" catalog and "upstream_results".
_request_params: ContextVar[Dict[str, Any]] = ContextVar("artifact_debug_request_params", default={})


class ArtifactDebugAgent(LangGraphPrometheusAgent):
    """Debug-only producer/converter for session-scoped artifact references backed by DeepLynx.

    Each card skill runs as a LangGraph graph with one tool of the same name.
    """

    model_alias = "small"

    @staticmethod
    def _sanitize_stem(value: str, fallback: str = "artifact") -> str:
        """Create a filesystem-safe stem for generated artifact names."""
        candidate = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "").strip())
        candidate = candidate.strip("._-")
        return candidate or fallback

    @staticmethod
    def _normalize_dimension(raw: Any, default_value: int) -> int:
        """Normalize untrusted width/height values and clamp to sensible bounds."""
        try:
            parsed = int(float(str(raw)))
        except Exception:
            parsed = default_value
        return max(64, min(parsed, 4096))

    @staticmethod
    def _convert_svg_to_png(source_svg: Path, target_png: Path) -> str:
        """Convert SVG to PNG with CairoSVG."""
        try:
            import cairosvg  # type: ignore

            cairosvg.svg2png(url=str(source_svg), write_to=str(target_png))
        except Exception as exc:
            raise RuntimeError(f"CairoSVG failed to convert SVG to PNG: {exc}") from exc

        if not target_png.exists() or target_png.stat().st_size == 0:
            raise RuntimeError("CairoSVG did not produce a PNG file.")
        return "cairosvg"

    def skill_tools(self) -> dict[str, list[BaseTool]]:
        """Map each card skill to its one tool."""
        return {
            "create_svg_artifact": [create_svg_artifact],
            "convert_svg_to_png": [convert_svg_to_png],
            "create_json_artifact": [create_json_artifact],
        }

    def system_prompt(self, skill_id: str) -> str:
        """Tell the model to call the skill's tool once, then answer briefly."""
        return (
            f"Call the {skill_id} tool exactly once, with the parameters of the JSON user message "
            "as its arguments. Then answer with one sentence."
        )

    async def _execute(
        self,
        params: Dict[str, Any],
        context: RequestContext,
        event_queue: EventQueue,
    ) -> Dict[str, Any]:
        """Run the graph of the invoked skill_id, inferring the skill when none is given."""
        # Route on the invoked skill (injected by the base executor as
        # params["skill_id"] from the A2A message metadata). This is the
        # authoritative selector — do not infer the skill from which
        # parameters happen to be present.
        skill_id = str(params.get("skill_id") or "").strip()
        if skill_id not in self.skill_tools():
            # No (or unknown) skill_id — e.g. a direct/manual invocation without
            # metadata. Fall back to inferring from parameters so such calls
            # still work, but a routed skill_id always wins.
            if params.get("json_type") or params.get("payload") is not None:
                skill_id = "create_json_artifact"
            elif params.get("artifact_id"):
                skill_id = "convert_svg_to_png"
            else:
                skill_id = "create_svg_artifact"
            params = {**params, "skill_id": skill_id}

        token = _request_params.set(params)
        try:
            return await super()._execute(params, context, event_queue)
        finally:
            _request_params.reset(token)


def _missing_storage(conversation_id: str) -> Dict[str, Any]:
    return {
        "status": "error",
        "conversation_id": conversation_id,
        "message": "DEEPLYNX_* credentials not configured.",
    }


async def _saved_result(
    runtime: ToolRuntime[PrometheusContext],
    saved: SavedArtifact,
    status: str,
    message: str,
    description: str,
) -> Dict[str, Any]:
    """Report a saved artifact and build the skill result.

    The reference is the one ``save_artifact`` registered. An item saved before
    ``SavedArtifact.artifact_id`` existed has none, so its reference is looked up
    by file name.
    """
    ctx = runtime.context
    conversation_id = context_id(runtime.context.request)
    if saved.artifact_id is not None:
        artifact_ref = ctx.agent.resolve_artifact_reference(conversation_id, saved.artifact_id)
        artifact_id = saved.artifact_id
    else:
        artifact_ref = ctx.agent.resolve_artifact_by_name(conversation_id, saved.filename)
        artifact_id = artifact_ref.artifact_id if artifact_ref else str(saved.item_id)

    await ctx.agent.send_status_update(
        context=ctx.request,
        event_queue=ctx.event_queue,
        message=f"Created artifact {artifact_id}: {description}",
    )
    await ctx.agent.send_conversation_message(
        context=ctx.request,
        event_queue=ctx.event_queue,
        message=message,
        metadata={"artifact_id": artifact_id},
    )

    return {
        "status": status,
        "conversation_id": conversation_id,
        "message": message,
        "artifact": artifact_ref.to_dict() if artifact_ref else None,
        "artifact_id": artifact_id,
        "artifact_name": saved.filename,
        "artifact_uri": saved.uri,
        "uri": saved.uri,
        "version": saved.version,
    }


@tool
async def create_svg_artifact(
    word: str,
    runtime: ToolRuntime[PrometheusContext],
    name: str = "",
    description: str = "",
    width: int = 512,
    height: int = 512,
    background_color: str = "#f8fafc",
    color: str = "#0f172a",
) -> Dict[str, Any]:
    """Create an SVG image artifact that shows *word* and save it to DeepLynx."""
    ctx = runtime.context
    conversation_id = context_id(runtime.context.request)
    if ctx.storage is None:
        return _missing_storage(conversation_id)

    word = str(word or "").strip()
    if not word:
        return {
            "status": "error",
            "conversation_id": conversation_id,
            "message": "Parameter 'word' is required to create an SVG artifact.",
        }

    width = ArtifactDebugAgent._normalize_dimension(width, 512)
    height = ArtifactDebugAgent._normalize_dimension(height, 512)
    background = str(background_color or "#f8fafc")
    text_color = str(color or "#0f172a")

    requested_name = str(name or "").strip()
    stem = ArtifactDebugAgent._sanitize_stem(
        Path(requested_name).stem if requested_name else word.lower(),
        fallback="debug_svg",
    )
    file_name = f"{stem}.svg"
    description = str(description or f"Debug SVG containing the word '{word}'.")

    await ctx.agent.send_status_update(
        context=ctx.request,
        event_queue=ctx.event_queue,
        message=f"Creating SVG artifact '{file_name}'.",
    )

    escaped_word = xml_escape(word)
    svg_content = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"'
        f' viewBox="0 0 {width} {height}">'
        f'<rect width="100%" height="100%" fill="{xml_escape(background)}" />'
        f'<text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle"'
        f' fill="{xml_escape(text_color)}" font-size="48"'
        f' font-family="sans-serif">{escaped_word}</text>'
        "</svg>"
    )

    await ctx.agent.send_status_update(
        context=ctx.request,
        event_queue=ctx.event_queue,
        message="Uploading SVG to DeepLynx.",
    )
    saved = await save_artifact(
        runtime,
        file_name,
        svg_content.encode("utf-8"),
        "image/svg+xml",
        description=description,
        json_type="prometheus.debug.svg.v1",
        metadata={"word": word},
    )
    return await _saved_result(runtime, saved, "created", "SVG artifact created successfully.", description)


async def _load_source(
    runtime: ToolRuntime[PrometheusContext],
    artifact_id: str,
    catalog: Optional[list],
) -> tuple[Optional[ArtifactReference], bytes]:
    """Return the reference and bytes of *artifact_id*, or ``(None, b"")`` when it is unknown.

    The reference comes from this agent's registry, else from the request's artifact
    catalog. A DeepLynx item is read with ``load_artifact``; any other reference
    (a ``file://`` or other URI, or an inline body) through ``get_artifact_file_path``.
    """
    ctx = runtime.context
    conversation_id = context_id(runtime.context.request)
    source_ref = ctx.agent.resolve_artifact_reference(conversation_id, artifact_id)
    if source_ref is None:
        entry = next(
            (a for a in catalog or [] if isinstance(a, dict) and str(a.get("artifact_id") or "") == artifact_id),
            None,
        )
        source_ref = ArtifactReference.from_any(entry, conversation_id=conversation_id) if entry else None
    if source_ref is None:
        return None, b""

    item_id = (source_ref.metadata or {}).get("deeplynx_item_id")
    if item_id is not None:
        return source_ref, (await load_artifact(runtime, int(item_id))).data
    path = await ctx.agent.get_artifact_file_path(
        artifact_id,
        context=ctx.request,
        conversation_id=conversation_id,
        artifacts=catalog,
    )
    return source_ref, await asyncio.to_thread(path.read_bytes)


@tool
async def convert_svg_to_png(
    runtime: ToolRuntime[PrometheusContext],
    artifact_id: str = "",
    name: str = "",
    description: str = "",
) -> Dict[str, Any]:
    """Convert the SVG artifact *artifact_id* of this conversation into a PNG artifact."""
    ctx = runtime.context
    conversation_id = context_id(runtime.context.request)
    if ctx.storage is None:
        return _missing_storage(conversation_id)

    params = _request_params.get()
    artifact_id = str(artifact_id or "").strip()
    if not artifact_id:
        upstream = params.get("upstream_results") or {}
        for skill_result in upstream.values():
            if isinstance(skill_result, dict):
                candidate = (
                    skill_result.get("artifact_id") or (skill_result.get("artifact") or {}).get("artifact_id") or ""
                )
                if candidate:
                    artifact_id = str(candidate)
                    break
    if not artifact_id:
        return {
            "status": "error",
            "conversation_id": conversation_id,
            "message": "Parameter 'artifact_id' is required for SVG to PNG conversion.",
        }

    artifact_catalog = params.get("artifacts") if isinstance(params.get("artifacts"), list) else None
    await ctx.agent.send_status_update(
        context=ctx.request,
        event_queue=ctx.event_queue,
        message=f"Loading SVG artifact '{artifact_id}'.",
    )
    try:
        source_ref, source_data = await _load_source(runtime, artifact_id, artifact_catalog)
    except FileNotFoundError:
        source_ref, source_data = None, b""
    except Exception as exc:
        return {
            "status": "error",
            "conversation_id": conversation_id,
            "message": f"Failed to retrieve artifact '{artifact_id}': {exc}",
        }
    if source_ref is None:
        return {
            "status": "error",
            "conversation_id": conversation_id,
            "message": f"Artifact '{artifact_id}' was not found in this conversation.",
        }

    source_dict = source_ref.to_dict()
    if Path(source_ref.name).suffix.lower() != ".svg":
        return {
            "status": "error",
            "conversation_id": conversation_id,
            "message": f"Artifact '{artifact_id}' is not an SVG file.",
            "source_artifact": source_dict,
        }

    requested_name = str(name or "").strip()
    base_stem = ArtifactDebugAgent._sanitize_stem(
        Path(requested_name).stem if requested_name else Path(source_ref.name).stem,
        fallback="converted",
    )
    png_name = f"{base_stem}.png"
    description = str(description or f"PNG converted from SVG artifact '{source_ref.name}'.")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        source_svg = tmp_path / "source.svg"
        source_svg.write_bytes(source_data)
        png_path = tmp_path / png_name

        await ctx.agent.send_status_update(
            context=ctx.request,
            event_queue=ctx.event_queue,
            message=f"Converting artifact '{source_ref.name}' to PNG.",
        )

        try:
            conversion_backend = ArtifactDebugAgent._convert_svg_to_png(source_svg, png_path)
        except Exception as exc:
            return {
                "status": "error",
                "conversation_id": conversation_id,
                "message": f"Failed to convert SVG artifact '{source_ref.name}' to PNG: {exc}",
                "source_artifact": source_dict,
            }
        png_bytes = png_path.read_bytes()

    await ctx.agent.send_status_update(
        context=ctx.request,
        event_queue=ctx.event_queue,
        message="Uploading PNG to DeepLynx.",
    )
    saved = await save_artifact(
        runtime,
        png_name,
        png_bytes,
        "image/png",
        description=description,
        metadata={
            "source_artifact_id": source_ref.artifact_id,
            "conversion_backend": conversion_backend,
        },
    )
    result = await _saved_result(
        runtime, saved, "converted", "SVG artifact converted to PNG successfully.", description
    )
    result["source_artifact"] = source_dict
    return result


@tool
async def create_json_artifact(
    json_type: str,
    runtime: ToolRuntime[PrometheusContext],
    payload: Optional[Dict[str, Any]] = None,
    name: str = "",
    description: str = "",
) -> Dict[str, Any]:
    """Create an inline JSON artifact of type *json_type* from the object *payload*."""
    ctx = runtime.context
    conversation_id = context_id(runtime.context.request)
    json_type = str(json_type or "").strip()
    if not json_type:
        return {
            "status": "error",
            "conversation_id": conversation_id,
            "message": "Parameter 'json_type' is required to create a JSON artifact.",
        }

    if payload is None:
        payload = {
            "message": "Debug JSON artifact",
            "requested_json_type": json_type,
        }
    if not isinstance(payload, dict):
        return {
            "status": "error",
            "conversation_id": conversation_id,
            "message": "Parameter 'payload' must be a JSON object.",
        }

    name = str(name or "debug_json_artifact").strip() or "debug_json_artifact"
    description = str(description or f"Debug JSON artifact for '{json_type}'.")

    await ctx.agent.send_status_update(
        context=ctx.request,
        event_queue=ctx.event_queue,
        message=f"Creating JSON artifact '{name}'.",
    )

    artifact_ref = ctx.agent.artifact_registry.register(
        ArtifactReference(
            artifact_id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            name=name,
            description=description,
            mime_type="application/json",
            json_type=json_type,
            json_body=payload,
            producer_agent_id=ctx.agent._producer_agent_id,
            metadata={"debug": True},
        )
    )
    artifact_id = artifact_ref.artifact_id
    await ctx.agent.send_json_artifact(
        context=ctx.request,
        event_queue=ctx.event_queue,
        payload=payload,
        name=name,
        description=description,
        json_type=json_type,
        artifact_id=artifact_id,
        metadata={"debug": True, "json_type": json_type},
    )
    await ctx.agent.send_status_update(
        context=ctx.request,
        event_queue=ctx.event_queue,
        message=f"Created JSON artifact {artifact_id}.",
    )
    await ctx.agent.send_conversation_message(
        context=ctx.request,
        event_queue=ctx.event_queue,
        message="JSON artifact created successfully.",
        metadata={"artifact_id": artifact_id, "json_type": json_type},
    )

    return {
        "status": "created",
        "conversation_id": conversation_id,
        "message": "JSON artifact created successfully.",
        "artifact": artifact_ref.to_dict(),
        "artifact_id": artifact_id,
        "json_type": json_type,
    }


if __name__ == "__main__":
    agent = ArtifactDebugAgent(agent_name="Artifact Debug Agent")
    agent.run(port=int(os.getenv("AGENT_PORT", "8000")))
