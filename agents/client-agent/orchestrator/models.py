from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

from pydantic import BaseModel


class ConversationRequest(BaseModel):
    query: Optional[str] = ""                    # Natural language query (optional for followup/approval)
    conversation_id: Optional[str] = None        # For multi-turn
    followup_answers: Optional[Dict] = None      # Answers to followup questions
    plan_approved: Optional[bool] = False        # Approval to execute plan
    artifacts: Optional[List[Dict[str, Any]]] = None  # Conversation artifact references (metadata only)
    workflow_id: Optional[str] = None            # Explicit workflow template selection
    workflow_version: Optional[str] = None       # Optional explicit workflow version
    selection_source: Optional[str] = None       # catalog|matcher|dynamic_router
    uploaded_files: Optional[List[Dict[str, Any]]] = None  # Raw files attached by the user this turn
    newly_uploaded_artifact_ids: Optional[List[str]] = None  # Set by _execute after upload; transient
    received_files: Optional[List[Dict[str, Any]]] = None  # Uploaded files received but not stored this turn


class ConversationResponse(BaseModel):
    conversation_id: str
    status: str  # "needs_info" | "plan_ready" | "executing" | "completed" | "recommendation" | "answer"
    message: Optional[str] = None

    # When status == "needs_info"
    followup_questions: Optional[List[Dict]] = None

    # When status == "plan_ready"
    plan: Optional[Dict] = None

    # When status == "completed"
    report: Optional[str] = None
    tool_results: Optional[Dict] = None

    # When status == "recommendation" or "answer"
    response_text: Optional[str] = None
    recommended_materials: Optional[List[str]] = None
    artifacts: Optional[List[Dict[str, Any]]] = None
    message_metadata: Optional[Dict[str, Any]] = None


class AgentState(TypedDict):
    """State for a conversation's orchestration lifecycle."""
    messages: List[Dict[str, Any]]

    # Conversation tracking
    conversation_id: Optional[str]
    user_query: Optional[str]
    conversation_history: List[Dict]

    # Dynamic routing decision
    routing_decision: Optional[Dict[str, Any]]  # Full RoutingDecision.to_dict()

    # Planning phase
    plan: Optional[Dict]
    missing_info: List[str]
    awaiting_approval: bool

    # All pending INPUT_REQUIRED requests from subagents in the current invocation.
    # Each entry has: skill_id, a2a_context_id, a2a_task_id, missing_inputs, hint.
    pending_subagent_requests: List[Dict[str, Any]]

    # Query parameters (extracted from routing decision)
    material_id: Optional[str]
    analysis_types: Optional[List[str]]
    context: Optional[Dict[str, Any]]
    question: Optional[str]

    # Results
    tool_results: Dict[str, Any]
    final_report: Optional[str]
