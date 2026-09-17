"""Structured contracts and data models for planner execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class NewTaskResolutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    standalone_request: str = Field(min_length=1)


class RepeatTaskResolutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    standalone_request: str = Field(min_length=1)
    referenced_invocation_id: str = Field(min_length=1)


class PriorResultDiscussionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)
    referenced_invocation_id: Optional[str] = None


class ClarificationResolutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)


class TurnResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    resolution_kind: Literal[
        "new_task",
        "repeat_prior_task_with_changes",
        "discuss_prior_result",
        "needs_clarification",
    ]
    standalone_request: str = ""
    referenced_invocation_id: Optional[str] = None
    message: str = ""


class DecomposeTaskInput(BaseModel):
    """Flat decomposition payload.

    ``operation_descriptions`` is a list of plain strings rather than a list of
    single-field objects: the flat form keeps ``$defs``/``$ref`` out of the
    advertised tool schema and gives the model one less nesting level to get
    wrong.
    """

    model_config = ConfigDict(extra="forbid")

    operation_descriptions: List[str] = Field(min_length=1)


class AssignDependenciesInput(BaseModel):
    """Dependency edges keyed by operation id.

    The wrapper property is deliberately *not* named ``dependencies``: a payload
    named the same as its wrapper invites the model to repeat the key
    (``{"dependencies": {"dependencies": {...}}}``).
    """

    model_config = ConfigDict(extra="forbid")

    depends_on_by_operation: Dict[str, List[str]]


class RequestedOperation(BaseModel):
    """Immutable operation from capability-neutral request decomposition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str
    description: str
    depends_on: List[str] = Field(default_factory=list)


class TaskDecomposition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operations: List[RequestedOperation]


class CoveredOperationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str
    skill_id: str


class UnsupportedOperationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str
    reason: str = Field(min_length=1)


class SetOperationCoverageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    covered: List[CoveredOperationInput] = Field(default_factory=list)
    unsupported: List[UnsupportedOperationInput] = Field(default_factory=list)


class SelectCapabilitiesInput(BaseModel):
    primary_skill: str = Field(description="Primary skill id to execute")
    supporting_skills: List[str] = Field(
        default_factory=list,
        description="Optional supporting skill ids",
    )
    workflow_type: Literal["single", "parallel", "sequential"] = Field(
        default="single",
        description="Execution workflow semantics",
    )
    reasoning: str = Field(
        default="",
        description="Short explanation for why these skills are selected",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Planner confidence in the skill selection",
    )


class SelectWorkflowTemplateInput(BaseModel):
    workflow_id: str = Field(description="Workflow template id")
    workflow_version: Optional[str] = Field(default=None, description="Specific version (optional)")
    reasoning: str = Field(default="", description="Short rationale for selecting this workflow")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class SelectRegisteredWorkflowInput(BaseModel):
    reasoning: str = Field(default="", description="Short rationale for selecting this workflow")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class SetPlanStepsInput(BaseModel):
    steps: List[str] = Field(
        default_factory=list,
        description="Human-readable plan steps for UI confirmation",
    )
    estimated_duration_seconds: int = Field(
        default=120,
        ge=1,
        description="Estimated end-to-end duration in seconds",
    )


class SetUserMessageInput(BaseModel):
    message: str = Field(
        default="",
        description="Message to show to the user with the generated plan",
    )


class PlanningResult(BaseModel):
    """Structured planner output consumed by ``agent.py`` chat flow."""

    outcome: Literal["agent_plan", "fallback", "unsupported"] = "agent_plan"
    message: str = ""
    workflow_id: Optional[str] = None
    workflow_version: Optional[str] = None
    workflow_match_score: Optional[float] = None
    selection_source: Optional[str] = None
    primary_skill: Optional[str] = None
    supporting_skills: List[str] = Field(default_factory=list)
    workflow_type: Literal["single", "parallel", "sequential", "workflow_template"] = "single"
    confidence: float = 0.5
    reasoning: str = ""
    extracted_params: Dict[str, Any] = Field(default_factory=dict)
    steps: List[str] = Field(default_factory=list)
    estimated_duration_seconds: int = 120
    operations: List[RequestedOperation] = Field(default_factory=list)
    operation_coverage: Dict[str, str] = Field(default_factory=dict)
    unsupported_operations: List[UnsupportedOperationInput] = Field(default_factory=list)
    resolved_query: str = ""
    resolution_kind: Optional[
        Literal[
            "new_task",
            "repeat_prior_task_with_changes",
            "discuss_prior_result",
            "needs_clarification",
        ]
    ] = None
    referenced_invocation_id: Optional[str] = None


@dataclass
class _PlanDraft:
    """Mutable draft updated via planning tools during a single planning session."""

    outcome: Literal["agent_plan", "fallback", "unsupported"] = "agent_plan"
    message: str = ""
    workflow_id: Optional[str] = None
    workflow_version: Optional[str] = None
    workflow_match_score: Optional[float] = None
    selection_source: Optional[str] = None
    primary_skill: Optional[str] = None
    supporting_skills: List[str] = field(default_factory=list)
    workflow_type: Literal["single", "parallel", "sequential", "workflow_template"] = "single"
    confidence: float = 0.5
    reasoning: str = ""
    extracted_params: Dict[str, Any] = field(default_factory=dict)
    steps: List[str] = field(default_factory=list)
    estimated_duration_seconds: int = 120
    operations: List[RequestedOperation] = field(default_factory=list)
    covered_operations: Dict[str, str] = field(default_factory=dict)
    unsupported_operations: Dict[str, str] = field(default_factory=dict)
    resolved_query: str = ""
    resolution_kind: Optional[str] = None
    referenced_invocation_id: Optional[str] = None
    finalized: bool = False

    def to_result(self) -> PlanningResult:
        return PlanningResult(
            outcome=self.outcome,
            message=self.message,
            workflow_id=self.workflow_id,
            workflow_version=self.workflow_version,
            workflow_match_score=self.workflow_match_score,
            selection_source=self.selection_source,
            primary_skill=self.primary_skill,
            supporting_skills=list(self.supporting_skills),
            workflow_type=self.workflow_type,
            confidence=self.confidence,
            reasoning=self.reasoning,
            extracted_params=dict(self.extracted_params),
            steps=list(self.steps),
            estimated_duration_seconds=self.estimated_duration_seconds,
            operations=list(self.operations),
            operation_coverage=dict(self.covered_operations),
            unsupported_operations=[
                UnsupportedOperationInput(operation_id=operation_id, reason=reason)
                for operation_id, reason in self.unsupported_operations.items()
            ],
            resolved_query=self.resolved_query,
            resolution_kind=self.resolution_kind,
            referenced_invocation_id=self.referenced_invocation_id,
        )


@dataclass
class WorkflowPlanningCandidate:
    """Workflow candidate exposed to planner tools."""

    workflow_id: str
    workflow_version: str
    score: float
    required_paths: List[str] = field(default_factory=list)
    selection_source: str = "matcher"
    skills: List[str] = field(default_factory=list)
    execution_mode: str = "sequential"
    estimated_duration_seconds: Optional[int] = None
    display_name: Optional[str] = None
    summary: Optional[str] = None
    extracted_params: Dict[str, Any] = field(default_factory=dict)
    tool_name: Optional[str] = None
