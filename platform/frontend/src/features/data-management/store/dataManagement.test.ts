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
import { ALL, filterList } from "@/lib/listFilter";
import {
  useDataManagement,
  derive,
  storagePercent,
  formatBytes,
  toggleSource,
  ARTIFACT_FILTER,
} from "./dataManagement.ts";

/* The real Data Management store, with React stubbed out as in chat.test.ts.
 * Outside a render the real useSyncExternalStore has no dispatcher, so the stub
 * returns the store's snapshot directly. It also leaves the store's subscribe
 * on globalThis.__dataManagementSubscribe. */
vi.mock("react", () => ({
  useSyncExternalStore: (sub: unknown, get: () => unknown) => {
    (globalThis as Record<string, unknown>).__dataManagementSubscribe = sub;
    return get();
  },
}));

const g = globalThis as unknown as { __dataManagementSubscribe: (cb: () => void) => () => void };

test("useDataManagement returns ready state with six sources and six artifacts", () => {
  const state = useDataManagement(); // not a render: the stubbed hook returns the snapshot
  assert.equal(state.status, "ready");
  assert.equal(state.sources.length, 6);
  const disabled = state.sources.filter((s) => !s.enabled);
  assert.deepEqual(
    disabled.map((s) => s.name),
    ["Reactor Operating Logs"],
  );
  assert.equal(state.artifacts.length, 6);
  for (const a of state.artifacts) {
    assert.ok(a.name.length > 0, `artifact ${a.id} has an empty name`);
    assert.ok(["report", "mesh", "result"].includes(a.type), `artifact ${a.id} has type ${a.type}`);
  }
});

test("derive returns empty for no sources and no artifacts, else ready", () => {
  const { sources } = useDataManagement();
  assert.equal(derive([], []), "empty");
  assert.equal(derive(sources.slice(0, 1), []), "ready");
});

test("storagePercent rounds used over total to a whole percentage", () => {
  assert.equal(storagePercent({ used_bytes: 1.8e12, total_bytes: 5e12 }), 36);
  assert.equal(storagePercent({ used_bytes: 1, total_bytes: 3 }), 33);
});

test("formatBytes steps to the decimal unit with at most one decimal", () => {
  assert.equal(formatBytes(1.8e12), "1.8 TB");
  assert.equal(formatBytes(890e9), "890 GB");
  assert.equal(formatBytes(84e3), "84 KB");
});

// Test plan: data_management_toggle_flips_one_source.
test("toggleSource flips one source in a new snapshot and notifies; an unknown id changes nothing", () => {
  const id = "reactor-operating-logs";
  const before = useDataManagement(); // not a render: the stub also captures the store's subscribe
  const listener = vi.fn();
  const unsubscribe = g.__dataManagementSubscribe(listener);
  try {
    toggleSource(id);
    const after = useDataManagement();
    assert.notEqual(after, before, "toggleSource must build a new snapshot object");
    assert.equal(after.sources.find((s) => s.id === id)?.enabled, true);
    const others = before.sources.filter((s) => s.id !== id);
    assert.equal(others.length, 5);
    for (const s of others) {
      assert.equal(after.sources.find((a) => a.id === s.id), s, `source ${s.id} must keep its object`);
    }
    assert.equal(listener.mock.calls.length, 1);

    toggleSource(id);
    const restored = useDataManagement();
    assert.equal(restored.sources.find((s) => s.id === id)?.enabled, false);
    assert.equal(listener.mock.calls.length, 2);

    toggleSource("nope");
    assert.equal(useDataManagement(), restored, "an unknown id must keep the same snapshot");
    assert.equal(listener.mock.calls.length, 2, "an unknown id must notify no subscriber");
  } finally {
    unsubscribe();
    // The store is a module singleton: leave the placeholder state for the other tests.
    if (useDataManagement().sources.find((s) => s.id === id)?.enabled) toggleSource(id);
  }
});

// Test plan: artifact_types_cover_every_chip.
test("ARTIFACT_FILTER keeps the placeholder artifacts of each type chip, and ALL keeps all six, in store order", () => {
  const { artifacts } = useDataManagement(); // not a render: the stubbed hook returns the snapshot
  const names = (facet: string) =>
    filterList(artifacts, ARTIFACT_FILTER, { query: "", facet }).map((a) => a.name);
  assert.deepEqual(names("report"), ["thermal_hydraulic_summary.pdf", "neutronics_report.pdf"]);
  assert.deepEqual(names("mesh"), ["core_mesh_v3.exo"]);
  assert.deepEqual(names("result"), ["dose_rate_map.csv", "cfd_flow_field.vtu", "keff_tally_results.csv"]);
  assert.deepEqual(names(ALL), [
    "thermal_hydraulic_summary.pdf",
    "core_mesh_v3.exo",
    "dose_rate_map.csv",
    "cfd_flow_field.vtu",
    "neutronics_report.pdf",
    "keff_tally_results.csv",
  ]);
});
