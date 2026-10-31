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

// A turn whose HTTP reply was dropped is recovered from the stored transcript, but
// only with the reply to this turn: its user message, stored after the send,
// directly followed by an assistant message.
import assert from "node:assert/strict";
import { test } from "vitest";

import type { ConversationMessage } from "../api/types.ts";
import {
  FOLLOWUP_DEFAULT_QUERY,
  UPLOAD_ONLY_QUERY,
  expectedUserMessage,
  isPendingInputStatus,
  storedReplyIndex,
  turnStart,
} from "./turnRecovery.ts";

const msg = (role: "user" | "assistant", content: string): ConversationMessage => ({
  role,
  content,
  timestamp: "2026-10-12T16:00:00Z",
  artifact_ids: [],
});

test("a new chat's first turn has landed once its reply follows its message", () => {
  assert.equal(storedReplyIndex([], 0, "run analysis"), null);
  assert.equal(storedReplyIndex([msg("user", "run analysis")], 0, "run analysis"), null);
  assert.equal(storedReplyIndex([msg("user", "run analysis"), msg("assistant", "done")], 0, "run analysis"), 1);
});

test("a later turn is not mistaken for landed by the previous turn's reply", () => {
  const before = [msg("user", "q1"), msg("assistant", "a1")];
  const start = turnStart(before, "q2");
  assert.equal(start, 2);
  assert.equal(storedReplyIndex([...before, msg("user", "q2")], start, "q2"), null);
  assert.equal(storedReplyIndex([...before, msg("user", "q2"), msg("assistant", "a2")], start, "q2"), 3);
});

test("repeating an earlier question waits for the new reply, not the old one", () => {
  const before = [msg("user", "status?"), msg("assistant", "old")];
  const start = turnStart(before, "status?");
  assert.equal(storedReplyIndex(before, start, "status?"), null);
  assert.equal(storedReplyIndex([...before, msg("user", "status?"), msg("assistant", "new")], start, "status?"), 3);
});

test("a baseline read that already holds this turn's message starts on it", () => {
  const before = [msg("user", "q1"), msg("assistant", "a1"), msg("user", "q2")];
  const start = turnStart(before, "q2");
  assert.equal(start, 2);
  assert.equal(storedReplyIndex([...before, msg("assistant", "a2")], start, "q2"), 3);
});

test("another tab's reply in the same conversation does not settle this turn", () => {
  const before = [msg("user", "q1"), msg("assistant", "a1")];
  const start = turnStart(before, "mine");
  // The other tab's turn lands first: no message of ours yet.
  const theirsFirst = [...before, msg("user", "theirs"), msg("assistant", "their reply")];
  assert.equal(storedReplyIndex(theirsFirst, start, "mine"), null);
  // Interleaved: their message sits between ours and the next reply, which can't be attributed.
  const interleaved = [...before, msg("user", "mine"), msg("user", "theirs"), msg("assistant", "a reply")];
  assert.equal(storedReplyIndex(interleaved, start, "mine"), null);
  // Ours lands after theirs: ours is matched, not theirs.
  assert.equal(storedReplyIndex([...theirsFirst, msg("user", "mine"), msg("assistant", "my reply")], start, "mine"), 5);
});

test("the expected user message follows what the backend stores for each request", () => {
  assert.equal(expectedUserMessage({ query: "  run it  " }), "run it");
  assert.equal(expectedUserMessage({ query: "", upload_ids: [{ upload_id: "u" } as never] }), UPLOAD_ONLY_QUERY);
  assert.equal(expectedUserMessage({ query: "", followup_answers: { a: 1 } }), FOLLOWUP_DEFAULT_QUERY);
  assert.equal(expectedUserMessage({ query: "Which mesh?", followup_answers: { a: 1 } }), "Which mesh?");
  // A plan decision stores no user message the transcript shows.
  assert.equal(expectedUserMessage({ query: "", plan_approved: true, plan_rejected: false }), null);
  assert.equal(expectedUserMessage({ query: "", plan_approved: false, plan_rejected: true }), null);
});

test("only a form or a plan card counts as a reply waiting on the user", () => {
  assert.equal(isPendingInputStatus("needs_info"), true);
  assert.equal(isPendingInputStatus("plan_ready"), true);
  assert.equal(isPendingInputStatus("completed"), false);
  assert.equal(isPendingInputStatus("unknown"), false);
  assert.equal(isPendingInputStatus(undefined), false);
});
