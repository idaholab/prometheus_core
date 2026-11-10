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
 * One row in the sidebar's chat-history list: the conversation's title (click
 * to resume it) plus a relative date, which swaps to a three-dot
 * rename/delete menu on hover/focus so the row stays uncluttered.
 *
 * No shared dropdown/menu primitive exists yet in this app — daisyui's
 * `dropdown`/`menu` classes are already loaded (see `index.css`), so this is
 * the lowest-friction idiomatic choice here.
 */

import { useRef, useState } from "react";
import { MoreVertical, Trash2, Pencil, Loader2 } from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import type { ConversationSummary } from "@/lib/api/types";

interface Props {
  conversation: ConversationSummary;
  active: boolean;
  onSelect: () => void;
  onRenamed: (title: string) => void;
  onDeleted: () => void;
}

const DAY_MS = 24 * 60 * 60 * 1000;

/** "Today" / "Yesterday" / "Oct 24" / "Oct 24, 2024" from an ISO timestamp. */
function relativeDay(timestamp: string): string {
  if (!timestamp) return "";
  const then = new Date(timestamp);
  if (Number.isNaN(then.getTime())) return "";
  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const now = new Date();
  const days = Math.round((startOfDay(now) - startOfDay(then)) / DAY_MS);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  return then.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    ...(then.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  });
}

export function ChatHistoryItem({ conversation, active, onSelect, onRenamed, onDeleted }: Props) {
  const [renaming, setRenaming] = useState(false);
  const label = conversation.title || conversation.query || "Untitled chat";
  // Holds the rename input only; the row itself renders `label` from props.
  const [title, setTitle] = useState(label);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const detailsRef = useRef<HTMLDetailsElement>(null);

  const closeMenu = () => detailsRef.current?.removeAttribute("open");

  async function submitRename(): Promise<void> {
    const next = title.trim();
    if (!next || next === label) {
      setRenaming(false);
      setTitle(label);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.renameConversation(conversation.conversation_id, next);
      onRenamed(next);
      setRenaming(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to rename.");
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(): Promise<void> {
    closeMenu();
    setBusy(true);
    setError(null);
    try {
      await api.deleteConversation(conversation.conversation_id);
      onDeleted();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to delete.");
      setBusy(false);
    }
  }

  if (renaming) {
    return (
      <div className="px-1">
        <input
          className="input input-xs input-bordered w-full"
          value={title}
          autoFocus
          disabled={busy}
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void submitRename();
            if (e.key === "Escape") {
              setRenaming(false);
              setTitle(label);
            }
          }}
          onBlur={() => void submitRename()}
        />
        {error && <p className="text-error text-xs px-1 pt-0.5">{error}</p>}
      </div>
    );
  }

  return (
    <div
      className={`group flex items-center rounded-md py-1.5 pl-3 pr-2 ${
        active ? "border border-primary bg-primary/15" : "hover:bg-base-300"
      }`}
    >
      <button
        className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
        onClick={onSelect}
        disabled={busy}
        title={conversation.pending ? `${label} (response in progress)` : label}
      >
        <span
          className={`truncate text-[13px] ${
            active ? "font-semibold text-base-content" : "text-base-content/80"
          }`}
        >
          {label}
        </span>
        {conversation.pending && (
          <Loader2
            size={12}
            className="shrink-0 animate-spin text-primary"
            aria-label="Response in progress"
          />
        )}
      </button>

      {/* Date by default; the options menu takes its place on hover/focus. */}
      <span className="shrink-0 pl-2 text-[11px] text-base-content/50 group-hover:hidden group-focus-within:hidden">
        {relativeDay(conversation.timestamp)}
      </span>
      <details
        ref={detailsRef}
        className="dropdown dropdown-end hidden group-hover:block group-focus-within:block"
      >
        <summary className="btn btn-ghost btn-xs btn-square" aria-label="Chat options">
          <MoreVertical size={14} />
        </summary>
        <ul className="dropdown-content menu menu-sm menu-panel z-10 w-32">
          <li>
            <button
              onClick={() => {
                closeMenu();
                setTitle(label);
                setRenaming(true);
              }}
            >
              <Pencil size={13} /> Rename
            </button>
          </li>
          <li>
            <button className="text-error" onClick={() => void handleDelete()}>
              <Trash2 size={13} /> Delete
            </button>
          </li>
        </ul>
      </details>
      {error && <p className="text-error text-xs px-1">{error}</p>}
    </div>
  );
}
