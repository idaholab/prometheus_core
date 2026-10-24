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

// A turn whose HTTP reply was dropped is recovered from the stored transcript:
// turnLanded() is true only once the transcript holds more assistant replies than
// it did when the turn was sent.
import assert from "node:assert/strict";
import test from "node:test";

import type { ConversationMessage } from "../api/types.ts";
import { assistantCount, turnLanded } from "./turnRecovery.ts";

const msg = (role: "user" | "assistant", content: string): ConversationMessage => ({
  role,
  content,
  timestamp: "2026-10-12T16:00:00Z",
  artifact_ids: [],
});

test("assistantCount counts only assistant replies", () => {
  assert.equal(assistantCount([]), 0);
  assert.equal(assistantCount([msg("user", "q1"), msg("assistant", "a1"), msg("user", "q2")]), 1);
});

test("a new chat's first turn has landed once one reply is stored", () => {
  assert.equal(turnLanded([], 0), false);
  assert.equal(turnLanded([msg("user", "run analysis")], 0), false);
  assert.equal(turnLanded([msg("user", "run analysis"), msg("assistant", "done")], 0), true);
});

test("a later turn is not mistaken for landed by the previous turn's reply", () => {
  const before = [msg("user", "q1"), msg("assistant", "a1")];
  const baseline = assistantCount(before);
  assert.equal(turnLanded([...before, msg("user", "q2")], baseline), false);
  assert.equal(turnLanded([...before, msg("user", "q2"), msg("assistant", "a2")], baseline), true);
});
