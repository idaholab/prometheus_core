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
