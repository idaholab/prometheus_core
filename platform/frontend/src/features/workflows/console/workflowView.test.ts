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

import assert from "node:assert/strict";
import { describe, test } from "vitest";

import type { GraphEdge, GraphNode, Workflow, WorkflowDetail } from "@/lib/api/types";
import type { AgentNodeData } from "@/features/workflows/graph/WorkflowGraphNodes";
import { formatSpeedup, toPlan, toTemplate } from "./workflowView.ts";

// The seed template's row (platform/backend/CONTRACT.md "## Workflows").
const SEED: Workflow = {
  workflow_id: "comprehensive_material_analysis",
  name: "Comprehensive Material Analysis",
  summary: "Full multi-domain assessment with data retrieval and specialist analysis.",
  category: "Safety",
  version: "1.0.0",
  source: "local",
  owner: "materials-team",
  complexity: null,
  estimated_runtime_seconds: 270,
  speedup: null,
  requires_approval: true,
  agent_count: 5,
  checkpoint_count: 0,
};

function node(node_id: string, label: string, overrides: Partial<GraphNode> = {}): GraphNode {
  return {
    node_id,
    kind: "skill",
    skill_id: node_id,
    label,
    agent_name: `${node_id}-agent`,
    is_final: false,
    inputs: [{ port: "material_id", source: "input.material_id", optional: false }],
    ...overrides,
  };
}

function edge(
  edge_id: string,
  from_node: string,
  to_node: string,
  kind: GraphEdge["kind"],
  port: string | null,
): GraphEdge {
  return { edge_id, from_node, to_node, kind, port };
}

function detail(nodes: GraphNode[], edges: GraphEdge[], overrides: Partial<Workflow> = {}): WorkflowDetail {
  return {
    ...SEED,
    ...overrides,
    inputs: {
      required: ["material_id", "context.temperature_c"],
      optional: ["context.pressure_mpa", "context.neutron_flux_n_cm2_s", "context.operating_hours"],
    },
    graph: { workflow_id: SEED.workflow_id, mode: "dag", nodes, edges },
  };
}

/** The data of the one agent node that `n` alone lays out to. */
function agentData(n: GraphNode): AgentNodeData {
  const [only] = toPlan(detail([n], [])).nodes;
  assert.equal(only.type, "agent");
  return only.data as AgentNodeData;
}

// The seed graph (platform/agents/client-agent/workflows/comprehensive_material_analysis.yaml): five skill nodes,
// three `order` edges from retrieve_material, four `data` edges into synthesize_report.
const SEED_LABELS: Record<string, string> = {
  retrieve_material: "Get Material Data",
  analyze_radiation: "Analyze Radiation Damage",
  analyze_corrosion: "Analyze Corrosion",
  analyze_thermal: "Analyze Thermal Effects",
  synthesize_report: "Synthesize Material Analysis",
};
const SEED_DETAIL = detail(
  Object.entries(SEED_LABELS).map(([id, label]) => node(id, label, { is_final: id === "synthesize_report" })),
  [
    edge("comprehensive_material_analysis-e1", "retrieve_material", "analyze_radiation", "order", null),
    edge("comprehensive_material_analysis-e2", "retrieve_material", "analyze_corrosion", "order", null),
    edge("comprehensive_material_analysis-e3", "retrieve_material", "analyze_thermal", "order", null),
    edge(
      "comprehensive_material_analysis-e4",
      "retrieve_material",
      "synthesize_report",
      "data",
      "tool_results.material_data",
    ),
    edge(
      "comprehensive_material_analysis-e5",
      "analyze_radiation",
      "synthesize_report",
      "data",
      "tool_results.radiation",
    ),
    edge(
      "comprehensive_material_analysis-e6",
      "analyze_corrosion",
      "synthesize_report",
      "data",
      "tool_results.corrosion",
    ),
    edge(
      "comprehensive_material_analysis-e7",
      "analyze_thermal",
      "synthesize_report",
      "data",
      "tool_results.thermal",
    ),
  ],
);

// Requirement: toTemplate() MUST map a Workflow to a WorkflowTemplate card with its
// runtime as "1h 30m" or "4m 30s" and its speed-up as "2.0x", and MUST leave a figure
// the template does not set as null.
describe("workflow_view_formats_templates", () => {
  test("toTemplate gives the runtime without a zero part", () => {
    const runtime = (seconds: number) => toTemplate({ ...SEED, estimated_runtime_seconds: seconds }).runtime;
    assert.equal(runtime(5400), "1h 30m");
    assert.equal(runtime(3600), "1h");
    assert.equal(runtime(270), "4m 30s");
    assert.equal(runtime(2700), "45m");
    assert.equal(runtime(45), "45s");
  });

  test("formatSpeedup keeps one decimal and adds x", () => {
    assert.equal(formatSpeedup(2), "2.0x");
    assert.equal(formatSpeedup(4.2), "4.2x");
  });

  test("toTemplate maps the seed workflow to its card, its unset figures as null", () => {
    assert.deepEqual(toTemplate(SEED), {
      id: "comprehensive_material_analysis",
      name: "Comprehensive Material Analysis",
      complexity: null,
      checkpoints: 0,
      agents: 5,
      runtime: "4m 30s",
      speedup: null,
      requiresApproval: true,
      owner: null,
    });
  });

  test("toTemplate shows a set complexity and speed-up, and a null runtime as null", () => {
    const card = toTemplate({ ...SEED, complexity: "moderate", speedup: 2.0 });
    assert.equal(card.complexity, "moderate");
    assert.equal(card.speedup, "2.0x");
    assert.equal(toTemplate({ ...SEED, estimated_runtime_seconds: null }).runtime, null);
  });

  test("toTemplate names the owner of an agent-card workflow only", () => {
    const owner = (source: Workflow["source"]) =>
      toTemplate({ ...SEED, source, owner: "artifact-debug-agent" }).owner;
    assert.equal(owner("agent_card"), "artifact-debug-agent");
    assert.equal(owner("local"), null);
  });
});

// Requirement: toPlan() MUST turn a WorkflowDetail into a WorkflowPlan with one node per
// graph node in longest-path layers over data and order edges, and one wire per edge keyed
// on its edge_id and carrying its kind.
describe("workflow_plan_from_graph", () => {
  test("the seed graph gives five agent nodes named by their labels, without a status or estimate", () => {
    const plan = toPlan(SEED_DETAIL);
    assert.deepEqual(plan.nodes.map((n) => n.id).sort(), Object.keys(SEED_LABELS).sort());
    for (const n of plan.nodes) {
      assert.equal(n.type, "agent");
      assert.equal(n.data.name, SEED_LABELS[n.id]);
      assert.equal("status" in n.data, false, `${n.id} has no status on a template`);
      assert.equal("est" in n.data, false, `${n.id} has no estimate on a template`);
    }
  });

  test("the seed graph is laid out in longest-path layers over data and order edges", () => {
    const y = new Map(toPlan(SEED_DETAIL).nodes.map((n) => [n.id, n.position.y]));
    const retrieve = y.get("retrieve_material") as number;
    const synthesize = y.get("synthesize_report") as number;
    const analyses = ["analyze_radiation", "analyze_corrosion", "analyze_thermal"].map(
      (id) => y.get(id) as number,
    );
    assert.equal(new Set(analyses).size, 1, "the three analyses share one row");
    assert.ok(retrieve < analyses[0], "retrieve_material sits above the analyses");
    assert.ok(analyses[0] < synthesize, "synthesize_report sits below the analyses");
  });

  test("the seed graph's rows are centred on the widest row, COLUMN_GAP apart", () => {
    const x = new Map(toPlan(SEED_DETAIL).nodes.map((n) => [n.id, n.position.x]));
    assert.equal(x.get("retrieve_material"), 220, "the one-node row sits under the middle analysis");
    assert.deepEqual(
      ["analyze_radiation", "analyze_corrosion", "analyze_thermal"].map((id) => x.get(id)),
      [0, 220, 440],
    );
    assert.equal(x.get("synthesize_report"), 220, "the one-node row sits under the middle analysis");
  });

  test("the seed graph gives one wire per edge, keyed on its edge_id and carrying its kind", () => {
    const plan = toPlan(SEED_DETAIL);
    assert.deepEqual(
      plan.wires.map((w) => w.id),
      [1, 2, 3, 4, 5, 6, 7].map((i) => `comprehensive_material_analysis-e${i}`),
    );
    assert.deepEqual(
      plan.wires.map((w) => w.kind),
      ["order", "order", "order", "data", "data", "data", "data"],
    );
  });

  test("the seed plan carries the template's path, agents, runtime, checkpoints and approval", () => {
    const plan = toPlan(SEED_DETAIL);
    assert.equal(plan.path[plan.path.length - 1], "comprehensive_material_analysis");
    assert.equal(plan.agents, 5);
    assert.equal(plan.pipelineTime, "4m 30s");
    assert.equal(plan.checkpoints, "0");
    assert.equal(plan.requiresApproval, true);
  });

  test("a template without a runtime has no pipeline time", () => {
    const plan = toPlan(
      detail(SEED_DETAIL.graph.nodes, SEED_DETAIL.graph.edges, { estimated_runtime_seconds: null }),
    );
    assert.equal(plan.pipelineTime, null);
  });

  test("a qa_gate and a checkpoint node each become a checkpoint node", () => {
    const plan = toPlan(
      detail(
        [
          node("gate", "QA Gate", { kind: "qa_gate", skill_id: null, agent_name: null }),
          node("hold", "Review", { kind: "checkpoint", skill_id: null, agent_name: null }),
        ],
        [edge("e1", "gate", "hold", "order", null)],
      ),
    );
    assert.deepEqual(
      plan.nodes.map((n) => [n.id, n.type, n.data.name]),
      [
        ["gate", "checkpoint", "QA Gate"],
        ["hold", "checkpoint", "Review"],
      ],
    );
  });

  test("an edge to an unknown node is dropped", () => {
    const plan = toPlan(
      detail(
        [node("a", "A"), node("b", "B")],
        [edge("e1", "a", "b", "order", null), edge("e2", "a", "missing", "order", null)],
      ),
    );
    assert.deepEqual(
      plan.wires.map((w) => w.id),
      ["e1"],
    );
    assert.deepEqual(
      plan.nodes.map((n) => n.id),
      ["a", "b"],
    );
  });

  test("a two-node cycle returns both nodes", () => {
    const plan = toPlan(
      detail(
        [node("a", "A"), node("b", "B")],
        [edge("e1", "a", "b", "order", null), edge("e2", "b", "a", "order", null)],
      ),
    );
    assert.deepEqual(plan.nodes.map((n) => n.id).sort(), ["a", "b"]);
    assert.equal(plan.wires.length, 2);
  });

  test("a checkpoint's centre lines up with the agent node in its column", () => {
    // Columns are laid out for a 200 px agent node; the checkpoint diamond is 42 px.
    const plan = toPlan(
      detail(
        [node("a", "A"), node("hold", "Review", { kind: "checkpoint", skill_id: null, agent_name: null })],
        [edge("e1", "a", "hold", "order", null)],
      ),
    );
    const [agent, checkpoint] = plan.nodes;
    assert.equal(agent.type, "agent");
    assert.equal(checkpoint.type, "checkpoint");
    assert.equal(checkpoint.position.x + 42 / 2, agent.position.x + 200 / 2);
  });

  test("a repeated node_id or edge_id keeps only the first", () => {
    const plan = toPlan(
      detail(
        [node("a", "First A"), node("b", "B"), node("a", "Second A")],
        [edge("e1", "a", "b", "order", null), edge("e1", "b", "a", "order", null)],
      ),
    );
    assert.deepEqual(
      plan.nodes.map((n) => [n.id, n.data.name]),
      [
        ["a", "First A"],
        ["b", "B"],
      ],
    );
    assert.deepEqual(plan.wires, [{ id: "e1", from: "a", to: "b", kind: "order" }]);
  });

  test("an agent node's input counts its required sourced inputs, not literals", () => {
    const two = agentData(
      node("a", "A", {
        inputs: [
          { port: "material_id", source: "input.material_id", optional: false },
          { port: "context", source: "input.context", optional: false },
          { port: "notes", source: null, optional: false },
        ],
      }),
    );
    assert.equal(two.input, "2 inputs");
    const none = agentData(node("a", "A", { inputs: [{ port: "notes", source: null, optional: false }] }));
    assert.equal(none.input, "\u2014");
  });

  test("an agent node's output is result", () => {
    assert.equal(agentData(node("a", "A")).output, "result");
  });
});
