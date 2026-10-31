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

import type { TaskNode } from "../api/types.ts";
import { extractLinks, historyFor, recordStatusHistory, resetHistories, toJobRows } from "./activeJobs.ts";

function node(over: Partial<TaskNode> & { task_id: string }): TaskNode {
  return {
    parent_task_id: null,
    agent: null,
    skill: null,
    title: "",
    state: "working",
    own_state: "working",
    is_background: false,
    waiting_on: [],
    created_at: null,
    started_at: null,
    updated_at: null,
    finished_at: null,
    last_status_message: null,
    progress: null,
    result_ref: null,
    error: null,
    children: [],
    ...over,
  };
}

test("extractLinks keeps only GitLab pipeline URLs, labelled and deduped", () => {
  const links = extractLinks(
    "Pipeline 4242 started: https://gitlab.example/group/project/-/pipelines/4242. " +
      "again https://gitlab.example/group/project/-/pipelines/4242 and https://docs.example/x",
  );
  assert.deepEqual(links, [
    {
      label: "GitLab pipeline 4242",
      url: "https://gitlab.example/group/project/-/pipelines/4242",
      pipelineId: "4242",
    },
  ]);
  assert.deepEqual(extractLinks(null), []);
});

test("extractLinks ignores URLs that only look like pipelines", () => {
  assert.deepEqual(
    extractLinks(
      [
        "https://evil.example/login?next=/-/pipelines/1",
        "https://evil.example/x#/-/pipelines/2",
        "https://evil.example/-/pipelines/3", // no project path
        "https://gl.example/g/p/-/pipelines/4/jobs",
        "javascript:alert(1)//-/pipelines/5",
      ].join(" "),
    ),
    [],
  );
  assert.deepEqual(
    extractLinks("see http://gl.example/g/sub/p/-/pipelines/6/").map((l) => l.pipelineId),
    ["6"],
  );
});

test("historyFor keeps one history per conversation across calls", () => {
  resetHistories();
  const a = historyFor("conv-a");
  a.set("t", ["Pipeline 1 started"]);
  assert.equal(historyFor("conv-a"), a);
  assert.notEqual(historyFor("conv-b"), a);
  assert.deepEqual(historyFor("conv-a").get("t"), ["Pipeline 1 started"]);
});

test("historyFor drops the least recently used conversation past the cap", () => {
  resetHistories();
  const first = historyFor("conv-0");
  first.set("t", ["x"]);
  for (let i = 1; i < 20; i++) historyFor(`conv-${i}`);
  historyFor("conv-0"); // touch: now most recently used
  historyFor("conv-20"); // evicts conv-1, not conv-0
  assert.equal(historyFor("conv-0"), first);
  assert.equal(historyFor("conv-1").size, 0);
});

test("toJobRows lists dispatches under their turn and keeps early links", () => {
  const tree = [
    node({
      task_id: "root",
      title: "Run UQ on the power history",
      children: [
        node({
          task_id: "uq",
          parent_task_id: "root",
          skill: "forward_sampling_uq",
          last_status_message: "Running okflow neutronics: 1/4 cases complete",
        }),
      ],
    }),
    node({ task_id: "done", title: "Earlier question", state: "completed" }),
  ];
  const history = new Map([["uq", ["Pipeline 7 started: https://gl.example/g/p/-/pipelines/7"]]]);
  const rows = toJobRows(tree, history);

  assert.equal(rows.length, 2);
  assert.equal(rows[0].name, "forward_sampling_uq");
  assert.equal(rows[0].turnTitle, "Run UQ on the power history");
  assert.equal(rows[0].running, true);
  assert.deepEqual(rows[0].links.map((l) => l.label), ["GitLab pipeline 7"]);
  // A root with no dispatches is still shown, as itself.
  assert.equal(rows[1].name, "Earlier question");
  assert.equal(rows[1].running, false);
});

test("recordStatusHistory appends only new messages", () => {
  const history = new Map<string, string[]>();
  const tree = [node({ task_id: "t", last_status_message: "a" })];
  recordStatusHistory(tree, history);
  recordStatusHistory(tree, history);
  tree[0].last_status_message = "b";
  recordStatusHistory(tree, history);
  assert.deepEqual(history.get("t"), ["a", "b"]);
});

test("toJobRows tags pipeline links with their state, failed first", () => {
  const tree = [node({ task_id: "uq", title: "UQ", last_status_message: "Pipeline 8: failed" })];
  const history = new Map([
    [
      "uq",
      [
        "Pipeline 7 started: https://gl.example/g/p/-/pipelines/7",
        "Pipeline 8 started: https://gl.example/g/p/-/pipelines/8",
        "Pipeline 7: success",
      ],
    ],
  ]);
  const [row] = toJobRows(tree, history);
  assert.deepEqual(
    row.links.map((l) => [l.pipelineId, l.state]),
    [
      ["8", "failed"],
      ["7", "success"],
    ],
  );
});

test("a childless turn with no skill or title is listed as 'task', and silent tasks add no history", () => {
  const tree = [node({ task_id: "root", state: "submitted" })];
  const history = recordStatusHistory(tree, new Map());
  assert.equal(history.size, 0);
  const [row] = toJobRows(tree, history);
  assert.equal(row.name, "task");
  assert.equal(row.running, true);
  assert.equal(row.message, "");
  assert.deepEqual(row.links, []);
});
