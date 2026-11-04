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
import { usePageHeader } from "@/lib/store/pageHeader";
import type { SkillGroup } from "../components/workflows/SkillLibrary";
import { WorkflowBuilder } from "../components/workflows/WorkflowBuilder";
import { WorkflowConsole } from "../components/workflows/WorkflowConsole";
import type { WorkflowGraphNode, WorkflowGraphWire } from "../components/workflows/WorkflowGraph";
import type { WorkflowPlan } from "../components/workflows/WorkflowPlanner";
import type { WorkflowTemplate } from "../components/workflows/WorkflowTemplateCard";

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

// Placeholder skill library for the Builder, from Figma D.2.
const SKILL_GROUPS: SkillGroup[] = [
  {
    id: "data",
    label: "Data",
    tone: "data",
    skills: [
      { id: "get-material-data", name: "Get Material Data" },
      { id: "query-artifact-store", name: "Query Artifact Store" },
    ],
  },
  {
    id: "analysis",
    label: "Analysis",
    tone: "analysis",
    skills: [
      { id: "radiation-damage", name: "Radiation Damage" },
      { id: "corrosion", name: "Corrosion" },
      { id: "thermal", name: "Thermal" },
    ],
  },
  {
    id: "synthesis",
    label: "Synthesis",
    tone: "analysis",
    skills: [{ id: "synthesize-report", name: "Synthesize Report" }],
  },
  {
    id: "control",
    label: "Control",
    tone: "control",
    skills: [
      { id: "checkpoint-sme", name: "Checkpoint (SME)" },
      { id: "qa-gate", name: "QA Gate" },
    ],
  },
];

// Placeholder Builder graph for Comprehensive Material Analysis, laid out as in
// Figma D.2 at 100%: positions are from the canvas's top left. Radiation Damage
// is shown selected, and Corrosion's output is mid-connection.
const BUILDER_NODES: WorkflowGraphNode[] = [
  {
    id: "get-material-data",
    type: "skill",
    position: { x: 255, y: 70 },
    data: { name: "Get Material Data", tone: "data", input: "material_id", output: "material_data", width: 170 },
  },
  {
    id: "radiation-damage",
    type: "skill",
    position: { x: 140, y: 260 },
    selected: true,
    data: { name: "Radiation Damage", tone: "analysis", input: "material_data", output: "rad_result", width: 170 },
  },
  {
    id: "corrosion",
    type: "skill",
    position: { x: 370, y: 260 },
    data: { name: "Corrosion", tone: "analysis", input: "material_data", output: "corr_result", width: 170 },
  },
  { id: "corrosion-drop", type: "connect", position: { x: 345, y: 464 }, data: { label: "drop to connect →" } },
];
const BUILDER_WIRES: WorkflowGraphWire[] = [
  { from: "get-material-data", to: "radiation-damage" },
  { from: "get-material-data", to: "corrosion" },
  { from: "corrosion", to: "corrosion-drop", dashed: true },
];

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
  return <WorkflowBuilder name={SELECTED_TEMPLATE_NAME} skillGroups={SKILL_GROUPS} nodes={BUILDER_NODES} wires={BUILDER_WIRES} />;
}
