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

  assert.deepEqual(
    dedupeElements([first, duplicate], classifyElement),
    [first],
  );
});
