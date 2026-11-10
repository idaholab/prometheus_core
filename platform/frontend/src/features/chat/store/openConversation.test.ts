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

import { test } from "vitest";
import assert from "node:assert/strict";
import { readOpenConversationId, saveOpenConversationId } from "./openConversation.ts";

/** Minimal Storage stand-in. `throws` models Safari private browsing and
 * "block site data", where touching sessionStorage raises instead of
 * returning null — the case the module has to survive. */
function installStorage(opts: { throws?: boolean } = {}): Map<string, string> {
  const backing = new Map<string, string>();
  const boom = () => {
    throw new Error("SecurityError: sessionStorage is not available");
  };
  (globalThis as Record<string, unknown>).sessionStorage = {
    getItem: (k: string) => (opts.throws ? boom() : (backing.get(k) ?? null)),
    setItem: (k: string, v: string) => (opts.throws ? boom() : void backing.set(k, v)),
    removeItem: (k: string) => (opts.throws ? boom() : void backing.delete(k)),
  };
  return backing;
}

test("round-trips a conversation id", () => {
  installStorage();
  assert.equal(readOpenConversationId(), null);
  saveOpenConversationId("conv-1");
  assert.equal(readOpenConversationId(), "conv-1");
});

test("saving null forgets the id", () => {
  installStorage();
  saveOpenConversationId("conv-1");
  saveOpenConversationId(null);
  assert.equal(readOpenConversationId(), null);
});

test("an empty stored value reads as null, not as an empty id", () => {
  // Guards the `bootstrap()` branch: `if (saved)` must not attempt a resume of "".
  const backing = installStorage();
  backing.set("prometheus.openConversationId", "");
  assert.equal(readOpenConversationId(), null);
});

test("survives storage that throws on every access", () => {
  installStorage({ throws: true });
  assert.equal(readOpenConversationId(), null);
  assert.doesNotThrow(() => saveOpenConversationId("conv-1"));
  assert.doesNotThrow(() => saveOpenConversationId(null));
});

test("no storage object at all is survivable", () => {
  delete (globalThis as Record<string, unknown>).sessionStorage;
  assert.equal(readOpenConversationId(), null);
  assert.doesNotThrow(() => saveOpenConversationId("conv-1"));
});
