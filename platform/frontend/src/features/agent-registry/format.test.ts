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

import { formatLatency, formatUptime, formatVersion } from "./format.ts";

test("uptime is a percentage that keeps its decimals", () => {
  assert.equal(formatUptime(100), "100%");
  assert.equal(formatUptime(99.8), "99.8%");
});

test("latency is in milliseconds", () => {
  assert.equal(formatLatency(42), "42ms");
});

test("version carries a V prefix", () => {
  assert.equal(formatVersion("1.4"), "V1.4");
});
