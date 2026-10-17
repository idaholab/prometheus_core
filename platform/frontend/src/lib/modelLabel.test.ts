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
import test from "node:test";

import type { ConfigResponse } from "./api/types.ts";
import { modelLabel } from "./modelLabel.ts";

const baseConfig: ConfigResponse = {
  profiles: [],
  chat_intro: "",
  chat_suggestion_title: "",
  workflow_suggestions: [],
  auto_approve_steps: false,
  max_upload_bytes: 0,
};

test("a non-blank model name gives the Model label", () => {
  assert.equal(modelLabel({ ...baseConfig, llm_model: "gpt-4o" }), "Model: gpt-4o");
  assert.equal(modelLabel({ ...baseConfig, llm_model: "  gpt-4o  " }), "Model: gpt-4o");
});

test("a null, missing or blank model name gives no label", () => {
  assert.equal(modelLabel({ ...baseConfig, llm_model: null }), null);
  assert.equal(modelLabel(baseConfig), null);
  assert.equal(modelLabel({ ...baseConfig, llm_model: "" }), null);
  assert.equal(modelLabel({ ...baseConfig, llm_model: "   " }), null);
});

test("a null config gives no label", () => {
  assert.equal(modelLabel(null), null);
});
