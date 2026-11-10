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
 * Chat-history list rendered in `LeftPanel`'s sidebar.
 *
 * Fetches `GET /api/conversations/recent` (already user-scoped server-side —
 * see `backend/app/routers/conversations.py`) and re-fetches whenever
 * `historyVersion` changes (a turn completed, New Chat was clicked, or a past
 * chat was opened — see `lib/store/chat.ts`). Sending a new chat's first turn
 * does not refetch: while that turn runs and the server list lacks the chat, a
 * local pending row stands in for it at the top (`lib/store/pendingHistoryRow.ts`),
 * and the server row replaces it once a refetch lists it. Degrades to the
 * header alone when Redis is unavailable, matching the endpoint's
 * graceful-degrade shape.
 * Opening a row calls `onOpenConversation` first, so the shell shows Home.
 *
 * `historyVersion` only bumps for events on the *currently open* conversation,
 * so a different conversation's own background turn finishing wouldn't
 * otherwise clear its "pending" badge (`ConversationSummary.pending`, from
 * `agent:status:{id}`) until something else happened to trigger a refetch.
 * While any row is pending, a short poll picks that up without needing full
 * per-conversation live tracking (see the "Prometheus Chat History Pending
 * Response Handling" note for why that's future work, not this).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Plus } from "lucide-react";
import { api } from "@/lib/api/client";
import { chatStore, useChatState } from "./store/chat";
import { withPendingRow } from "./store/pendingHistoryRow";
import type { ConversationSummary } from "@/lib/api/types";
import { ChatHistoryItem } from "./ChatHistoryItem";

const PENDING_POLL_MS = 8000;

interface Props {
  onNewChat: () => void;
  onOpenConversation: () => void;
}

export function ChatHistory({ onNewChat, onOpenConversation }: Props) {
  const { conversationId, resumingConversationId, historyVersion, items, awaiting } = useChatState();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  // Whether the last fetch returned `available: true`; the local pending row is
  // merged only then, so a Valkey outage keeps the header-only state.
  const [available, setAvailable] = useState(false);
  // Ids deleted here, so a deleted open conversation gets no local pending row back.
  const [deletedIds, setDeletedIds] = useState<ReadonlySet<string>>(() => new Set());
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(() => {
    void api
      .getRecentConversations()
      .then((res) => {
        setAvailable(res.available);
        setConversations(res.available ? res.conversations : []);
      })
      .catch(() => {
        setAvailable(false);
        setConversations([]);
      })
      .finally(() => setLoaded(true));
  }, []);

  // `historyVersion` is a dependency purely to trigger a refetch on every
  // history-affecting event; its value is never read here.
  useEffect(() => {
    refresh();
  }, [historyVersion, refresh]);

  const firstUser = items.find((it) => it.kind === "user");
  const firstQuery = firstUser?.kind === "user" ? firstUser.text : null;
  const rows = useMemo(
    () =>
      available
        ? withPendingRow(conversations, {
            conversationId: conversationId && !deletedIds.has(conversationId) ? conversationId : null,
            firstQuery,
            awaiting,
            now: new Date().toISOString(),
          })
        : conversations,
    [available, conversations, conversationId, deletedIds, firstQuery, awaiting],
  );

  const anyPending = rows.some((c) => c.pending);
  useEffect(() => {
    if (!anyPending) return;
    pollRef.current = setInterval(refresh, PENDING_POLL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [anyPending, refresh]);

  return (
    <div className="flex flex-col gap-2 pb-3">
      <h2 className="m-0 px-1 text-[11px] font-semibold text-base-content/60">Chat History</h2>
      <button
        onClick={onNewChat}
        className="flex items-center gap-1.5 px-1 text-xs text-base-content/60 transition-colors hover:text-base-content cursor-pointer"
      >
        <Plus size={12} />
        New Chat
      </button>

      {loaded && rows.length > 0 && (
        <div className="flex flex-col gap-0.5">
          {rows.map((c) => (
            <ChatHistoryItem
              key={c.conversation_id}
              conversation={c}
              // `conversationId` only flips once the resume resolves, so during the
              // fetch prefer the id being loaded — otherwise the row the user just
              // clicked sits unhighlighted for the whole round trip.
              active={c.conversation_id === (resumingConversationId ?? conversationId)}
              onSelect={() => {
                onOpenConversation();
                void chatStore.loadConversation(c.conversation_id);
              }}
              onRenamed={(title) =>
                setConversations((prev) =>
                  prev.map((it) => (it.conversation_id === c.conversation_id ? { ...it, title } : it)),
                )
              }
              onDeleted={() => {
                setDeletedIds((prev) => new Set(prev).add(c.conversation_id));
                setConversations((prev) =>
                  prev.filter((it) => it.conversation_id !== c.conversation_id),
                );
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}
