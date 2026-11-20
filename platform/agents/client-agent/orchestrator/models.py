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

from __future__ import annotations

from typing import Any, Dict, List, NotRequired, Optional, TypedDict

# The frontend <-> client-agent wire contract is owned by prometheus_api;
# re-exported here so orchestrator modules keep importing from .models.
from prometheus_api.contract import (  # noqa: F401
    ConversationRequest,
    ConversationResponse,
    ConversationStatus,
)


class AgentState(TypedDict):
    """Persisted conversation record (Valkey key ``conversation:{id}``)."""

    conversation_id: Optional[str]
    # Latest user query; the backend's chat history falls back to it as a title.
    user_query: Optional[str]
    # Short LLM-generated title for chat history (set once, on the first turn).
    title: Optional[str]

    # User-visible transcript plus evidence (tool inputs/results, forms, plans).
    # The backend's chat history renders the user/assistant entries with content.
    conversation_history: List[Dict[str, Any]]
    # Conversation-scoped context; ``artifacts`` is the artifact catalog.
    context: Dict[str, Any]

    # Orchestration transcript replayed to the LLM (OpenAI message format).
    llm_messages: List[Dict[str, Any]]
    # Unfinished tool calls of the latest assistant message (agent_loop call records).
    pending_calls: List[Dict[str, Any]]
    # Assistant text that accompanied the pending calls, shown with forms/plans.
    pending_note: str
    # Result key (skill_id, then skill_id#2, ... for repeats) -> raw result / arguments
    # of every call in the current user turn.
    turn_tool_results: Dict[str, Any]
    turn_tool_inputs: Dict[str, Any]

    # The user's own words for the request in progress, sent to skill fields
    # marked ``x-prometheus-source: user_message`` (agent_loop.USER_REQUEST_PARTS),
    # and whether a skill has run since, so the next typed message starts anew.
    user_request_parts: NotRequired[List[str]]
    user_request_delivered: NotRequired[bool]

    # Pause bookkeeping, also read by the backend to infer conversation status.
    plan: Optional[Dict[str, Any]]
    missing_info: List[str]
    awaiting_approval: bool
    final_report: Optional[str]
