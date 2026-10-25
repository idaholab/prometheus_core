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

import { isPerSampleArtifact } from "./perSample.ts";

test("per-sample configs, ZDOs and failure logs are grouped, results are not", () => {
  assert.equal(isPerSampleArtifact({ tags: ["uq-sample", "uq-config"] }), true);
  assert.equal(isPerSampleArtifact({ tags: ["zdo", "multiphysics"] }), true);
  assert.equal(isPerSampleArtifact({ tags: ["failure", "diagnostics", "multiphysics"] }), true);
  assert.equal(isPerSampleArtifact({ tags: ["uq", "notebook"] }), false);
  assert.equal(isPerSampleArtifact({ tags: [] }), false);
});
