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
 * store also polls the stored transcript, and once it holds the reply to *this*
 * turn -- this turn's user message, stored after the send, directly followed by an
 * assistant message -- it appends that reply and stops waiting.
 *
 * A bare count of assistant messages is not enough: a second tab sending in the same
 * conversation adds an assistant message too, and would settle this turn with the
 * wrong reply. Matching the user message means a turn that can't be matched simply
 * isn't recovered (the POST reply, or reopening the conversation, still shows it),
 * rather than showing a reply that belongs to another turn.
 *
 * Kept as a leaf module with only type imports, which are erased, so it is
 * unit-testable without the API client.
 */

import type { ChatMessageRequest, ConversationMessage } from "../api/types.ts";

/** Start polling only once a turn has run this long; quick turns never poll. */
export const RECOVERY_GRACE_MS = 60_000;
/** Poll interval after the grace period. */
export const RECOVERY_POLL_MS = 15_000;

/** The user message the backend stores for a turn sent with uploads and no text
 * (its neutral default query, `routers/chat.py`). */
export const UPLOAD_ONLY_QUERY = "Please process the uploaded file(s).";
/** The user message the client-agent stores for form answers sent with no query
 * (`orchestrator/chat_flow.py`). */
export const FOLLOWUP_DEFAULT_QUERY = "Provided requested inputs.";

/**
 * The user message this request is stored under, or `null` when it stores none the
 * transcript shows (a plan approval or rejection), so the turn can't be matched and
 * is not watched. A slash-command workflow is stored under a rewritten query and so
 * never matches either; it just isn't recovered.
 */
export function expectedUserMessage(body: ChatMessageRequest): string | null {
  if (body.plan_approved || body.plan_rejected) return null;
  const query = (body.query ?? "").trim();
  if (query) return query;
  if (body.upload_ids?.length) return UPLOAD_ONLY_QUERY;
  if (body.followup_answers) return FOLLOWUP_DEFAULT_QUERY;
  return null;
}

/**
 * The index from which this turn's user message can appear in the stored
 * transcript, given the transcript read when the turn was sent.
 *
 * The client-agent stores the user message as the turn starts, so the send-time
 * read can already end with it; in that case the search starts on that message.
 */
export function turnStart(baseline: readonly ConversationMessage[], userText: string): number {
  const last = baseline.at(-1);
  return last && last.role === "user" && last.content === userText ? baseline.length - 1 : baseline.length;
}

/**
 * The index of the stored reply to this turn, or `null` while it hasn't landed:
 * the first user message at or after `start` whose text is `userText`, when the
 * message right after it is an assistant message. Another user message between
 * them (a concurrent turn from another tab) means the reply can't be attributed,
 * so it is not taken.
 */
export function storedReplyIndex(
  messages: readonly ConversationMessage[],
  start: number,
  userText: string,
): number | null {
  for (let i = Math.max(0, start); i < messages.length; i += 1) {
    const m = messages[i];
    if (m.role !== "user" || m.content !== userText) continue;
    return messages[i + 1]?.role === "assistant" ? i + 1 : null;
  }
  return null;
}

/** Conversation statuses meaning the stored reply was a form or a plan card, which
 * the transcript can't rebuild (see `ConversationStateClient._infer_status`). */
export function isPendingInputStatus(status: string | undefined): boolean {
  return status === "needs_info" || status === "plan_ready";
}

/** Shown under a recovered reply that asked for input or approval. Its form or plan
 * card can't be rebuilt from the transcript (a reload restores it as text too). */
export const INPUT_NOT_RECOVERED =
  "This reply asks for your input, but its form could not be recovered. Reply in the chat to continue.";
