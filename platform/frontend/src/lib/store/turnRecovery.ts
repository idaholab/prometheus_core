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
 * Recover a turn whose `POST /api/chat/messages` reply never reached the page.
 *
 * A long turn (a multi-minute agent run) holds one HTTP request open for its whole
 * duration. If that connection is silently dropped on the way (dev proxy, laptop
 * sleep, network change) the backend still finishes the turn and stores the reply,
 * but the page keeps showing the spinner forever. So while a turn is awaited the
 * store also polls the stored transcript, and once it holds an assistant reply
 * newer than the turn's start, it renders the transcript and stops waiting.
 *
 * Kept as a leaf module with only a type import, which is erased, so it is
 * unit-testable under `node --test`.
 */

import type { ConversationMessage } from "../api/types.ts";

/** Start polling only once a turn has run this long; quick turns never poll. */
export const RECOVERY_GRACE_MS = 60_000;
/** Poll interval after the grace period. */
export const RECOVERY_POLL_MS = 15_000;

/** Number of assistant replies in a stored transcript. */
export function assistantCount(messages: readonly ConversationMessage[]): number {
  return messages.filter((m) => m.role === "assistant").length;
}

/**
 * Whether the stored transcript already holds the reply to the awaited turn:
 * it has more assistant replies than it had when the turn was sent.
 */
export function turnLanded(messages: readonly ConversationMessage[], baseline: number): boolean {
  return assistantCount(messages) > baseline;
}
