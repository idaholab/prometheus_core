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

import { dedupeElements } from "./elementDeduplication.ts";

type TestElement = {
  id?: string;
  type: string;
  name?: string;
  url?: string;
  props?: Record<string, unknown>;
};

const classifyElement = (element: TestElement) =>
  element.type === "custom" && element.name === "MeshViewer" ? "mesh" : "file";

test("keeps distinct mesh datasets from one response", () => {
  const elements: TestElement[] = [
    {
      id: "stl-viewer",
      type: "custom",
      name: "MeshViewer",
      props: { datasetId: "stl-dataset" },
    },
    {
      id: "exodus-viewer",
      type: "custom",
      name: "MeshViewer",
      props: { datasetId: "exodus-dataset" },
    },
  ];

  assert.deepEqual(dedupeElements(elements, classifyElement), elements);
});

test("collapses duplicate delivery of the same mesh dataset", () => {
  const first: TestElement = {
    id: "step-element",
    type: "custom",
    name: "MeshViewer",
    props: { datasetId: "exodus-dataset" },
  };
  const duplicate: TestElement = {
    id: "global-element",
    type: "custom",
    name: "MeshViewer",
    props: { datasetId: "exodus-dataset" },
  };

  assert.deepEqual(dedupeElements([first, duplicate], classifyElement), [first]);
});

test("keeps distinct artifacts that share a display name", () => {
  const elements: TestElement[] = [
    {
      id: "a1",
      type: "image",
      name: "plot.png",
      url: "/api/artifacts/a1/content",
      props: { artifact_id: "a1" },
    },
    {
      id: "a2",
      type: "image",
      name: "plot.png",
      url: "/api/artifacts/a2/content",
      props: { artifact_id: "a2" },
    },
    { id: "j1", type: "custom", name: "CollapsibleJson", props: { name: "result", artifact_id: "j1" } },
    { id: "j2", type: "custom", name: "CollapsibleJson", props: { name: "result", artifact_id: "j2" } },
  ];

  assert.deepEqual(dedupeElements(elements, classifyElement), elements);
});

test("collapses the same artifact delivered twice", () => {
  const first: TestElement = { id: "x", type: "image", name: "plot.png", props: { artifact_id: "a1" } };
  const again: TestElement = { id: "y", type: "image", name: "renamed.png", props: { artifact_id: "a1" } };

  assert.deepEqual(dedupeElements([first, again], classifyElement), [first]);
});
