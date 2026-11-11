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
import { test, vi } from "vitest";
import { useAgents } from "./agents.ts";

/* The real agents store, with React stubbed out so that
 * useSyncExternalStore(sub, get) returns get(). */
vi.mock("react", () => ({ useSyncExternalStore: (_sub: unknown, get: () => unknown) => get() }));

const ICONS = ["box", "grid", "activity", "wind", "thermometer", "shield", "database", "file-text"];

test("useAgents serves the eight placeholder agents with every card field", () => {
  const state = useAgents();
  assert.equal(state.status, "ready");
  assert.equal(state.agents.length, 8);
  assert.equal(new Set(state.agents.map((a) => a.id)).size, 8);
  for (const a of state.agents) {
    assert.ok(a.name.length > 0, `${a.id}: name`);
    assert.ok(a.description.length > 0, `${a.id}: description`);
    assert.ok(a.version.length > 0, `${a.id}: version`);
    assert.ok(Number.isFinite(a.avgRunSeconds), `${a.id}: avgRunSeconds`);
    assert.ok(Number.isFinite(a.uptimePercent), `${a.id}: uptimePercent`);
    assert.ok(Number.isFinite(a.latencyMs), `${a.id}: latencyMs`);
    assert.ok(ICONS.includes(a.icon), `${a.id}: icon ${a.icon}`);
  }
  const offline = state.agents.filter((a) => a.status === "offline");
  assert.deepEqual(
    offline.map((a) => a.name),
    ["Dose Rate Calculator"],
  );
});

test("useAgents returns the same snapshot object on every call", () => {
  assert.equal(useAgents(), useAgents());
});
