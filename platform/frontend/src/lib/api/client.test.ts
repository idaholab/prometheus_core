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

import { api } from "./client.ts";

test("artifactContentUrl uses the backend's conversation content_url as given", () => {
  const content_url = "/api/conversations/c1/artifacts/a1/content";

  assert.equal(api.artifactContentUrl({ artifact_id: "a1", content_url }), content_url);
});

test("artifactContentUrl falls back to the session route when content_url is empty or absent", () => {
  // The backend sends "" when it knows no conversation; fixtures and samples omit it.
  for (const artifact of [{ artifact_id: "a1", content_url: "" }, { artifact_id: "a1" }]) {
    assert.equal(api.artifactContentUrl(artifact), "/api/artifacts/a1/content");
  }
});

test("artifactContentUrl quotes the artifact id in the fallback", () => {
  assert.equal(api.artifactContentUrl({ artifact_id: "a b/c?d" }), "/api/artifacts/a%20b%2Fc%3Fd/content");
});
