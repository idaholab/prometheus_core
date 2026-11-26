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
import { afterEach, test, vi } from "vitest";
import { newTurnId } from "./turnId.ts";

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
/** The backend's `TURN_ID_PATTERN` (`backend/app/contract.py`). */
const TURN_ID_PATTERN = /^[A-Za-z0-9-]{8,64}$/;

afterEach(() => vi.restoreAllMocks());

test("uses crypto.randomUUID when the context has it", () => {
  const spy = vi.spyOn(crypto, "randomUUID");
  const id = newTurnId();
  assert.equal(spy.mock.calls.length, 1);
  assert.match(id, UUID_V4);
});

test("without crypto.randomUUID (plain http on a LAN address) it builds a v4 id", () => {
  const original = crypto.randomUUID;
  Object.defineProperty(crypto, "randomUUID", { value: undefined, configurable: true });
  try {
    const ids = new Set(Array.from({ length: 50 }, newTurnId));
    assert.equal(ids.size, 50, "fresh each time");
    for (const id of ids) {
      assert.match(id, UUID_V4);
      assert.match(id, TURN_ID_PATTERN);
    }
  } finally {
    Object.defineProperty(crypto, "randomUUID", { value: original, configurable: true });
  }
});
