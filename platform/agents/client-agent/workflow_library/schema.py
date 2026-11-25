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

"""Workflow definition schema for YAML-based workflow templates."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class WorkflowSemanticFallback(BaseModel):
    enabled: bool = False
    min_confidence: float = 0.8


class WorkflowMatching(BaseModel):
    priority: int = 0
    patterns: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    semantic_fallback: WorkflowSemanticFallback = Field(default_factory=WorkflowSemanticFallback)


class WorkflowInputs(BaseModel):
    required: List[str] = Field(default_factory=list)
    optional: List[str] = Field(default_factory=list)


class WorkflowExecution(BaseModel):
    mode: Literal["dag", "sequential", "parallel"] = "sequential"
    max_concurrency: int = 3
    on_error: Literal["fail_fast", "continue_with_partial"] = "fail_fast"


class WorkflowStep(BaseModel):
    id: str
    skill_id: str
    depends_on: List[str] = Field(default_factory=list)
    params: Dict[str, Any] = Field(default_factory=dict)
    outputs: List[Dict[str, Any]] = Field(default_factory=list)
    when: Dict[str, Any] = Field(default_factory=dict)
    is_final: bool = False


class WorkflowOutputs(BaseModel):
    final: Dict[str, Any] = Field(default_factory=dict)


class WorkflowMetadata(BaseModel):
    requires_approval: bool = False
    estimated_duration_seconds: Optional[int] = None
    owner: Optional[str] = None
    source_agent_id: Optional[str] = None
    source_agent_url: Optional[str] = None


class WorkflowUiInputOverride(BaseModel):
    label: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    unit: Optional[str] = None
    options: Optional[List[Any]] = None


class WorkflowUi(BaseModel):
    category: Optional[str] = None
    display_name: Optional[str] = None
    summary: Optional[str] = None
    complexity: Optional[Literal["complex", "moderate", "simple"]] = None
    speedup: Optional[float] = None
    input_overrides: Dict[str, WorkflowUiInputOverride] = Field(default_factory=dict)


class WorkflowDefinition(BaseModel):
    id: str
    name: str
    version: str
    description: str
    matching: WorkflowMatching = Field(default_factory=WorkflowMatching)
    inputs: WorkflowInputs = Field(default_factory=WorkflowInputs)
    execution: WorkflowExecution = Field(default_factory=WorkflowExecution)
    steps: List[WorkflowStep] = Field(default_factory=list)
    outputs: WorkflowOutputs = Field(default_factory=WorkflowOutputs)
    metadata: WorkflowMetadata = Field(default_factory=WorkflowMetadata)
    ui: WorkflowUi = Field(default_factory=WorkflowUi)


@dataclass(frozen=True)
class CompiledPattern:
    """Compiled deterministic query pattern."""

    source: str
    regex: Any
    placeholder_names: List[str] = field(default_factory=list)
    specificity: int = 0


@dataclass
class CompiledWorkflow:
    """Compiled workflow with validation metadata and compiled patterns."""

    definition: WorkflowDefinition
    source_path: Path
    compiled_patterns: List[CompiledPattern] = field(default_factory=list)
    required_input_paths: List[str] = field(default_factory=list)
    step_ids: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.definition.id

    @property
    def version(self) -> str:
        return self.definition.version

    @property
    def key(self) -> str:
        return f"{self.definition.id}:{self.definition.version}"
