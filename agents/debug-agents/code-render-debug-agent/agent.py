"""
Code Render Debug Agent.

Purpose:
- Return a fixed, hand-written sample file per language so the chat UI's code viewer
  (syntax highlighting, language detection, artifact routing) can be inspected by eye.
- Stay deterministic: file bodies come from checked-in ``samples/`` files (no LLM, clock
  or randomness). Only artifact ids are random uuid4 values.

Each skill returns one sample as an inline text artifact. Optional inputs shape it:
- ``lines``: cut the sample to its first N lines, or pad it to N lines with numbered
  filler lines; ``0`` yields an empty file.
- ``routing``: which signals the backend gets to route on (file name, MIME type, or both).
"""

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from prometheus_api.agent import ArtifactReference, PrometheusAgent

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"

# 20000 lines of filler is ~350-400 KB, past the viewer's 200 KB highlight cutoff, so the
# unhighlighted fallback can be exercised too.
MAX_LINES = 20000

ROUTING_MODES = ("both", "extension", "mime")

# Name used in "mime" routing: deliberately has no extension or well-known basename.
NEUTRAL_NAME = "sample"


@dataclass(frozen=True)
class SampleSpec:
    """One sample file and how it should be presented."""

    language: str  # also the sample file stem and the artifact tag
    filename: str  # extension (or well-known basename) that routes it to the code viewer
    mime_type: Optional[str]  # None when no MIME type routes this language to `code`
    pad: str  # filler line in this language's comment syntax; takes ``{n}``

    @property
    def skill_id(self) -> str:
        return f"render_{self.language}_sample"

    @property
    def sample_path(self) -> Path:
        return SAMPLES_DIR / f"{self.language}.sample"


_SPECS = (
    SampleSpec("yaml", "sample.yaml", "application/yaml", "# padding line {n:05d}"),
    SampleSpec("moose", "input.i", "text/x-moose", "# padding line {n:05d}"),
    SampleSpec("python", "sample.py", "text/x-python", "# padding line {n:05d}"),
    # .json / application/json route to the interactive JSON viewer, so the code viewer's
    # JSON is reached by the .jsonc extension, and no MIME type routes to it.
    SampleSpec("json", "sample.jsonc", None, ""),
    SampleSpec("toml", "sample.toml", "application/toml", "# padding line {n:05d}"),
    SampleSpec("xml", "sample.xml", "application/xml", "<!-- padding line {n:05d} -->"),
    SampleSpec("c", "sample.c", "text/x-csrc", "// padding line {n:05d}"),
    SampleSpec("cpp", "sample.cpp", "text/x-c++src", "// padding line {n:05d}"),
    SampleSpec("fortran", "sample.f90", "text/x-fortran", "! padding line {n:05d}"),
    SampleSpec("cmake", "CMakeLists.txt", "text/x-cmake", "# padding line {n:05d}"),
    SampleSpec("makefile", "Makefile", "text/x-makefile", "# padding line {n:05d}"),
    SampleSpec("bash", "sample.sh", "application/x-sh", "# padding line {n:05d}"),
    SampleSpec("dockerfile", "Dockerfile", "text/x-dockerfile", "# padding line {n:05d}"),
    SampleSpec("ini", "sample.ini", None, "; padding line {n:05d}"),
    SampleSpec("sql", "sample.sql", "application/sql", "-- padding line {n:05d}"),
    SampleSpec("javascript", "sample.js", "text/javascript", "// padding line {n:05d}"),
    SampleSpec("typescript", "sample.ts", "application/typescript", "// padding line {n:05d}"),
    # A leading space makes the filler a diff context line.
    SampleSpec("diff", "sample.diff", "text/x-diff", " padding line {n:05d}"),
    SampleSpec("log", "sample.log", None, "2026-10-07T00:00:00Z DEBUG padding line {n:05d}"),
    SampleSpec("text", "sample.txt", None, "padding line {n:05d}"),
)

SAMPLES: Dict[str, SampleSpec] = {spec.skill_id: spec for spec in _SPECS}


def parse_lines(raw: Any) -> Optional[int]:
    """Validate the ``lines`` input: ``None`` (natural length) or an int in 0..MAX_LINES."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        raise ValueError("lines must be an integer")
    try:
        value = float(str(raw))
    except ValueError as exc:
        raise ValueError("lines must be an integer") from exc
    if value != int(value):
        raise ValueError("lines must be an integer")
    count = int(value)
    if not 0 <= count <= MAX_LINES:
        raise ValueError(f"lines must be between 0 and {MAX_LINES}")
    return count


def _json_body(lines: int) -> str:
    """A valid JSON document that pretty-prints to exactly ``lines`` lines."""
    if lines == 0:
        return ""
    if lines == 1:
        return "{}\n"
    if lines == 2:
        return "{\n}\n"
    if lines == 3:
        document: Dict[str, Any] = {"rows": []}
    elif lines == 4:
        document = {"name": "sample", "rows": []}
    else:
        # `{`, `"rows": [`, the rows, `]`, `}`
        document = {"rows": [f"row-{index:05d}" for index in range(1, lines - 3)]}
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def build_body(spec: SampleSpec, lines: Optional[int] = None) -> str:
    """The sample's text, optionally cut or padded to exactly ``lines`` lines."""
    if lines is not None and spec.language == "json":
        # Cutting or padding would break the JSON, so build a valid document instead.
        return _json_body(lines)
    text = spec.sample_path.read_text(encoding="utf-8")
    if lines is None:
        return text
    rows = text.splitlines()
    if lines <= len(rows):
        rows = rows[:lines]
    else:
        rows += [spec.pad.format(n=index) for index in range(1, lines - len(rows) + 1)]
    return "\n".join(rows) + "\n" if rows else ""


def resolve_routing(spec: SampleSpec, routing: str) -> Optional[Tuple[str, Optional[str]]]:
    """``(artifact name, MIME type)`` for a routing mode, or ``None`` if impossible."""
    if routing == "extension":
        return spec.filename, None
    if routing == "mime":
        if spec.mime_type is None:
            return None
        return NEUTRAL_NAME, spec.mime_type
    return spec.filename, spec.mime_type


class CodeRenderDebugAgent(PrometheusAgent):
    """Debug-only producer of deterministic source-file artifacts for the code viewer."""

    @staticmethod
    def _error(message: str, **extra: Any) -> Dict[str, Any]:
        return {"status": "error", "message": message, **extra}

    async def _handle_sample(
        self,
        spec: SampleSpec,
        params: Dict[str, Any],
        context: RequestContext,
        event_queue: EventQueue,
    ) -> Dict[str, Any]:
        try:
            lines = parse_lines(params.get("lines"))
        except ValueError as exc:
            return self._error(str(exc))

        routing = str(params.get("routing") or "both").strip().lower()
        if routing not in ROUTING_MODES:
            return self._error(f"routing must be one of: {', '.join(ROUTING_MODES)}")
        resolved = resolve_routing(spec, routing)
        if resolved is None:
            return self._error(
                f"No MIME type routes {spec.language} to the code viewer; "
                "use routing 'both' or 'extension'."
            )
        name, mime_type = resolved

        body = build_body(spec, lines)
        line_count = len(body.splitlines())
        encoded = body.encode("utf-8")
        sha256 = hashlib.sha256(encoded).hexdigest()

        await self.send_status_update(
            context=context,
            event_queue=event_queue,
            message=f"Rendering {spec.language} sample ({line_count} lines).",
        )

        artifact_id = str(uuid.uuid4())
        self.register_artifact_reference(
            context,
            ArtifactReference(
                artifact_id=artifact_id,
                conversation_id="",
                name=name,
                description=f"Deterministic {spec.language} sample for code viewer testing ({line_count} lines).",
                mime_type=mime_type,
                text_body=body,
                size_bytes=len(encoded),
                tags=["debug", "code", spec.language],
            ),
        )
        await self.send_text_artifact(context, event_queue, text=body, name=name, artifact_id=artifact_id)

        return {
            "status": "created",
            "language": spec.language,
            "artifact_id": artifact_id,
            "artifact_name": name,
            "mime_type": mime_type,
            "routing": routing,
            "line_count": line_count,
            "sha256": sha256,
        }

    async def _execute(
        self,
        params: Dict[str, Any],
        context: RequestContext,
        event_queue: EventQueue,
    ) -> Dict[str, Any]:
        """Dispatch on the invoked skill_id (injected by the base executor)."""
        skill_id = str(params.get("skill_id") or "").strip()
        spec = SAMPLES.get(skill_id)
        if spec is None:
            return self._error(
                f"Unknown skill {skill_id!r}.",
                available_skills=sorted(SAMPLES),
            )
        return await self._handle_sample(spec, params, context, event_queue)


if __name__ == "__main__":
    agent = CodeRenderDebugAgent(agent_name="Code Render Debug Agent")
    agent.run(port=int(os.getenv("AGENT_PORT", "8000")))
