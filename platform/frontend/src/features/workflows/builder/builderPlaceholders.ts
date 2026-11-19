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

/* Placeholder content for the Workflow Builder, from Figma D.2 to D.6, until
 * workflows come from the backend. Shared by PageWorkflows (D.2) and the
 * dev review page for the other states (src/dev/BuilderStatesHarness.tsx). */
import type { InspectedNode } from "./NodeInspector";
import type { SkillGroup } from "./SkillLibrary";
import type { TweakedStep } from "./TweakStepInspector";
import type { WorkflowVersionDetail } from "@/features/workflows/history/VersionDetail";
import type { WorkflowVersion } from "@/features/workflows/history/VersionItem";
import type { WorkflowGraphNode, WorkflowGraphWire } from "@/features/workflows/graph/WorkflowGraph";

// Placeholder skill library for the Builder, from Figma D.2.
export const SKILL_GROUPS: SkillGroup[] = [
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
export const BUILDER_NODES: WorkflowGraphNode[] = [
  {
    id: "get-material-data",
    type: "skill",
    position: { x: 255, y: 70 },
    data: {
      name: "Get Material Data",
      tone: "analysis",
      input: "material_id",
      inputTone: "data",
      output: "material_data",
      outputTone: "data",
      width: 170,
    },
  },
  {
    id: "radiation-damage",
    type: "skill",
    position: { x: 140, y: 260 },
    selected: true,
    data: {
      name: "Radiation Damage",
      tone: "analysis",
      input: "material_data",
      inputTone: "data",
      output: "rad_result",
      outputTone: "analysis",
      width: 170,
    },
  },
  {
    id: "corrosion",
    type: "skill",
    position: { x: 370, y: 260 },
    data: {
      name: "Corrosion",
      tone: "analysis",
      input: "material_data",
      inputTone: "data",
      output: "corr_result",
      outputTone: "analysis",
      width: 170,
    },
  },
  { id: "corrosion-drop", type: "connect", position: { x: 345, y: 464 }, data: { label: "drop to connect →" } },
];
export const BUILDER_WIRES: WorkflowGraphWire[] = [
  { from: "get-material-data", to: "radiation-damage" },
  { from: "get-material-data", to: "corrosion" },
  { from: "corrosion", to: "corrosion-drop", dashed: true },
];

// Placeholder inspector content for the selected node, Radiation Damage, from
// Figma D.2. Neutron flux is an optional input left unset.
export const INSPECTED_NODE: InspectedNode = {
  name: "Radiation Damage",
  tone: "analysis",
  skillId: "analyze_radiation_damage",
  inputs: [
    { name: "material_id", value: "from input.material_id" },
    { name: "neutron_flux" },
    { name: "temperature_c", value: "from input.context" },
  ],
  outputs: [{ name: "to_context", value: "radiation" }],
};

// Placeholder graph and step for changing this run, from Figma PPLT-409 D.2a:
// D.2's graph with Corrosion selected instead of Radiation Damage. The canvas
// drops the connect endpoint and the half-made wire itself in this mode.
export const RUN_NODES: WorkflowGraphNode[] = BUILDER_NODES.map((node) =>
  node.type === "skill" ? { ...node, selected: node.id === "corrosion" } : node,
);
export const TWEAKED_STEP: TweakedStep = {
  name: "Corrosion",
  tone: "analysis",
  agent: "Corrosion Agent v2.1",
  agentOptions: ["Corrosion Agent v2.0", "Corrosion Agent v1.8"],
  settings: [{ name: "temperature_c", value: "from input.context" }],
};

// Unsaved structural changes to the template, from Figma PPLT-409 D.2d.
// Nothing can change the structure yet, so PageWorkflows treats the template
// opened from "Edit the template" as having these, to show the confirm.
export const UNSAVED_CHANGES = "1 node added, 2 wires changed";

// Placeholder versions of Comprehensive Material Analysis, newest first, from
// Figma D.8 (the Builder's History tab in PPLT-409 D.2c).
export const WORKFLOW_VERSIONS: WorkflowVersion[] = [
  { id: "v1.2.0", version: "v1.2.0", summary: "+ QA Gate after analyses", date: "2 days ago", author: "V. Kerimov", latest: true },
  { id: "v1.1.0", version: "v1.1.0", summary: "Swapped Thermal agent v1.8→v2.0", date: "Oct 1", author: "Dr. Halsey" },
  { id: "v1.0.0", version: "v1.0.0", summary: "Initial template", date: "Sep 12", author: "platform-team" },
];

// Placeholder details for the latest version, v1.2.0, from Figma D.8 (D.2c).
// The older versions have none yet, which is fine while only the latest can be selected.
export const VERSION_DETAILS: WorkflowVersionDetail[] = [
  {
    id: "v1.2.0",
    version: "v1.2.0",
    workflowId: "comprehensive_material_analysis",
    derivedFrom: "v1.1.0",
    changes: [
      { kind: "added", text: "Added QA Gate checkpoint after the parallel analyses" },
      { kind: "changed", text: "SME Review moved below the new QA Gate" },
    ],
    invalidated:
      "3 cached runs of 'Synthesize Report' invalidated — downstream of the new checkpoint. Re-run required for provenance.",
    stats: [
      { label: "Total runs", value: "12", detail: "since 2 days ago" },
      { label: "Last run", value: "4h ago", detail: "Thermal Analysis RC-7" },
      { label: "Status", value: "Active", detail: "current latest" },
    ],
    runIn: [
      { project: "MARVEL Reactor Project", runs: "9 runs" },
      { project: "Fuel Assembly QA — RC-7", runs: "3 runs" },
    ],
  },
];

// The dragging-skill state from Figma D.4, at 100% from the canvas's top left:
// Get Material Data on its own, and Radiation Damage as the ghost of a skill
// being dropped, with the inspector showing it.
export const DRAGGING_NODES: WorkflowGraphNode[] = [
  {
    id: "get-material-data",
    type: "skill",
    position: { x: 110, y: 120 },
    data: {
      name: "Get Material Data",
      tone: "analysis",
      input: "material_id",
      inputTone: "data",
      output: "material_data",
      outputTone: "data",
      width: 170,
    },
  },
  {
    id: "radiation-damage-ghost",
    type: "skill",
    position: { x: 250, y: 250 },
    data: {
      name: "Radiation Damage",
      tone: "analysis",
      input: "material_data",
      inputTone: "data",
      output: "rad_result",
      outputTone: "analysis",
      width: 170,
      ghost: true,
    },
  },
];

// The insert-on-edge state from Figma D.5: Get Material Data wired to Radiation
// Damage (still selected), with the insert menu open on the wire.
export const INSERT_NODES: WorkflowGraphNode[] = [
  {
    id: "get-material-data",
    type: "skill",
    position: { x: 180, y: 70 },
    data: {
      name: "Get Material Data",
      tone: "analysis",
      input: "material_id",
      inputTone: "data",
      output: "material_data",
      outputTone: "data",
      width: 170,
    },
  },
  {
    id: "radiation-damage",
    type: "skill",
    position: { x: 180, y: 300 },
    selected: true,
    data: {
      name: "Radiation Damage",
      tone: "analysis",
      input: "material_data",
      inputTone: "data",
      output: "rad_result",
      outputTone: "analysis",
      width: 170,
    },
  },
];
export const INSERT_WIRES: WorkflowGraphWire[] = [
  { from: "get-material-data", to: "radiation-damage", insertMenu: true },
];

// The invalid-connection state from Figma D.6: Mesh Generator's mesh output
// wired to Radiation Damage's material_data input, which expects material data.
export const INVALID_NODES: WorkflowGraphNode[] = [
  {
    id: "mesh-generator",
    type: "skill",
    position: { x: 120, y: 90 },
    data: {
      name: "Mesh Generator",
      tone: "analysis",
      input: "material_id",
      inputTone: "data",
      output: "mesh",
      outputTone: "data",
      width: 170,
    },
  },
  {
    id: "radiation-damage",
    type: "skill",
    position: { x: 360, y: 320 },
    data: {
      name: "Radiation Damage",
      tone: "analysis",
      input: "material_data",
      inputTone: "data",
      output: "rad_result",
      outputTone: "analysis",
      width: 170,
      invalid: true,
    },
  },
];
export const INVALID_WIRES: WorkflowGraphWire[] = [{ from: "mesh-generator", to: "radiation-damage", invalid: true }];
export const INVALID_ERROR = "Type mismatch: mesh → material_data";
