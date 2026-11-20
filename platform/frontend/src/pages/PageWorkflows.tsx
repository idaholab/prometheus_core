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
import { LayoutWorkflowBuilder } from "@/features/workflows";
import { LayoutWorkflowConsole } from "@/features/workflows";
import type { BuilderMode, WorkflowGraphNode, WorkflowGraphWire } from "@/features/workflows";
import type { WorkflowPlan } from "@/features/workflows";
import type { WorkflowTemplate } from "@/features/workflows";
import {
  BUILDER_NODES,
  BUILDER_WIRES,
  INSPECTED_NODE,
  RUN_NODES,
  SKILL_GROUPS,
  TWEAKED_STEP,
  UNSAVED_CHANGES,
  VERSION_DETAILS,
  WORKFLOW_VERSIONS,
} from "@/features/workflows";

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
  templateName: "Comprehensive Material Analysis",
  inputs: ["RC-7_assembly.step", "inlet_velocity_vector.config"],
  outputs: ["TH_validation_report.pdf", "velocity_vectors.vtu"],
};

const SELECTED_TEMPLATE_NAME = TEMPLATES.find((t) => t.id === SELECTED_TEMPLATE_ID)?.name ?? "";

// Placeholder versions of the selected template, from Figma PPLT-409 D.2a and D.2b.
const TEMPLATE_VERSION = "v1.2.0";
const NEXT_TEMPLATE_VERSION = "v1.3.0";

/** What the Builder opens on: the selected template, or a new workflow's empty canvas (D.3). */
type BuilderStart = { mode: BuilderMode; isNew: boolean };

/**
 * Workflows section page: owns the page's data and header, and which view is
 * showing: the Workflow Console, or the Builder opened from its "Modify Plan"
 * (in either mode) or "+ New Workflow". Layout lives in LayoutWorkflowConsole and
 * LayoutWorkflowBuilder.
 *
 * The Builder is a view here rather than its own route until PPLT-240 gives
 * it a URL. LayoutApp remounts this page on every sidebar click, so clicking
 * Workflows from the Builder returns to the Console.
 */
export function PageWorkflows() {
  const [builder, setBuilder] = useState<BuilderStart | null>(null);

  if (builder) return <BuilderView start={builder} />;
  return (
    <ConsoleView
      onModifyPlan={(mode) => setBuilder({ mode, isNew: false })}
      onNewWorkflow={() => setBuilder({ mode: "template", isNew: true })}
    />
  );
}

/** Each view sets its own header, so the header switches with the view. */
function ConsoleView({
  onModifyPlan,
  onNewWorkflow,
}: {
  onModifyPlan: (mode: BuilderMode) => void;
  onNewWorkflow: () => void;
}) {
  usePageHeader({ title: "Workflow Console" });
  return (
    <LayoutWorkflowConsole
      templates={TEMPLATES}
      selectedId={SELECTED_TEMPLATE_ID}
      plan={EXAMPLE_PLAN}
      onModifyPlan={onModifyPlan}
      onNewWorkflow={onNewWorkflow}
    />
  );
}

function BuilderView({ start }: { start: BuilderStart }) {
  usePageHeader({ trail: ["Workflow Builder"] });
  const [mode, setMode] = useState(start.mode);
  // Nothing can change the structure yet, so the template opened from "Edit
  // the template" starts with placeholder unsaved changes, and switching to
  // this run asks first (D.2d). Switching drops or saves them, so it asks once.
  const [unsaved, setUnsaved] = useState(start.mode === "template" && !start.isNew);
  const changeMode = (next: BuilderMode) => {
    setMode(next);
    if (next === "run") setUnsaved(false);
  };
  return (
    <LayoutWorkflowBuilder
      // Placeholder name until naming a new workflow is designed. D.3 keeps the template's.
      name={SELECTED_TEMPLATE_NAME}
      mode={mode}
      onModeChange={changeMode}
      unsavedChanges={unsaved ? UNSAVED_CHANGES : undefined}
      version={TEMPLATE_VERSION}
      nextVersion={NEXT_TEMPLATE_VERSION}
      skillGroups={SKILL_GROUPS}
      versions={WORKFLOW_VERSIONS}
      versionDetails={VERSION_DETAILS}
      // Selection isn't interactive yet, so each mode shows its frame's
      // selected node: Corrosion changing this run (D.2a), Radiation Damage
      // changing the template (D.2b).
      nodes={start.isNew ? [] : mode === "run" ? RUN_NODES : BUILDER_NODES}
      wires={start.isNew ? [] : BUILDER_WIRES}
      inspected={start.isNew ? null : INSPECTED_NODE}
      tweaked={start.isNew ? null : TWEAKED_STEP}
    />
  );
}
