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

test("keeps distinct mesh artifacts from one response", () => {
  const elements: TestElement[] = [
    {
      id: "stl-viewer",
      type: "custom",
      name: "MeshViewer",
      props: { datasetId: "stl-dataset", artifact_id: "stl" },
    },
    {
      id: "exodus-viewer",
      type: "custom",
      name: "MeshViewer",
      props: { datasetId: "exodus-dataset", artifact_id: "exodus" },
    },
  ];

  assert.deepEqual(dedupeElements(elements), elements);
});

test("collapses duplicate delivery of the same mesh artifact", () => {
  const first: TestElement = {
    id: "step-element",
    type: "custom",
    name: "MeshViewer",
    props: { datasetId: "exodus-dataset", artifact_id: "exodus" },
  };
  const duplicate: TestElement = {
    id: "global-element",
    type: "custom",
    name: "MeshViewer",
    props: { datasetId: "exodus-dataset", artifact_id: "exodus" },
  };

  assert.deepEqual(dedupeElements([first, duplicate]), [first]);
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

  assert.deepEqual(dedupeElements(elements), elements);
});

test("collapses the same artifact delivered twice", () => {
  const first: TestElement = { id: "x", type: "image", name: "plot.png", props: { artifact_id: "a1" } };
  const again: TestElement = { id: "y", type: "image", name: "renamed.png", props: { artifact_id: "a1" } };

  assert.deepEqual(dedupeElements([first, again]), [first]);
});

test("never keys on the display name, even without an artifact id", () => {
  const elements: TestElement[] = [
    { id: "e1", type: "image", name: "plot.png", url: "/api/artifacts/a1/content" },
    { id: "e2", type: "image", name: "plot.png", url: "/api/artifacts/a2/content" },
    { id: "e3", type: "custom", name: "CollapsibleJson", props: { name: "result" } },
    { id: "e4", type: "custom", name: "CollapsibleJson", props: { name: "result" } },
  ];

  assert.deepEqual(dedupeElements(elements), elements);
});

test("falls back to the artifact URL when there is no artifact id", () => {
  const first: TestElement = { id: "e1", type: "image", name: "a.png", url: "/api/artifacts/a1/content" };
  const again: TestElement = { id: "e2", type: "image", name: "b.png", url: "/api/artifacts/a1/content" };

  assert.deepEqual(dedupeElements([first, again]), [first]);
});

test("compares artifact ids exactly, without case folding", () => {
  const elements: TestElement[] = [
    { id: "x", type: "image", props: { artifact_id: "Art-1" } },
    { id: "y", type: "image", props: { artifact_id: "art-1" } },
  ];

  assert.deepEqual(dedupeElements(elements), elements);
});

test("keeps a file card and an image preview of two different artifacts", () => {
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
      type: "file",
      name: "plot.png",
      url: "/api/artifacts/a2/content",
      props: { artifact_id: "a2" },
    },
  ];

  assert.deepEqual(dedupeElements(elements), elements);
});

test("collapses a custom element delivered twice under one artifact id", () => {
  const first: TestElement = {
    id: "x",
    type: "custom",
    name: "CollapsibleJson",
    props: { name: "result", artifact_id: "j1" },
  };
  const again: TestElement = {
    id: "y",
    type: "custom",
    name: "CollapsibleJson",
    props: { name: "other", artifact_id: "j1" },
  };

  assert.deepEqual(dedupeElements([first, again]), [first]);
});

test("keeps two mesh artifacts that share a dataset id", () => {
  const elements: TestElement[] = [
    { id: "m1", type: "custom", name: "MeshViewer", props: { datasetId: "d", artifact_id: "m1" } },
    { id: "m2", type: "custom", name: "MeshViewer", props: { datasetId: "d", artifact_id: "m2" } },
  ];

  assert.deepEqual(dedupeElements(elements), elements);
});
