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

"""Workflow templates for the browser, read from the client-agent's workflow library.

``GET /api/workflows`` lists every template, sorted by ``name``, then ``workflow_id``;
``GET /api/workflows/{workflow_id}`` returns one template with its inputs and graph.
Both read the client-agent's ``GET /workflows/templates`` (Bearer ``AGENT_SECRET``) on
every request; the backend stores nothing.

The listed ``workflow_id`` is the id chat takes (``ChatMessageRequest.workflow_id``):
chat runs a workflow from the same library, so every listed template can run.

These are session-cookie routes. When the client-agent cannot be reached, times out,
answers non-2xx or malformed JSON, or reports the library off, the list degrades to
``{available: false, workflows: []}`` with a 200, and the one-template route answers
503. A template that does not validate is dropped with a logged warning; it never
fails the request.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import ValidationError

from app.a2a_client import A2AClient
from app.api_responses import AUTH_RESPONSES, error
from app.config import settings
from app.contract import Workflow, WorkflowDetail, WorkflowListResponse
from app.openapi import SESSION_COOKIE, TAG_WORKFLOWS
from app.security import current_claims

logger = logging.getLogger(__name__)

_LIBRARY_UNAVAILABLE = "Workflow library is unavailable"
_NOT_FOUND = "Workflow not found"

router = APIRouter(
    prefix="/api/workflows",
    tags=[TAG_WORKFLOWS],
    responses=AUTH_RESPONSES,
    dependencies=[Depends(SESSION_COOKIE), Depends(current_claims)],
)


def _get_a2a_client() -> A2AClient:
    return A2AClient(agent_url=settings.agent_url, agent_secret=settings.agent_secret)


async def _load_templates() -> Optional[list[WorkflowDetail]]:
    """The library's valid templates, or ``None`` when the library is unavailable or off."""
    try:
        payload = await _get_a2a_client().list_workflow_templates()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Workflow library read failed: %s", exc)
        return None
    if payload.get("enabled") is not True:
        return None
    raw = payload.get("workflows")
    templates: list[WorkflowDetail] = []
    for entry in raw if isinstance(raw, list) else []:
        try:
            templates.append(WorkflowDetail.model_validate(entry))
        except ValidationError:
            # The id only: a ValidationError's text repeats the entry's values.
            workflow_id = entry.get("workflow_id") if isinstance(entry, dict) else None
            logger.warning("Dropping malformed workflow template %r", workflow_id)
    return templates


@router.get("", summary="List workflow templates", response_model=WorkflowListResponse)
async def list_workflows() -> WorkflowListResponse:
    """Every workflow template, sorted by `name`, then `workflow_id`, without its inputs or graph.

    When the workflow library is unreachable or off, answers 200 with `available: false`
    and no workflows, rather than an error.
    """
    templates = await _load_templates()
    if templates is None:
        return WorkflowListResponse(available=False, workflows=[])
    templates.sort(key=lambda t: (t.name, t.workflow_id))
    workflows = [Workflow.model_validate(t.model_dump(exclude={"inputs", "graph"})) for t in templates]
    return WorkflowListResponse(available=True, workflows=workflows)


@router.get(
    "/{workflow_id}",
    summary="Get a workflow template",
    response_model=WorkflowDetail,
    responses={
        **error(status.HTTP_404_NOT_FOUND, "The workflow library has no template with this id.", _NOT_FOUND),
        **error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The workflow library is unreachable or off.",
            _LIBRARY_UNAVAILABLE,
        ),
    },
)
async def get_workflow(
    workflow_id: str = Path(description="The workflow's library id, as `GET /api/workflows` lists it."),
) -> WorkflowDetail:
    """One workflow template with its inputs and its graph of nodes and edges."""
    templates = await _load_templates()
    if templates is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_LIBRARY_UNAVAILABLE)
    for template in templates:
        if template.workflow_id == workflow_id:
            return template
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
