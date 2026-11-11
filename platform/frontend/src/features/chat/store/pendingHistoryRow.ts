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

/**
 * Show a new chat in Chat History from the start of its first turn.
 *
 * `GET /api/conversations/recent` lists a conversation only after the backend stores
 * its first turn, so a new chat is missing from the list while that turn runs. While
 * the open conversation awaits a reply and is missing from the server list, a local
 * pending row stands in for it at the top. Once the server list holds the id, the
 * server row wins and the local row goes away.
 *
 * Kept as a leaf module with only a type import, which is erased, so it is
 * unit-testable under `node --test` (`ChatHistory.tsx` itself pulls in the API client
 * and can only run inside Vite).
 */

import type { ConversationSummary } from "@/lib/api/types.ts";

/** A Chat History row, as `GET /api/conversations/recent` returns it. */
export type HistoryRowLike = ConversationSummary;

/** The open conversation, as far as Chat History needs it. */
export type OpenConversation = {
  conversationId: string | null;
  firstQuery: string | null;
  awaiting: boolean;
  now: string;
};

/**
 * `rows` with a local pending row first for the open conversation, when it awaits a
 * reply and is missing from the list (no row has its id). Otherwise `rows` itself,
 * unchanged.
 */
export function withPendingRow<R extends HistoryRowLike>(rows: R[], open: OpenConversation): (R | HistoryRowLike)[] {
  const { conversationId, firstQuery, awaiting, now } = open;
  if (!awaiting || !conversationId || !firstQuery) return rows;
  if (rows.some((r) => r.conversation_id === conversationId)) return rows;
  const pendingRow: HistoryRowLike = {
    conversation_id: conversationId,
    title: "",
    query: firstQuery,
    status: "unknown",
    timestamp: now,
    pending: true,
  };
  return [pendingRow, ...rows];
}
