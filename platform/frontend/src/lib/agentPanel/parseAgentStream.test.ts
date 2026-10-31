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
import { test } from "vitest";

import { parseAgentStream } from "./parseAgentStream.ts";
import { RUNNER, agentDef } from "./roster.ts";

/**
 * Verbatim status streams captured from the tool-calling loop (orchestrator/agent_loop.py,
 * skills.py). The panel keys off these exact strings, so the fixtures are real runs, not
 * paraphrases: a forward-UQ run that drives three HPC pipelines, and the same request
 * when the UQ agent's port is down.
 */
const UQ_RUN = [
  "Received request.",
  "Deciding the next step.",
  "Next step: 'forward_sampling_uq'.",
  "Invoking 'forward_sampling_uq'.",
  "[forward_sampling_uq] Processing your request to initialize sampling and UQ agent for model 'demo_core_neutronics'",
  "[forward_sampling_uq] Pipeline 1002: created",
  "[forward_sampling_uq] Pipeline 1003: created",
  "[forward_sampling_uq] Pipeline 1001: created",
  "[forward_sampling_uq] Pipeline 1001: running",
  "[forward_sampling_uq] Pipeline 1002: running",
  "[forward_sampling_uq] Pipeline 1003: running",
  "[forward_sampling_uq] Pipeline 1001: success",
  "[forward_sampling_uq] Running okflow neutronics: 1/3 cases complete (3 max concurrent)",
  "[forward_sampling_uq] Pipeline 1002: success",
  "[forward_sampling_uq] Running okflow neutronics: 2/3 cases complete (3 max concurrent)",
  "[forward_sampling_uq] Pipeline 1003: success",
  "[forward_sampling_uq] Running okflow neutronics: 3/3 cases complete (3 max concurrent)",
  "[forward_sampling_uq] okflow neutronics UQ complete for 'demo_core_neutronics'.",
  "'forward_sampling_uq' completed.",
  "Deciding the next step.",
  "Response ready.",
];

const UQ_DOWN = [
  "Processing orchestration request.",
  "Received request.",
  "Deciding the next step.",
  "Next step: 'forward_sampling_uq'.",
  "Invoking 'forward_sampling_uq'.",
  "'forward_sampling_uq' failed: Network communication error: All connection attempts failed (host.docker.internal:8042)",
  "Deciding the next step.",
  "Response ready.",
];

const upto = (stream: string[], n: number) => stream.slice(0, n);

test("empty history reveals nothing", () => {
  const s = parseAgentStream([]);
  assert.deepEqual(s.revealed, []);
  assert.equal(s.active, null);
  assert.equal(s.complete, false);
});

test("the first line puts only the planner on stage, working", () => {
  const s = parseAgentStream(upto(UQ_RUN, 2));
  assert.deepEqual(s.revealed, ["planner"]);
  assert.equal(s.active, "planner");
  assert.equal(s.edge, null);
});

test("'Next step' reveals the named skill as an agent, with no hardcoded roster", () => {
  const s = parseAgentStream(upto(UQ_RUN, 3));
  assert.deepEqual(s.revealed, ["planner", "forward_sampling_uq"]);
  assert.equal(s.active, "planner");
  assert.deepEqual(s.edge, { from: "planner", to: "forward_sampling_uq", dir: "down", label: "A2A" });
});

test("any skill name works, not just the demo cast", () => {
  const s = parseAgentStream(["Received request.", "Invoking 'search_literature'."]);
  assert.deepEqual(s.revealed, ["planner", "search_literature"]);
  assert.equal(s.active, "search_literature");
  assert.equal(s.status.search_literature.outcome, "working");
});

test("pipeline lines reveal the okflow runner and collapse into one loop badge", () => {
  const s = parseAgentStream(upto(UQ_RUN, 11));
  assert.deepEqual(s.revealed, ["planner", "forward_sampling_uq", "okflow_runner"]);
  assert.equal(s.active, "okflow_runner");
  assert.equal(s.loops.okflow_runner.n, 3);
  assert.equal(s.loops.okflow_runner.done, false);
  assert.deepEqual(
    s.pipelines.map((p) => p.id).sort(),
    ["1001", "1002", "1003"],
  );
});

test("the loop badge counts finished cases from the progress line", () => {
  const s = parseAgentStream(upto(UQ_RUN, 15));
  assert.equal(s.loops.okflow_runner.completed, 2);
  assert.equal(s.loops.okflow_runner.n, 3);
  assert.equal(s.loops.okflow_runner.done, false);
});

test("all cases complete: runner done, results flow back to the UQ agent", () => {
  const s = parseAgentStream(upto(UQ_RUN, 17));
  assert.equal(s.loops.okflow_runner.done, true);
  assert.equal(s.status.okflow_runner.outcome, "done");
  assert.deepEqual(s.edge, { from: "okflow_runner", to: "forward_sampling_uq", dir: "up", label: "results" });
});

test("skill completed: report docks at the skill, status done", () => {
  const s = parseAgentStream(upto(UQ_RUN, 19));
  assert.equal(s.status.forward_sampling_uq.outcome, "done");
  assert.deepEqual(
    s.files.map((f) => [f.id, f.at, f.click]),
    [["report:forward_sampling_uq", "forward_sampling_uq", true]],
  );
});

test("'Response ready.' ends the turn: nothing active, every agent stays revealed", () => {
  const s = parseAgentStream(UQ_RUN);
  assert.equal(s.complete, true);
  assert.equal(s.active, null);
  assert.equal(s.edge, null);
  assert.deepEqual(s.revealed, ["planner", "forward_sampling_uq", "okflow_runner"]);
});

test("an unreachable agent is marked failed + unreachable, with the error kept", () => {
  const s = parseAgentStream(UQ_DOWN);
  const uq = s.status.forward_sampling_uq;
  assert.equal(uq.outcome, "failed");
  assert.equal(uq.unreachable, true);
  assert.match(uq.error ?? "", /8042/);
  assert.equal(s.files.length, 0, "no report docks for a failed call");
  assert.equal(s.complete, true);
});

test("a task error (not connectivity) is failed but not unreachable", () => {
  const s = parseAgentStream([
    "Invoking 'forward_sampling_uq'.",
    "'forward_sampling_uq' failed: Unknown design_variant 'no_such_core'",
  ]);
  assert.equal(s.status.forward_sampling_uq.outcome, "failed");
  assert.equal(s.status.forward_sampling_uq.unreachable, false);
});

test("an unavailable capability is unreachable", () => {
  const s = parseAgentStream(["Invoking 'forward_sampling_uq'.", "Capability 'forward_sampling_uq' is currently unavailable."]);
  assert.equal(s.status.forward_sampling_uq.outcome, "failed");
  assert.equal(s.status.forward_sampling_uq.unreachable, true);
});

test("a failed pipeline marks the runner failed", () => {
  const s = parseAgentStream([
    "Invoking 'forward_sampling_uq'.",
    "[forward_sampling_uq] Pipeline 1: running",
    "[forward_sampling_uq] Pipeline 1: failed",
  ]);
  assert.equal(s.status.okflow_runner.outcome, "failed");
});

test("a second skill in the same turn re-lights the panel after the first completed", () => {
  const s = parseAgentStream([
    ...upto(UQ_RUN, 19),
    "Deciding the next step.",
    "Next step: 'synthesize_material_analysis'.",
    "Invoking 'synthesize_material_analysis'.",
  ]);
  assert.equal(s.active, "synthesize_material_analysis");
  assert.equal(s.status.forward_sampling_uq.outcome, "done");
  assert.equal(s.complete, false);
});

test("a peer agent a specialist calls joins the stage, with no roster change", () => {
  const s = parseAgentStream([
    "Invoking 'forward_sampling_uq'.",
    "[forward_sampling_uq] Requesting baseline pipeline config from okflow-config-agent (base_branch='x')...",
  ]);
  assert.ok(s.revealed.includes("okflow-config-agent"));
  assert.equal(s.active, "okflow-config-agent");
  assert.deepEqual(s.edge, { from: "forward_sampling_uq", to: "okflow-config-agent", dir: "down", label: "A2A" });
  assert.equal(s.status["okflow-config-agent"].outcome, "working");
});

test("the peer is done once the specialist moves on, and failures are kept", () => {
  const done = parseAgentStream([
    "Invoking 'forward_sampling_uq'.",
    "[forward_sampling_uq] Requesting baseline pipeline config from okflow-config-agent ...",
    "[forward_sampling_uq] Running okflow neutronics (4 cases)",
  ]);
  assert.equal(done.status["okflow-config-agent"].outcome, "done");

  const failed = parseAgentStream([
    "Invoking 'forward_sampling_uq'.",
    "[forward_sampling_uq] could not reach brand-new-agent for skill 'x' at http://...: 404",
  ]);
  assert.ok(failed.revealed.includes("brand-new-agent"));
  assert.equal(failed.status["brand-new-agent"].outcome, "failed");
});

test("the okflow runner named in a line keeps its pipeline-runner identity", () => {
  const s = parseAgentStream([
    "Invoking 'forward_sampling_uq'.",
    "[forward_sampling_uq] could not reach okflow runner 'okflow-runner-agent' for skill 'start_pipeline'",
  ]);
  assert.ok(s.revealed.includes(RUNNER));
  assert.ok(!s.revealed.includes("okflow-runner-agent"));
});

test("an unknown agent gets a readable name and a stable color of its own", () => {
  const a = agentDef("okflow-config-agent");
  assert.equal(a.name, "okflow config");
  assert.equal(a.color, agentDef("okflow-config-agent").color);
  assert.notEqual(a.color, agentDef("rom-builder-agent").color);
});

test("a backgrounded turn's 'waiting on <skill> — msg' lines keep the specialist, peers and runner", () => {
  const s = parseAgentStream([
    "Next step: 'forward_sampling_uq'.",
    "waiting on forward_sampling_uq — Requesting baseline pipeline config from okflow-config-agent...",
    "waiting on forward_sampling_uq — Sample 3: Pipeline 7 started: https://gl.example/g/p/-/pipelines/7",
    "waiting on forward_sampling_uq — Pipelines (2/2): 1 running, 1 success",
  ]);
  assert.ok(s.revealed.includes("forward_sampling_uq"));
  assert.ok(s.revealed.includes("okflow-config-agent"));
  assert.ok(s.revealed.includes(RUNNER));
  assert.equal(s.loops[RUNNER].n, 2);
  assert.equal(s.loops[RUNNER].completed, 1);
});

test("the pipeline tally completes the runner loop when every pipeline is finished", () => {
  const s = parseAgentStream([
    "[forward_sampling_uq] Pipelines (3/3): 2 success, 1 failed",
  ]);
  assert.equal(s.loops[RUNNER].done, true);
  assert.equal(s.status[RUNNER].outcome, "done");
});

test("a peer that hands its result back is done, and results flow up to the caller", () => {
  const s = parseAgentStream([
    "Invoking 'forward_sampling_uq'.",
    "[forward_sampling_uq] Requesting baseline pipeline config from okflow-config-agent ...",
    "[forward_sampling_uq] okflow-config-agent returned the baseline config.",
  ]);
  assert.equal(s.status["okflow-config-agent"].outcome, "done");
  assert.equal(s.active, "forward_sampling_uq");
  assert.deepEqual(s.edge, { from: "okflow-config-agent", to: "forward_sampling_uq", dir: "up", label: "result" });
});

test("a progress line with no prior dispatch line still draws the planner edge", () => {
  const s = parseAgentStream(["[search_literature] Searching OSTI for 'bank worth'"]);
  assert.deepEqual(s.revealed, ["planner", "search_literature"]);
  assert.equal(s.active, "search_literature");
  assert.deepEqual(s.edge, { from: "planner", to: "search_literature", dir: "down", label: "A2A" });
});

test("a skill's progress after another skill's result re-points the edge at it", () => {
  const s = parseAgentStream([
    "Invoking 'search_literature'.",
    "'search_literature' completed.",
    "[forward_sampling_uq] Processing your request",
  ]);
  assert.equal(s.active, "forward_sampling_uq");
  assert.deepEqual(s.edge, { from: "planner", to: "forward_sampling_uq", dir: "down", label: "A2A" });
});

test("a backgrounded 'waiting on <skill>' line with no message keeps that skill working", () => {
  const s = parseAgentStream(["Next step: 'forward_sampling_uq'.", "waiting on forward_sampling_uq"]);
  assert.equal(s.active, "forward_sampling_uq");
  assert.equal(s.status.forward_sampling_uq.outcome, "working");
});

test("a skill that completes twice docks one report, and a skill with no runner leaves no loop", () => {
  const s = parseAgentStream([
    "Invoking 'search_literature'.",
    "'search_literature' completed.",
    "Invoking 'search_literature'.",
    "'search_literature' completed.",
  ]);
  assert.deepEqual(s.files, [{ id: "report:search_literature", at: "search_literature", label: "report", click: true }]);
  assert.deepEqual(s.loops, {});
  assert.equal(s.status.search_literature.outcome, "done");
});

test("completing after a failed pipeline keeps the runner failed", () => {
  const s = parseAgentStream([
    "Invoking 'forward_sampling_uq'.",
    "[forward_sampling_uq] Pipelines (2/2): 1 success, 1 failed",
    "[forward_sampling_uq] Pipeline 9: failed",
    "'forward_sampling_uq' completed.",
  ]);
  assert.equal(s.loops[RUNNER].done, true);
  assert.equal(s.status[RUNNER].outcome, "failed");
});

test("the okflow case total reveals the runner before any case finishes", () => {
  const s = parseAgentStream(["Invoking 'forward_sampling_uq'.", "[forward_sampling_uq] Running okflow neutronics (4 cases)"]);
  assert.equal(s.loops[RUNNER].n, 4);
  assert.equal(s.loops[RUNNER].completed, 0);
  assert.equal(s.active, RUNNER);
});

test("a stray line after the turn completed does not light the planner again", () => {
  const s = parseAgentStream([...UQ_DOWN, "Deciding the next step."]);
  assert.equal(s.complete, true);
  assert.equal(s.active, null);
});

test("a skill id that is not an '-agent' name is shown as-is", () => {
  assert.equal(agentDef("search_literature").name, "search_literature");
  assert.equal(agentDef("search_literature").role, "search_literature");
});
