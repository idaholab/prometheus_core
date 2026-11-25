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

/**
 * Maps the workflow API (`GET /api/workflows`, `GET /api/workflows/{id}`) to
 * what the Workflow Console draws: a `WorkflowTemplate` card per template and
 * a `WorkflowPlan` for the selected one.
 *
 * A nullable figure (complexity, runtime, speed-up) maps to null, which the
 * card and the planner hide; no placeholder stands in for it. The wire
 * carries no node positions, so `toPlan` lays the graph out in layers.
 * JSX-free; its only runtime import is the pure `@/lib/duration`, so a vitest
 * unit (Node) test can cover it.
 */
import { formatRunTime } from "@/lib/duration";
import type { GraphNode, Workflow, WorkflowDetail, WorkflowGraph } from "@/lib/api/types";
import type { WorkflowGraphNode, WorkflowGraphWire } from "@/features/workflows/graph/WorkflowGraph";
import type { WorkflowPlan } from "./WorkflowPlanner";
import type { WorkflowTemplate } from "./WorkflowTemplateCard";

// placeholder: these stay fixed for now, as the blueprint keeps them (Q12).
export const PLAN_STATUS = "Orchestrator: Active | Mode: DAG";
export const PLAN_INPUTS: string[] = ["RC-7_assembly.step", "inlet_velocity_vector.config"];
export const PLAN_OUTPUTS: string[] = ["TH_validation_report.pdf", "velocity_vectors.vtu"];

const AGENT_NODE_WIDTH = 200;
/** The checkpoint diamond's box (`size-10.5` in WorkflowGraphNodes.tsx). */
const CHECKPOINT_NODE_SIZE = 42;
const ROW_GAP = 170;
const COLUMN_GAP = 220;

/** The stored benchmark speed-up, e.g. 2 -> "2.0x"; the card adds "faster". */
export function formatSpeedup(speedup: number): string {
  return `${speedup.toFixed(1)}x`;
}

export function toTemplate(w: Workflow): WorkflowTemplate {
  return {
    id: w.workflow_id,
    name: w.name,
    complexity: w.complexity,
    checkpoints: w.checkpoint_count,
    agents: w.agent_count,
    runtime: w.estimated_runtime_seconds === null ? null : formatRunTime(w.estimated_runtime_seconds),
    speedup: w.speedup === null ? null : formatSpeedup(w.speedup),
    requiresApproval: w.requires_approval,
    // Only an agent-card workflow names its owner on the card.
    owner: w.source === "agent_card" ? w.owner : null,
  };
}

export function toPlan(d: WorkflowDetail): WorkflowPlan {
  // React Flow keys nodes and edges by id, so only the first of each id is kept.
  const nodes = firstById(d.graph.nodes, (n) => n.node_id);
  const ids = new Set(nodes.map((n) => n.node_id));
  const edges = firstById(d.graph.edges, (e) => e.edge_id).filter(
    (e) => ids.has(e.from_node) && ids.has(e.to_node),
  );
  return {
    path: ["Chat", "Workflow Plan", d.workflow_id],
    status: PLAN_STATUS,
    nodes: layoutGraph({ ...d.graph, nodes, edges }),
    wires: edges.map((e): WorkflowGraphWire => ({
      id: e.edge_id,
      from: e.from_node,
      to: e.to_node,
      kind: e.kind,
    })),
    agents: d.agent_count,
    pipelineTime: d.estimated_runtime_seconds === null ? null : formatRunTime(d.estimated_runtime_seconds),
    checkpoints: String(d.checkpoint_count),
    requiresApproval: d.requires_approval,
    templateName: d.name,
    inputs: PLAN_INPUTS,
    outputs: PLAN_OUTPUTS,
  };
}

function firstById<T>(items: T[], idOf: (item: T) => string): T[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    const id = idOf(item);
    if (seen.has(id)) return false;
    seen.add(id);
    return true;
  });
}

/**
 * A required input with a source names its port; several give "<n> inputs";
 * none gives "—". A literal value (`source: null`) is not an input.
 */
function inputLabel(node: GraphNode): string {
  const required = node.inputs.filter((i) => i.source !== null && !i.optional);
  if (required.length === 0) return "—";
  return required.length === 1 ? required[0].port : `${required.length} inputs`;
}

function toNode(node: GraphNode, position: { x: number; y: number }): WorkflowGraphNode {
  if (node.kind !== "skill") {
    // Centre the diamond in its column, which is laid out for an agent node's width.
    const x = position.x + (AGENT_NODE_WIDTH - CHECKPOINT_NODE_SIZE) / 2;
    return { id: node.node_id, type: "checkpoint", position: { ...position, x }, data: { name: node.label } };
  }
  // The wire has no step status or estimate, so the node shows neither.
  return {
    id: node.node_id,
    type: "agent",
    position,
    data: {
      name: node.label,
      input: inputLabel(node),
      output: "result",
      width: AGENT_NODE_WIDTH,
    },
  };
}

/**
 * A node's layer is the longest path to it from a node with no incoming edge,
 * over every edge (`order` edges included). Each layer is a row,
 * ROW_GAP below the last; a row keeps the order of `graph.nodes`, COLUMN_GAP
 * apart, centred on the widest row. Nodes on or after a cycle never get a
 * layer, so they go into one last row. Every node id must be unique and every
 * edge must name known nodes.
 */
function layoutGraph(graph: WorkflowGraph): WorkflowGraphNode[] {
  const incoming = new Map<string, number>(graph.nodes.map((n) => [n.node_id, 0]));
  for (const e of graph.edges) incoming.set(e.to_node, (incoming.get(e.to_node) ?? 0) + 1);

  const layer = new Map<string, number>();
  const ready = graph.nodes.filter((n) => incoming.get(n.node_id) === 0).map((n) => n.node_id);
  for (const id of ready) layer.set(id, 0);
  while (ready.length > 0) {
    const from = ready.shift() as string;
    for (const e of graph.edges) {
      if (e.from_node !== from) continue;
      layer.set(e.to_node, Math.max(layer.get(e.to_node) ?? 0, (layer.get(from) ?? 0) + 1));
      const left = (incoming.get(e.to_node) ?? 0) - 1;
      incoming.set(e.to_node, left);
      if (left === 0) ready.push(e.to_node);
    }
  }

  const rows: GraphNode[][] = [];
  const unplaced: GraphNode[] = [];
  for (const node of graph.nodes) {
    // A node still waiting on an edge sits on or after a cycle.
    if ((incoming.get(node.node_id) ?? 0) > 0) {
      unplaced.push(node);
      continue;
    }
    const row = layer.get(node.node_id) ?? 0;
    (rows[row] ??= []).push(node);
  }
  if (unplaced.length > 0) rows.push(unplaced);

  const widest = Math.max(0, ...rows.map((row) => row.length));
  return rows.flatMap((row, r) => {
    const offset = ((widest - row.length) * COLUMN_GAP) / 2;
    return row.map((node, i) => toNode(node, { x: offset + i * COLUMN_GAP, y: r * ROW_GAP }));
  });
}
