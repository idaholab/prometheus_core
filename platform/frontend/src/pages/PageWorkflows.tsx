// This file is part of Prometheus
// https://inl.gov/super-intelligence/prometheus/
//
// Copyright 2026 Battelle Energy Alliance, LLC
// All rights reserved, see NOTICE.txt for full restrictions
// https://github.com/idaholab/prometheus_core/blob/main/NOTICE.txt
//
// Licensed under the MIT License, please see LICENSE for details
// https://github.com/idaholab/prometheus_core/blob/main/LICENSE
//
// SPDX-License-Identifier: MIT

import { useState } from "react";
import { usePageHeader } from "@/features/shell";
import { WorkflowBuilder } from "@/features/workflows";
import { WorkflowConsole } from "@/features/workflows";
import type { WorkflowGraphNode, WorkflowGraphWire } from "@/features/workflows";
import type { WorkflowPlan } from "@/features/workflows";
import type { WorkflowTemplate } from "@/features/workflows";
import { BUILDER_NODES, BUILDER_WIRES, INSPECTED_NODE, SKILL_GROUPS } from "@/features/workflows";

// Placeholder graph for Comprehensive Material Analysis, laid out as in Figma D.1.
const EXAMPLE_NODES: WorkflowGraphNode[] = [
  {
    id: "retrieve",
    type: "agent",
    position: { x: 286, y: 16 },
    data: { name: "Retrieve Material", status: "done", input: "material_id", output: "material_data", est: "8s", width: 200 },
  },
  {
    id: "radiation",
    type: "agent",
    position: { x: 94, y: 190 },
    data: { name: "Radiation", status: "queued", input: "material_data", output: "rad_result", est: "40s", width: 176 },
  },
  {
    id: "corrosion",
    type: "agent",
    position: { x: 298, y: 190 },
    data: { name: "Corrosion", status: "queued", input: "material_data", output: "corr_result", est: "35s", width: 176 },
  },
  {
    id: "thermal",
    type: "agent",
    position: { x: 502, y: 190 },
    data: { name: "Thermal", status: "queued", input: "material_data", output: "therm_result", est: "50s", width: 176 },
  },
  { id: "sme-review", type: "checkpoint", position: { x: 365, y: 359 }, data: { name: "SME Review" } },
  {
    id: "synthesize",
    type: "agent",
    position: { x: 276, y: 460 },
    data: { name: "Synthesize Report", status: "blocked", input: "3 results", output: "final_report", est: "15s", width: 220 },
  },
];
const EXAMPLE_WIRES: WorkflowGraphWire[] = [
  { from: "retrieve", to: "radiation" },
  { from: "retrieve", to: "corrosion" },
  { from: "retrieve", to: "thermal" },
  { from: "radiation", to: "sme-review" },
  { from: "corrosion", to: "sme-review" },
  { from: "thermal", to: "sme-review" },
  { from: "sme-review", to: "synthesize" },
];

// Placeholder templates from Figma D.1. Comprehensive Material Analysis is the
// example workflow, so it's shown as selected.
const TEMPLATES: WorkflowTemplate[] = [
  {
    id: "comprehensive-material-analysis",
    name: "Comprehensive Material Analysis",
    complexity: "complex",
    checkpoints: 3,
    agents: 5,
    runtime: "1h 30m",
    speedup: "4.2x",
  },
  {
    id: "shielding-design-optimization",
    name: "Shielding Design Optimization",
    complexity: "complex",
    checkpoints: 2,
    agents: 4,
    runtime: "2h 45m",
    speedup: "6.1x",
  },
  {
    id: "component-stress-qualification",
    name: "Component Stress Qualification",
    complexity: "moderate",
    checkpoints: 4,
    agents: 3,
    runtime: "40m",
    speedup: "3.8x",
  },
  {
    id: "fuel-assembly-qa-pipeline",
    name: "Fuel Assembly QA Pipeline",
    complexity: "simple",
    checkpoints: 2,
    agents: 3,
    runtime: "10m",
    speedup: "5.5x",
  },
];
const SELECTED_TEMPLATE_ID = "comprehensive-material-analysis";

// Placeholder plan for the selected template, from Figma D.1.
const EXAMPLE_PLAN: WorkflowPlan = {
  path: ["Chat", "Workflow Plan", "comprehensive_material_analysis"],
  status: "Orchestrator: Active | Mode: DAG",
  nodes: EXAMPLE_NODES,
  wires: EXAMPLE_WIRES,
  agents: 5,
  pipelineTime: "3hr 40s",
  checkpoints: "2 Active",
  inputs: ["RC-7_assembly.step", "inlet_velocity_vector.config"],
  outputs: ["TH_validation_report.pdf", "velocity_vectors.vtu"],
};

const SELECTED_TEMPLATE_NAME = TEMPLATES.find((t) => t.id === SELECTED_TEMPLATE_ID)?.name ?? "";

type WorkflowsView = "console" | "builder";

/**
 * Workflows section page: owns the page's data and header, and which view is
 * showing: the Workflow Console, or the Builder opened from its "Modify Plan".
 * Layout lives in WorkflowConsole and WorkflowBuilder.
 *
 * Until the router lands (RT-1), the Builder is a view here rather than its
 * own route. ProjectView remounts this page on every sidebar click, so
 * clicking Workflows from the Builder returns to the Console.
 */
export function PageWorkflows() {
  const [view, setView] = useState<WorkflowsView>("console");

  if (view === "builder") return <BuilderView />;
  return <ConsoleView onModifyPlan={() => setView("builder")} />;
}

/** Each view sets its own header, so the header switches with the view. */
function ConsoleView({ onModifyPlan }: { onModifyPlan: () => void }) {
  usePageHeader({ title: "Workflow Console" });
  return (
    <WorkflowConsole
      templates={TEMPLATES}
      selectedId={SELECTED_TEMPLATE_ID}
      plan={EXAMPLE_PLAN}
      onModifyPlan={onModifyPlan}
    />
  );
}

function BuilderView() {
  usePageHeader({ trail: ["Workflow Builder"] });
  return (
    <WorkflowBuilder
      name={SELECTED_TEMPLATE_NAME}
      skillGroups={SKILL_GROUPS}
      nodes={BUILDER_NODES}
      wires={BUILDER_WIRES}
      inspected={INSPECTED_NODE}
    />
  );
}
