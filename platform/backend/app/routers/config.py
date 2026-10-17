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

"""GET /api/config — static, session-independent client bootstrap.

Replaces Chainlit's ``set_chat_profiles`` plus the config-derived UI hints the
React app needs before a session exists (intro text, workflow suggestions, upload
limit, auto-approve behavior).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.a2a_client import A2AClient
from app.config import settings
from app.contract import ChatProfile, ConfigResponse
from app.security import TokenClaims, current_claims

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["config"])

# The profile identifier that carries starter suggestions (parallels the
# ``chat_profile == "Beginner Chat"`` branch in ``frontend/main.py`` on_chat_start).
BEGINNER_PROFILE = "Beginner Chat"

# Ported verbatim from ``frontend/main.py`` ``set_chat_profiles``.
CHAT_PROFILES: list[ChatProfile] = [
    ChatProfile(
        name=BEGINNER_PROFILE,
        markdown_description="This profile provides some suggestions on how to get started.",
        icon="https://picsum.photos/id/29/200",
    ),
    ChatProfile(
        name="Advanced Chat",
        markdown_description="This profile doesn't provide any suggestions.",
        icon="https://picsum.photos/id/28/200",
    ),
]


def _get_a2a_client() -> A2AClient:
    return A2AClient(agent_url=settings.agent_url, agent_secret=settings.agent_secret)


@router.get("/config", response_model=ConfigResponse)
async def get_config(claims: TokenClaims = Depends(current_claims)) -> ConfigResponse:
    # Auth-gated (AU-5): profiles/suggestions/limits were behind login in Chainlit; the
    # React app fetches config after authenticating (tasks/frontend Step 02).
    try:
        llm_model = await _get_a2a_client().get_llm_model()
    except Exception as exc:  # the model label is best-effort; never fail the config
        logger.warning("Failed to read the orchestrator LLM model: %s", exc)
        llm_model = None
    return ConfigResponse(
        profiles=CHAT_PROFILES,
        chat_intro=settings.chat_intro,
        chat_suggestion_title=settings.chat_suggestion_title,
        workflow_suggestions=settings.workflow_suggestions,
        auto_approve_steps=settings.auto_approve_steps,
        max_upload_bytes=settings.max_upload_bytes,
        llm_model=llm_model,
    )
