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
- Convert SVG artifacts into PNG artifacts by loading them through the ADK
  artifact service, converting locally, and saving the result.
- Serve as the reference ``AdkPrometheusAgent``: each skill is a one-node ADK
  ``Workflow`` whose ``FunctionNode`` runs the skill handler with no model call.

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
from typing import Any, Awaitable, Callable, Dict
from xml.sax.saxutils import escape as xml_escape

from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from google.adk.agents import Context
from google.adk.runners import Runner
from google.adk.workflow import START, BaseNode, Edge, FunctionNode, Workflow
from google.genai import types
from prometheus_api.adk import AdkPrometheusAgent
from prometheus_api.agent import ArtifactReference, PrometheusWorker

SkillHandler = Callable[..., Awaitable[Dict[str, Any]]]

# The A2A context and event queue of the running request. ``create_runner`` sets them in the
# request's task; the workflow nodes run in tasks copied from it, so they read the same pair.
_request: ContextVar[tuple[RequestContext, EventQueue]] = ContextVar("artifact_debug_request")


class SvgToPngWorker(PrometheusWorker):
    """Run the blocking CairoSVG conversion off the event loop."""

    def __init__(self, source_svg: Path, target_png: Path) -> None:
        super().__init__()
        self.source_svg = source_svg
        self.target_png = target_png

    def run(self) -> Dict[str, Any]:
        backend = ArtifactDebugAgent._convert_svg_to_png(self.source_svg, self.target_png)
        return {"conversion_backend": backend}


class ArtifactDebugAgent(AdkPrometheusAgent):
    """Debug-only producer/converter for session-scoped artifact references backed by DeepLynx.

    Each card skill runs as a one-node ADK ``Workflow``. The node's input is the skill params
    (the JSON user message); SVG and PNG outputs are saved with ``ctx.save_artifact`` and the
    SVG input of ``convert_svg_to_png`` is read with ``ctx.load_artifact``.
    """

    compaction = None

    def __init__(self, agent_name: str = "Agent", agent_card_path: str | None = None):
        super().__init__(agent_name=agent_name, agent_card_path=agent_card_path)
        self.adk_agents = {
            "create_svg_artifact": self._skill_workflow(
                "create_svg_artifact", self._handle_create_svg
            ),
            "convert_svg_to_png": self._skill_workflow(
                "convert_svg_to_png", self._handle_convert_svg_to_png
            ),
            "create_json_artifact": self._skill_workflow(
                "create_json_artifact", self._handle_create_json_artifact
            ),
        }

    @staticmethod
    def _skill_workflow(skill_id: str, handler: SkillHandler) -> Workflow:
        """Wrap one skill handler as a one-node ADK ``Workflow`` that makes no model call."""

        async def run_skill(ctx: Context, node_input: Dict[str, Any]) -> Dict[str, Any]:
            context, event_queue = _request.get()
            return await handler(
                params=node_input,
                conversation_id=ctx.session.id,
                context=context,
                event_queue=event_queue,
                ctx=ctx,
            )

        node = FunctionNode(func=run_skill, name="run_skill")
        return Workflow(name=skill_id, edges=[Edge(from_node=START, to_node=node)])

    def create_runner(
        self,
        context: RequestContext,
        root: BaseNode,
        *,
        event_queue: EventQueue,
        abort_signal: asyncio.Event,
    ) -> Runner:
        """Bind the request's context and event queue for the nodes, then build the runner."""
        _request.set((context, event_queue))
        return super().create_runner(
            context, root, event_queue=event_queue, abort_signal=abort_signal
        )

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

    async def _handle_create_svg(
        self,
        params: Dict[str, Any],
        conversation_id: str,
        context: RequestContext,
        event_queue: EventQueue,
        ctx: Context,
    ) -> Dict[str, Any]:
        """Create an SVG artifact and save it through the ADK artifact service."""
        word = str(params.get("word") or params.get("text") or "").strip()
        if not word:
            return {
                "status": "error",
                "conversation_id": conversation_id,
                "message": "Parameter 'word' is required to create an SVG artifact.",
            }

        width = self._normalize_dimension(params.get("width", 512), 512)
        height = self._normalize_dimension(params.get("height", 512), 512)
        background = str(params.get("background") or params.get("background_color") or "#f8fafc")
        text_color = str(params.get("color") or params.get("text_color") or "#0f172a")

        requested_name = str(params.get("name") or "").strip()
        stem = self._sanitize_stem(
            Path(requested_name).stem if requested_name else word.lower(),
            fallback="debug_svg",
        )
        file_name = f"{stem}.svg"
        description = str(params.get("description") or f"Debug SVG containing the word '{word}'.")

        await self.send_status_update(
            context=context,
            event_queue=event_queue,
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

        await self.send_status_update(
            context=context,
            event_queue=event_queue,
            message="Saving SVG artifact.",
        )

        version = await ctx.save_artifact(
            file_name,
            types.Part.from_bytes(data=svg_content.encode("utf-8"), mime_type="image/svg+xml"),
            custom_metadata={
                "description": description,
                "json_type": "prometheus.debug.svg.v1",
                "word": word,
            },
        )
        return await self._saved_artifact_result(
            context=context,
            event_queue=event_queue,
            conversation_id=conversation_id,
            file_name=file_name,
            version=version,
            status="created",
            message="SVG artifact created successfully.",
        )

    async def _saved_artifact_result(
        self,
        *,
        context: RequestContext,
        event_queue: EventQueue,
        conversation_id: str,
        file_name: str,
        version: int,
        status: str,
        message: str,
    ) -> Dict[str, Any]:
        """Report a saved artifact and build the skill result.

        The DeepLynx artifact service registers each save under its file name, so the
        reference is resolved by name. When nothing registered it (the in-memory service of
        test mode), ``artifact_id`` is the file name, which ``convert_svg_to_png`` also accepts.
        """
        artifact_ref = self.resolve_artifact_by_name(conversation_id, file_name)
        artifact_id = artifact_ref.artifact_id if artifact_ref else file_name

        await self.send_status_update(
            context=context,
            event_queue=event_queue,
            message=f"Saved artifact {artifact_id}.",
        )
        await self.send_conversation_message(
            context=context,
            event_queue=event_queue,
            message=message,
            metadata={"artifact_id": artifact_id},
        )

        return {
            "status": status,
            "conversation_id": conversation_id,
            "message": message,
            "artifact": artifact_ref.to_dict() if artifact_ref else None,
            "artifact_id": artifact_id,
            "artifact_name": file_name,
            "artifact_uri": artifact_ref.uri if artifact_ref else None,
            "artifact_version": version,
        }

    async def _handle_convert_svg_to_png(
        self,
        params: Dict[str, Any],
        conversation_id: str,
        context: RequestContext,
        event_queue: EventQueue,
        ctx: Context,
    ) -> Dict[str, Any]:
        """Load an SVG artifact, convert it to PNG on a worker thread, and save the result.

        ``artifact_id`` is the artifact ID of a reference in this conversation, whose name is
        the ADK artifact file name, or that file name itself.
        """
        artifact_id = str(params.get("artifact_id") or "").strip()
        if not artifact_id:
            upstream = params.get("upstream_results") or {}
            for skill_result in upstream.values():
                if isinstance(skill_result, dict):
                    candidate = (
                        skill_result.get("artifact_id")
                        or (skill_result.get("artifact") or {}).get("artifact_id")
                        or ""
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

        source_ref = self.resolve_artifact_reference(conversation_id, artifact_id)
        source_name = source_ref.name if source_ref else artifact_id
        source_dict = source_ref.to_dict() if source_ref else {"name": source_name}
        if Path(source_name).suffix.lower() != ".svg":
            return {
                "status": "error",
                "conversation_id": conversation_id,
                "message": f"Artifact '{artifact_id}' is not an SVG file.",
                "source_artifact": source_dict,
            }

        await self.send_status_update(
            context=context,
            event_queue=event_queue,
            message=f"Loading SVG artifact '{source_name}'.",
        )

        source_part = await ctx.load_artifact(source_name)
        if source_part is None or source_part.inline_data is None or not source_part.inline_data.data:
            return {
                "status": "error",
                "conversation_id": conversation_id,
                "message": f"Artifact '{artifact_id}' was not found in this conversation.",
            }

        requested_name = str(params.get("name") or "").strip()
        base_stem = self._sanitize_stem(
            Path(requested_name).stem if requested_name else Path(source_name).stem,
            fallback="converted",
        )
        description = str(
            params.get("description")
            or f"PNG converted from SVG artifact '{source_name}'."
        )
        png_name = f"{base_stem}.png"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_svg = tmp_path / Path(source_name).name
            source_svg.write_bytes(source_part.inline_data.data)
            png_path = tmp_path / png_name

            await self.send_status_update(
                context=context,
                event_queue=event_queue,
                message=f"Converting artifact '{source_name}' to PNG.",
            )

            try:
                worker_result = await self.run_worker(
                    SvgToPngWorker(source_svg, png_path), context, event_queue
                )
            except Exception as exc:
                return {
                    "status": "error",
                    "conversation_id": conversation_id,
                    "message": f"Failed to convert SVG artifact '{source_name}' to PNG: {exc}",
                    "source_artifact": source_dict,
                }
            png_bytes = png_path.read_bytes()

        await self.send_status_update(
            context=context,
            event_queue=event_queue,
            message="Saving PNG artifact.",
        )

        version = await ctx.save_artifact(
            png_name,
            types.Part.from_bytes(data=png_bytes, mime_type="image/png"),
            custom_metadata={
                "description": description,
                "source_artifact_id": artifact_id,
                "conversion_backend": worker_result["conversion_backend"],
            },
        )
        result = await self._saved_artifact_result(
            context=context,
            event_queue=event_queue,
            conversation_id=conversation_id,
            file_name=png_name,
            version=version,
            status="converted",
            message="SVG artifact converted to PNG successfully.",
        )
        result["source_artifact"] = source_dict
        return result

    async def _handle_create_json_artifact(
        self,
        params: Dict[str, Any],
        conversation_id: str,
        context: RequestContext,
        event_queue: EventQueue,
        ctx: Context,
    ) -> Dict[str, Any]:
        """Create an inline JSON artifact with an explicit json_type."""
        json_type = str(params.get("json_type") or "").strip()
        if not json_type:
            return {
                "status": "error",
                "conversation_id": conversation_id,
                "message": "Parameter 'json_type' is required to create a JSON artifact.",
            }

        payload = params.get("payload")
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

        name = str(params.get("name") or "debug_json_artifact").strip() or "debug_json_artifact"
        description = str(params.get("description") or f"Debug JSON artifact for '{json_type}'.")

        await self.send_status_update(
            context=context,
            event_queue=event_queue,
            message=f"Creating JSON artifact '{name}'.",
        )

        artifact_ref = self.artifact_registry.register(
            ArtifactReference(
                artifact_id=str(uuid.uuid4()),
                conversation_id=conversation_id,
                name=name,
                description=description,
                mime_type="application/json",
                json_type=json_type,
                json_body=payload,
                producer_agent_id=self._producer_agent_id,
                metadata={"debug": True},
            )
        )
        artifact_id = artifact_ref.artifact_id
        await self.send_json_artifact(
            context=context,
            event_queue=event_queue,
            payload=payload,
            name=name,
            description=description,
            json_type=json_type,
            artifact_id=artifact_id,
            metadata={"debug": True, "json_type": json_type},
        )
        await self.send_status_update(
            context=context,
            event_queue=event_queue,
            message=f"Created JSON artifact {artifact_id}.",
        )
        await self.send_conversation_message(
            context=context,
            event_queue=event_queue,
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
