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

import {
  formatLatency,
  formatRunTime,
  formatUptime,
  formatVersion,
} from "./format.ts";

test("run time uses seconds, minutes and hours and drops a zero lower unit", () => {
  assert.equal(formatRunTime(45), "45s");
  assert.equal(formatRunTime(320), "5m 20s");
  assert.equal(formatRunTime(4500), "1h 15m");
  assert.equal(formatRunTime(1120), "18m 40s");
  assert.equal(formatRunTime(720), "12m");
  assert.equal(formatRunTime(90), "1m 30s");
  assert.equal(formatRunTime(2), "2s");
  assert.equal(formatRunTime(3600), "1h");
});

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
