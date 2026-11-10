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

// A new chat shows in Chat History, marked pending, from the start of its first turn:
// withPendingRow() adds exactly one pending row at the top for the open conversation only
// while it awaits a reply and is missing from the server list, and returns the server list
// unchanged otherwise.
import assert from "node:assert/strict";
import { test } from "vitest";

import { withPendingRow, type HistoryRowLike, type OpenConversation } from "./pendingHistoryRow.ts";

const row = (conversation_id: string, query: string): HistoryRowLike => ({
  conversation_id,
  title: `Title of ${query}`,
  query,
  status: "completed",
  timestamp: "2026-10-01T09:00:00Z",
  pending: false,
});

const serverRows = (): HistoryRowLike[] => [row("older-1", "first older chat"), row("older-2", "second older chat")];

const open = (overrides: Partial<OpenConversation> = {}): OpenConversation => ({
  conversationId: "new-chat",
  firstQuery: "plot the mesh",
  awaiting: true,
  now: "2026-10-03T12:00:00Z",
  ...overrides,
});

test("a new chat awaiting its first reply and missing from the list gets one pending row at the top", () => {
  const rows = serverRows();

  const result = withPendingRow(rows, open());

  assert.equal(result.length, rows.length + 1);
  assert.deepEqual(result[0], {
    conversation_id: "new-chat",
    title: "",
    query: "plot the mesh",
    status: "unknown",
    timestamp: "2026-10-03T12:00:00Z",
    pending: true,
  });
  assert.deepEqual(result.slice(1), serverRows());
});

test("an empty server list gets only the pending row", () => {
  const result = withPendingRow([], open());

  assert.deepEqual(
    result.map((r) => [r.conversation_id, r.query, r.pending]),
    [["new-chat", "plot the mesh", true]],
  );
});

test("once the server list holds the open id, the list is unchanged and the server row wins", () => {
  const stored = row("new-chat", "plot the mesh");
  const rows = [stored, ...serverRows()];

  const result = withPendingRow(rows, open());

  assert.deepEqual(result, [row("new-chat", "plot the mesh"), ...serverRows()]);
  const forOpenId = result.filter((r) => r.conversation_id === "new-chat");
  assert.equal(forOpenId.length, 1, "the open conversation must not be listed twice");
  assert.equal(forOpenId[0], stored);
  assert.equal(forOpenId[0].pending, false);
});

for (const [name, overrides] of [
  ["not awaiting a reply", { awaiting: false }],
  ["a null conversation id", { conversationId: null }],
  ["a null first query", { firstQuery: null }],
  ["an empty first query", { firstQuery: "" }],
] as const) {
  test(`${name} leaves the server list unchanged`, () => {
    const result = withPendingRow(serverRows(), open(overrides));

    assert.deepEqual(result, serverRows());
    assert.ok(result.every((r) => !r.pending));
  });
}
