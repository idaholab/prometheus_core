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
