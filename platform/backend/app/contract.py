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

"""Frozen wire contract for the backend HTTP/SSE API.

This module is the single source of truth for the JSON shapes the React frontend
codes against. It is defined **independently** of ``prometheus_api.contract``
(``ConversationRequest`` / ``ConversationResponse``): the backend normalizes
at its service boundary and never leaks base-image types onto its own wire. The
mapping between the two lives in the turn orchestrator (task 04); this file only
declares our public shapes.

Design decisions (from tasks/01-contract.md open questions):

- ``render_hint`` — every artifact carries a classifier-derived ``render_hint``
  (``classify_render_hint`` in ``services/artifacts.py`` fills it) so a thin
  frontend can route without re-implementing MIME/json_type/extension dispatch.
  Raw ``mime_type`` / ``json_type`` / ``tags`` are kept alongside it so the
  frontend can override.
- Session identity — the SSE session token is the auth JWT's subject/session id;
  ``conversation_id`` is carried in session state, never in the request body.
- ``POST /api/sessions`` — sessions are created explicitly, not implicitly on the
  first message.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Optional, Union, cast, get_args

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- #
# Status enum
# --------------------------------------------------------------------------- #


class ChatStatus(str, Enum):
    """Public status set, mirroring ``prometheus_api``'s ``ConversationStatus``.

    String-valued so ``response.status == "completed"`` comparisons work on both
    sides of the wire.
    """

    NEEDS_INFO = "needs_info"  # follow-up questions for the user
    PLAN_READY = "plan_ready"  # plan awaiting user approval
    EXECUTING = "executing"  # plan execution in progress
    COMPLETED = "completed"  # multi-step plan finished, report ready
    RECOMMENDATION = "recommendation"  # direct recommendation answer
    ANSWER = "answer"  # direct single-agent answer
    BACKGROUNDED = "backgrounded"  # turn detached to a background task
    ERROR = "error"  # request failed


# --------------------------------------------------------------------------- #
# DynamicForm field schema (needs_info)
# --------------------------------------------------------------------------- #

FieldInputType = Literal[
    "text",
    "number",
    "email",
    "password",
    "date",
    "datetime",
    "textarea",
    "select",
    "checkbox",
]


_ALLOWED_INPUT_TYPES: frozenset[str] = frozenset(get_args(FieldInputType))


def _coerce_input_type(value: Any) -> FieldInputType:
    """Coerce a raw agent field ``type`` to a known :data:`FieldInputType`.

    Agents emit historically-varying / free-form types (``radio``, ``slider``,
    ``multiselect``, ``""`` …). The old Chainlit form defaulted unknown types to a
    text input (its JSX ``switch`` fell through to ``text``); mirror that here so a
    nonstandard type can never fail contract validation and turn a legitimate
    ``needs_info`` turn into an ``error`` (T-3).
    """
    candidate = str(value).strip().lower() if value else ""
    if candidate in _ALLOWED_INPUT_TYPES:
        return cast("FieldInputType", candidate)
    return "text"


class SelectOption(BaseModel):
    """One option for a ``select`` field."""

    label: str
    value: str


class FormField(BaseModel):
    """A single follow-up form field.

    Matches the props consumed by ``frontend/src/components/chat/FollowupForm.tsx``
    and the normalized shape produced by ``normalize_followup_questions`` below
    (ported from ``message_handler._handle_needs_info``).
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    label: str
    input_type: FieldInputType = "text"
    required: bool = True
    options: Optional[list[SelectOption]] = None
    default: Optional[Any] = None
    help: Optional[str] = None
    placeholder: Optional[str] = None
    rows: Optional[int] = None
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None


def normalize_followup_questions(questions: list[dict[str, Any]]) -> list[FormField]:
    """Normalize raw agent ``followup_questions`` into ``FormField`` objects.

    Ports the field-building loop from ``message_handler._handle_needs_info``
    (frontend/components/message_handler.py ~500-518). Agents emit follow-up
    questions with loose, historically-varying key names; this collapses them to
    the frozen schema:

    - ``id``      ← ``field`` | ``id`` | ``question``
    - ``label``   ← ``question`` | ``label``
    - ``input_type`` ← ``type`` | ``input_type`` (default ``text``)
    - ``options`` — bare scalars become ``{label, value}`` pairs
    - ``help``    ← ``description``
    """
    fields: list[FormField] = []
    for q in questions:
        raw_options = q.get("options")
        options: Optional[list[SelectOption]] = None
        if isinstance(raw_options, list):
            options = []
            for opt in raw_options:
                if isinstance(opt, dict):
                    value = str(opt.get("value", opt.get("label", "")))
                    label = str(opt.get("label", value))
                    options.append(SelectOption(label=label, value=value))
                else:
                    options.append(SelectOption(label=str(opt), value=str(opt)))

        fields.append(
            FormField(
                id=str(q.get("field") or q.get("id") or q.get("question") or ""),
                label=str(q.get("question") or q.get("label") or ""),
                input_type=_coerce_input_type(q.get("type") or q.get("input_type")),
                required=bool(q.get("required", True)),
                options=options,
                default=q.get("default"),
                help=q.get("description") or q.get("help"),
                placeholder=q.get("placeholder"),
                rows=q.get("rows"),
                min=q.get("min"),
                max=q.get("max"),
                step=q.get("step"),
            )
        )
    return fields


# --------------------------------------------------------------------------- #
# Artifact metadata
# --------------------------------------------------------------------------- #

RenderHint = Literal[
    "pdf",  # PDF → PdfViewer
    "image",  # raster image or SVG → ImageViewer (SVG folds into image; no separate svg hint)
    "json",  # JSON → JSONViewer (CollapsibleJson)
    "ifc",  # IFC → IFCViewer
    "mesh",  # Exodus/STL → MeshViewer (shared VTK viewer)
    "mermaid",  # Mermaid diagram → MermaidViewer
    "thermal",  # prometheus.thermal_analysis.result.v1 → ThermalAnalysisViewer
    "uq",  # prometheus.uq.result.v1 → UQDashboard (baked notebook report)
    "report",  # markdown / plain-text report → markdown renderer (rendered inline, not downloaded)
    "code",  # source / config text (YAML, MOOSE .i, Python, ...) → CodeViewer (syntax-highlighted inline, not Markdown)
    "table",  # CSV / TSV → TableViewer (sortable table, raw-text toggle)
    "reference",  # citation / external reference (frontend formats from ``ArtifactMeta.citation``)
    "file",  # generic downloadable file (CAD/step, archives, octet-stream)
    "unknown",  # no viewer; offer download
]
"""Frontend viewer routing hint. This ``Literal`` is the single authoritative list —
``backend/CONTRACT.md`` mirrors it, and ``test_contract_matrix.py`` asserts every
value is reachable so the two cannot drift. Filled by ``classify_render_hint`` in
``services/artifacts.py``. The React adapter (see ``tasks/frontend/README.md`` Step 05)
maps each value onto a viewer; ``report`` renders markdown, ``reference`` a citation card.
Raw ``mime_type`` / ``json_type`` / ``tags`` travel alongside so the frontend can override."""


class Citation(BaseModel):
    """Source / section / page for a ``reference`` (citation) artifact.

    Ported from the old inline citation renderer ``_render_reference_artifact``
    (frontend/components/message_handler.py:1004), which read these from the raw
    artifact ``metadata``. The frontend's citation card formats from these fields;
    without them a ``reference`` artifact loses its provenance on the wire (CON-1).
    (The ``uri`` link and ``name``/``description`` the old renderer also used are
    already top-level :class:`ArtifactMeta` fields.)
    """

    model_config = ConfigDict(extra="ignore")

    source: Optional[str] = None
    section: Optional[str] = None
    page: Optional[str] = None


class ArtifactLink(BaseModel):
    """A link a producing agent attaches to its artifact (``metadata.links``).

    Viewers show these as buttons that open in a new tab, e.g. an interactive
    dashboard the agent serves for that artifact, or the job that produced it.
    Only ``http``/``https`` URLs are kept (see ``services.artifacts``).
    """

    model_config = ConfigDict(extra="ignore")

    label: str
    url: str


class ArtifactMeta(BaseModel):
    """Conversation-scoped artifact reference on our wire.

    Snake_case per the Prometheus catalog convention (see
    docs/docs/dev-docs/artifacts.md). Superset of ``prometheus_api``'s
    ``ArtifactReference`` fields the frontend needs, plus the derived
    ``render_hint``. ``json_body`` is inline-only; bytes are fetched via
    ``GET /api/artifacts/{artifact_id}/content`` (task 07).
    """

    model_config = ConfigDict(extra="ignore")

    artifact_id: str
    name: str = ""
    mime_type: Optional[str] = None
    json_type: Optional[str] = None
    description: str = ""
    uri: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    json_body: Optional[Any] = None  # inline only
    render_hint: RenderHint = "unknown"
    citation: Optional[Citation] = None  # populated for reference/citation artifacts
    producer_agent_id: Optional[str] = None
    created_at: Optional[str] = None
    links: list[ArtifactLink] = Field(default_factory=list)  # from metadata.links
    # True when the producer attached a baked HTML report (metadata.report), served by
    # GET /api/artifacts/{artifact_id}/report.
    has_report: bool = False


# --------------------------------------------------------------------------- #
# Uploads
# --------------------------------------------------------------------------- #


class UploadDescriptor(BaseModel):
    """Returned by ``POST /api/uploads``; echoed back in the next chat request."""

    model_config = ConfigDict(extra="ignore")

    upload_id: str
    name: str
    mime_type: str
    size_bytes: int


# --------------------------------------------------------------------------- #
# Chat request / response
# --------------------------------------------------------------------------- #


class ChatMessageRequest(BaseModel):
    """Frontend → backend body for ``POST /api/chat/messages``.

    Mirrors the args ``A2AClient.send()`` accepts (frontend/utils/a2a_client.py:81).
    ``conversation_id`` is **not** in the body — it comes from session state.
    """

    model_config = ConfigDict(extra="ignore")

    query: str = ""
    followup_answers: Optional[dict[str, Any]] = None
    plan_approved: bool = False
    plan_rejected: bool = False
    workflow_id: Optional[str] = None
    upload_ids: Optional[list[UploadDescriptor]] = None


class ChatMessageResponse(BaseModel):
    """backend → frontend body for ``POST /api/chat/messages``.

    A normalized view of ``prometheus_api``'s ``ConversationResponse``. Fields are
    grouped by the ``status`` that populates them; all are optional so a single
    model round-trips every variant.
    """

    model_config = ConfigDict(extra="ignore", use_enum_values=True)

    turn_id: str
    status: ChatStatus
    message: Optional[str] = None

    # status == needs_info
    followup_questions: Optional[list[FormField]] = None

    # status == plan_ready
    plan: Optional[dict[str, Any]] = None
    auto_approve: bool = False

    # status == completed | answer | recommendation
    report: Optional[str] = None
    response_text: Optional[str] = None
    artifacts: Optional[list[ArtifactMeta]] = None
    recommended_materials: Optional[list[str]] = None
    follow_up_suggestions: Optional[list[str]] = None

    # status == backgrounded
    task_id: Optional[str] = None


# --------------------------------------------------------------------------- #
# SSE events (discriminated union on ``type``)
# --------------------------------------------------------------------------- #


class StatusEvent(BaseModel):
    """Streamed progress line for the in-flight turn."""

    type: Literal["status"] = "status"
    turn_id: str
    message: str
    history: Optional[list[str]] = None


class TaskProgressEvent(BaseModel):
    """Progress line for a detached (backgrounded) task."""

    type: Literal["task_progress"] = "task_progress"
    task_id: str
    message: str


class TaskDoneEvent(BaseModel):
    """Terminal event for a detached task, carrying the final response.

    ``response`` is populated only for ``state == "completed"`` (the mapped answer).
    For non-completed terminal states (failed/canceled/rejected), ``message`` carries
    a human-readable line for the frontend to render (E-5)."""

    type: Literal["task_done"] = "task_done"
    task_id: str
    state: str
    message: Optional[str] = None
    response: Optional[ChatMessageResponse] = None


ServerEvent = Annotated[
    Union[StatusEvent, TaskProgressEvent, TaskDoneEvent],
    Field(discriminator="type"),
]
"""Discriminated union of JSON SSE events.

A ``heartbeat`` is sent as an SSE comment line (``: ping``), not a JSON event, so
it is intentionally not part of this union.
"""


# --------------------------------------------------------------------------- #
# Session / config (POST /api/sessions, GET /api/config)
# --------------------------------------------------------------------------- #


class ChatProfile(BaseModel):
    """A selectable chat profile, mirroring Chainlit's ``cl.ChatProfile``.

    Ported from ``frontend/main.py`` ``set_chat_profiles``. The frontend picks one
    at session creation; ``POST /api/sessions`` echoes the chosen ``profile`` and,
    for the beginner profile, includes ``workflow_suggestions``.
    """

    name: str
    markdown_description: str = ""
    icon: Optional[str] = None


class SessionResponse(BaseModel):
    """Returned by ``POST /api/sessions`` — starts a conversation."""

    conversation_id: str
    profile: str = ""
    chat_intro: str = ""
    chat_suggestion_title: str = ""
    workflow_suggestions: list[str] = Field(default_factory=list)
    auto_approve_steps: bool = False


class ConfigResponse(BaseModel):
    """Returned by ``GET /api/config`` — static, non-session settings."""

    profiles: list[ChatProfile] = Field(default_factory=list)
    chat_intro: str = ""
    chat_suggestion_title: str = ""
    workflow_suggestions: list[str] = Field(default_factory=list)
    auto_approve_steps: bool = False
    max_upload_bytes: int = 0


# --------------------------------------------------------------------------- #
# Conversation history (GET /api/conversations/recent)
# --------------------------------------------------------------------------- #


class ConversationSummary(BaseModel):
    """One recent-conversation row.

    Mirrors the dict shape produced by
    ``ConversationStateClient.get_conversation_history`` (ported from the Chainlit
    ``/history`` command); ``status`` is the client's inferred user-facing status.
    ``title`` is the effective title: a user rename wins over the client-agent's
    LLM-generated title, which wins over the raw first query (``query``).
    ``pending`` is true while a turn is actively running against this
    conversation (``agent:status:{id}.final is False``) — a conversation the
    caller isn't currently viewing may still have work in flight.
    """

    model_config = ConfigDict(extra="ignore")

    conversation_id: str
    title: str = ""
    query: str = ""
    status: str = "unknown"
    timestamp: str = ""
    pending: bool = False


class ConversationHistoryResponse(BaseModel):
    """Returned by ``GET /api/conversations/recent``.

    ``available`` is ``False`` when Redis is unreachable — the endpoint degrades to
    an empty list with a 200 rather than erroring (parallels the Chainlit "History
    unavailable" message).
    """

    available: bool = False
    conversations: list[ConversationSummary] = Field(default_factory=list)


class ConversationMessage(BaseModel):
    """One normalized chat turn, as returned by the conversation-detail/resume
    endpoints. Distinct from the richer live ``ChatMessageResponse``: this is a
    display-only replay of a past turn, not a re-playable turn result."""

    model_config = ConfigDict(extra="ignore")

    role: Literal["user", "assistant"]
    content: str = ""
    timestamp: str = ""
    #: Ids of the artifacts this turn produced, each resolvable in the detail's
    #: ``artifacts``. The frontend renders a restored turn from these alone, never
    #: from the whole catalog. Empty for user turns and for turns stored before
    #: the client-agent recorded them.
    artifact_ids: list[str] = Field(default_factory=list)


class ConversationDetailResponse(BaseModel):
    """Returned by ``GET /api/conversations/{id}`` and ``POST
    /api/conversations/{id}/resume`` — a past conversation's transcript plus
    enough session-bootstrap info for the frontend to resume it.
    """

    model_config = ConfigDict(extra="ignore")

    conversation_id: str
    title: str = ""
    profile: str = ""
    auto_approve_steps: bool = False
    messages: list[ConversationMessage] = Field(default_factory=list)
    artifacts: list[ArtifactMeta] = Field(default_factory=list)


class TaskNodeOut(BaseModel):
    """One Task Graph node, as returned by ``GET /api/conversations/{id}/tasks``.

    Mirrors the client-agent's ``TaskNode`` (agents/client-agent/task_graph.py), minus
    ``conversation_id`` (the request's scope) and ``child_task_ids`` (replaced by the
    nested ``children``). A root is one chat turn; its children are the specialist
    skill dispatches it made. ``state`` is the effective state after the children
    percolate up (an A2A ``TaskState`` string: ``submitted``, ``working``,
    ``input-required``, ``completed``, ``failed``, ``canceled``, ``rejected``);
    ``own_state`` is the node's own. ``is_background`` marks a turn the client-agent
    detached, and the skill that asked for it. Timestamps are ISO-8601 strings.
    """

    model_config = ConfigDict(extra="ignore")

    task_id: str
    parent_task_id: Optional[str] = None
    agent: Optional[str] = None
    skill: Optional[str] = None
    title: str = ""
    state: str
    own_state: Optional[str] = None
    is_background: bool = False
    waiting_on: list[str] = Field(default_factory=list)
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    updated_at: Optional[str] = None
    finished_at: Optional[str] = None
    last_status_message: Optional[str] = None
    progress: Optional[float] = None
    result_ref: Optional[str] = None
    error: Optional[str] = None
    children: list[TaskNodeOut] = Field(default_factory=list)


class ConversationTasksResponse(BaseModel):
    """Returned by ``GET /api/conversations/{id}/tasks``: the conversation's Task
    Graph as a tree of root turns, newest first. Includes finished tasks until their
    nodes expire (24 h by default); filter on ``state`` / ``is_background`` client-side.

    ``available`` is ``False`` when Valkey is unreachable, matching ``recent``.
    """

    available: bool = False
    conversation_id: str
    tasks: list[TaskNodeOut] = Field(default_factory=list)


class ConversationRenameRequest(BaseModel):
    """Body for ``PATCH /api/conversations/{id}``."""

    model_config = ConfigDict(extra="ignore")

    title: str


class ConversationResumeRequest(BaseModel):
    """Optional body for ``POST /api/conversations/{id}/resume``.

    ``bind_seq`` orders session rebinds by click, not by arrival: a resume or new
    session whose seq is not greater than the last one applied leaves the session where
    it is. The frontend sends a strictly increasing value (``Date.now()``-based).
    ``POST /api/sessions`` takes the same field in :class:`CreateSessionRequest`.
    """

    model_config = ConfigDict(extra="ignore")

    bind_seq: Optional[int] = None


class CreateSessionRequest(BaseModel):
    """Optional body for ``POST /api/sessions`` — the selected chat profile, plus the
    ``bind_seq`` that orders this rebind against in-flight resumes (see
    :class:`ConversationResumeRequest`)."""

    profile: Optional[str] = None
    bind_seq: Optional[int] = None
