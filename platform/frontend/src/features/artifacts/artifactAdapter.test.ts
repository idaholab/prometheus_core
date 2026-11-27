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

import type { ArtifactMeta } from "@/lib/api/types";
import { artifactToElement } from "./artifactAdapter.ts";

function jsonArtifact(overrides: Partial<ArtifactMeta>): ArtifactMeta {
  return {
    artifact_id: "art-1",
    name: "result.json",
    mime_type: "application/json",
    description: "",
    tags: [],
    json_body: null,
    render_hint: "json",
    ...overrides,
  };
}

test("json artifact without an inline body points CollapsibleJson at the content URL", () => {
  const element = artifactToElement(jsonArtifact({ artifact_id: "a b", json_body: null }));

  assert.equal(element.name, "CollapsibleJson");
  assert.equal(element.props?.url, "/api/artifacts/a%20b/content");
  assert.equal(element.props?.data, null);
});

test("json artifact with an inline body keeps it as CollapsibleJson data", () => {
  const body = { status: "ok", values: [1, 2, 3], nested: { flag: true } };
  const element = artifactToElement(jsonArtifact({ json_body: body }));

  assert.equal(element.name, "CollapsibleJson");
  assert.deepEqual(element.props?.data, { status: "ok", values: [1, 2, 3], nested: { flag: true } });
  assert.equal(element.props?.url, "/api/artifacts/art-1/content");
});

test("an artifact's content_url wins over the session-scoped route", () => {
  const element = artifactToElement(
    jsonArtifact({ json_body: null, content_url: "/api/conversations/c1/artifacts/art-1/content" }),
  );

  assert.equal(element.props?.url, "/api/conversations/c1/artifacts/art-1/content");
});

test("a mesh with a mesh_url but no inline manifest mounts the viewer to fetch it", () => {
  const element = artifactToElement(
    jsonArtifact({
      render_hint: "mesh",
      name: "out.e",
      content_url: "/api/conversations/c1/artifacts/m1/content",
      mesh_url: "/api/conversations/c1/artifacts/m1/mesh",
    }),
  );

  assert.equal(element.name, "MeshViewer");
  assert.equal(element.props?.meshUrl, "/api/conversations/c1/artifacts/m1/mesh");
  assert.equal(element.props?.downloadUrl, "/api/conversations/c1/artifacts/m1/content");
});

test("a mesh with neither manifest nor mesh_url stays a download", () => {
  const element = artifactToElement(jsonArtifact({ render_hint: "mesh", name: "out.e" }));

  assert.equal(element.type, "file");
});

test("an inline mesh body mounts the viewer only when it can render", () => {
  const files = [{ index: 0, timestep_index: 0, time_value: 0, filename: "surface_t0000.vtp" }];
  const complete = artifactToElement(
    jsonArtifact({
      render_hint: "mesh",
      json_body: { baseUrl: "/api/artifacts/mesh/d", manifest: { files } },
    }),
  );
  assert.equal(complete.name, "MeshViewer");
  assert.equal(complete.props?.baseUrl, "/api/artifacts/mesh/d");

  // A partial body (no baseUrl or no files) would mount an empty viewer: fetch instead.
  const mesh_url = "/api/conversations/c1/artifacts/m1/mesh";
  for (const json_body of [{ datasetId: "d" }, { baseUrl: "/b", manifest: { files: [] } }]) {
    const element = artifactToElement(jsonArtifact({ render_hint: "mesh", json_body, mesh_url }));
    assert.equal(element.props?.meshUrl, mesh_url, JSON.stringify(json_body));
  }
});
