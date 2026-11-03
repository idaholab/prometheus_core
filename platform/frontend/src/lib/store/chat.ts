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
 * Chat store — replaces Chainlit's Recoil atoms + `useChatMessages`/`useChatInteract`.
 *
 * A minimal `useSyncExternalStore`-backed store (Decision A: drop Recoil) that owns
 * conversation state and the network layer:
 *
 * - `bootstrap()` loads `/api/config` + creates a session.
 * - `connect()` opens the `/api/events` SSE stream; `disconnect()` closes it.
 * - `sendTurn` / `submitFollowup` / `decidePlan` POST `/api/chat/messages` and reduce
 *   the `ChatMessageResponse` into `ChatItem`s.
 * - SSE `status` events feed the in-flight turn's progress (ToolStep); `task_progress`
 *   / `task_done` drive backgrounded tasks.
 *
 * `ChatItem` is the app's own message type; `Chat.tsx` renders it, and the artifact
 * adapter (Step 05) converts `AssistantItem.artifacts` → viewer elements.
 */

import { useSyncExternalStore } from "react";
import { api, ApiError } from "@/lib/api/client";
import { openEventStream } from "@/lib/api/events";
import type {
  ArtifactMeta,
  ChatMessageRequest,
  ChatMessageResponse,
  ConfigResponse,
  ConversationMessage,
  FormField,
  StatusEvent,
  TaskDoneEvent,
  TaskProgressEvent,
  TurnDoneEvent,
  UploadDescriptor,
} from "@/lib/api/types";
import { artifactsPerTurn } from "./transcriptArtifacts";
import { readOpenConversationId, saveOpenConversationId } from "./openConversation";

// --- item model -------------------------------------------------------------

interface BaseItem {
  id: string;
}
export interface UserItem extends BaseItem {
  kind: "user";
  text: string;
}
export interface AssistantItem extends BaseItem {
  kind: "assistant";
  text: string;
  artifacts: ArtifactMeta[];
  recommendedMaterials: string[];
  followUpSuggestions: string[];
}
/** In-flight turn progress or a backgrounded task — renders as the ToolStep UI. */
export interface ToolItem extends BaseItem {
  kind: "tool";
  turnId?: string;
  taskId?: string;
  name: string;
  history: string[];
  done: boolean;
}
export interface NeedsInfoItem extends BaseItem {
  kind: "needs_info";
  turnId: string;
  message: string;
  fields: FormField[];
  submitted: boolean;
}
export interface PlanItem extends BaseItem {
  kind: "plan";
  turnId: string;
  message: string;
  plan: Record<string, unknown>;
  autoApprove: boolean;
  decided: null | "approved" | "rejected";
}
export interface ErrorItem extends BaseItem {
  kind: "error";
  text: string;
}
export type ChatItem =
  | UserItem
  | AssistantItem
  | ToolItem
  | NeedsInfoItem
  | PlanItem
  | ErrorItem;

// --- state ------------------------------------------------------------------

export interface ChatState {
  ready: boolean;
  items: ChatItem[];
  awaiting: boolean;
  conversationId: string | null;
  /** The conversation id of a resume that is still in flight, else `null`.
   *
   * Distinguishes "this conversation is empty" from "we are still fetching it":
   * `loadConversation()` clears `items` before awaiting, so without this the UI
   * could only see an empty transcript and showed the welcome screen — chips and
   * all — for the whole multi-second round trip. It doubles as `applyResume()`'s
   * staleness guard, so two overlapping resumes cannot fight over `items`. */
  resumingConversationId: string | null;
  config: ConfigResponse | null;
  autoApprove: boolean;
  /** Bumped whenever the conversation list may have changed (new/renamed title,
   * a completed turn, a switch to another conversation) — components rendering
   * the history list re-fetch when this changes. */
  historyVersion: number;
  /** Set when the stream died *and* a `/api/auth/me` probe confirmed the session
   * is gone. Watched by `useAuthLost()` so the UI can prompt for re-login
   * instead of sitting there silently receiving nothing. */
  authLost: boolean;
}

const initialState: ChatState = {
  ready: false,
  items: [],
  awaiting: false,
  conversationId: null,
  resumingConversationId: null,
  config: null,
  autoApprove: false,
  historyVersion: 0,
  authLost: false,
};

let state: ChatState = initialState;
const listeners = new Set<() => void>();
const awaitedTaskIds = new Set<string>();
let closeStream: (() => void) | null = null;

/** Ordering for session rebinds (new chat, resume). Every rebind takes the next
 * value and sends it as `bind_seq`; the server ignores a rebind whose seq is not
 * newer than the last one it applied, so a slow request cannot rebind over a
 * newer click. The same value is the client's staleness marker: a rebind is
 * current while `seq === lastBindSeq`. `Date.now()` rather than a plain counter so
 * that two tabs sharing one session still order by wall clock, and a reload does
 * not restart below the seq the server already stored. */
let lastBindSeq = 0;
function nextBindSeq(): number {
  lastBindSeq = Math.max(lastBindSeq + 1, Date.now());
  return lastBindSeq;
}
const isLatestBind = (seq: number): boolean => seq === lastBindSeq;

function emit(): void {
  for (const l of listeners) l();
}
function set(patch: Partial<ChatState>): void {
  state = { ...state, ...patch };
  // Mirror every conversation-id change into per-tab storage, so a page reload
  // (see `bootstrap()`) resumes where it left off. Hooked here rather than at
  // each of the three call sites (bootstrap / reset / loadConversation) so a
  // future fourth one cannot forget it.
  if ("conversationId" in patch) saveOpenConversationId(patch.conversationId ?? null);
  emit();
}
function setItems(update: (items: ChatItem[]) => ChatItem[]): void {
  set({ items: update(state.items) });
}

let idCounter = 0;
function nextId(prefix: string): string {
  idCounter += 1;
  return `${prefix}-${idCounter}`;
}

function bumpHistory(): void {
  set({ historyVersion: state.historyVersion + 1 });
}

// --- response → items reducer ----------------------------------------------

function assistantItem(text: string, artifacts: ArtifactMeta[] = []): AssistantItem {
  return {
    id: nextId("assistant"),
    kind: "assistant",
    text,
    artifacts,
    recommendedMaterials: [],
    followUpSuggestions: [],
  };
}

function assistantFrom(res: ChatMessageResponse, text: string): AssistantItem {
  return {
    ...assistantItem(text, res.artifacts ?? []),
    recommendedMaterials: res.recommended_materials ?? [],
    followUpSuggestions: res.follow_up_suggestions ?? [],
  };
}

/** Map a resumed conversation's normalized transcript to renderable items. Each
 * assistant turn gets only the artifacts it produced (see `artifactsPerTurn`). */
function itemsFromTranscript(messages: ConversationMessage[], artifacts: ArtifactMeta[]): ChatItem[] {
  const perTurn = artifactsPerTurn(messages, artifacts);
  return messages.map((m, i) =>
    m.role === "user"
      ? { id: nextId("user"), kind: "user", text: m.content }
      : assistantItem(m.content, perTurn[i]),
  );
}

/** Mark the in-flight turn's ToolStep done (leaves its progress trace collapsed). */
function finalizeTurnProgress(turnId: string): void {
  setItems((items) =>
    items.map((it) =>
      it.kind === "tool" && it.turnId === turnId ? { ...it, done: true } : it,
    ),
  );
}

/** Append the item(s) a terminal ChatMessageResponse maps to. */
function applyResponse(res: ChatMessageResponse): void {
  finalizeTurnProgress(res.turn_id);
  // A completed turn may have just gotten this conversation its first LLM
  // title, or changed its inferred status — let the history list re-fetch.
  bumpHistory();

  switch (res.status) {
    case "answer":
    case "recommendation": {
      const text = res.response_text ?? res.message ?? "";
      setItems((items) => [...items, assistantFrom(res, text)]);
      break;
    }
    case "completed": {
      const text = res.report ?? res.message ?? "";
      setItems((items) => [...items, assistantFrom(res, text)]);
      break;
    }
    case "needs_info": {
      const fields = res.followup_questions ?? [];
      if (fields.length === 0) {
        // Backend still sends needs_info with zero questions; render the message as a
        // normal bubble rather than an empty form that would hang (frontend note).
        setItems((items) => [...items, assistantFrom(res, res.message ?? "")]);
      } else {
        setItems((items) => [
          ...items,
          {
            id: nextId("needs_info"),
            kind: "needs_info",
            turnId: res.turn_id,
            message: res.message ?? "",
            fields,
            submitted: false,
          },
        ]);
      }
      break;
    }
    case "plan_ready": {
      const item: PlanItem = {
        id: nextId("plan"),
        kind: "plan",
        turnId: res.turn_id,
        message: res.message ?? "",
        plan: res.plan ?? {},
        autoApprove: Boolean(res.auto_approve),
        decided: null,
      };
      setItems((items) => [...items, item]);
      // auto_approve: execute immediately without prompting (no buttons rendered).
      if (item.autoApprove) {
        void decidePlan(item.id, true);
      }
      break;
    }
    case "executing": {
      setItems((items) => [
        ...items,
        {
          id: nextId("tool"),
          kind: "tool",
          turnId: res.turn_id,
          name: res.message ?? "Executing the plan…",
          history: [],
          done: false,
        },
      ]);
      break;
    }
    case "backgrounded": {
      if (res.task_id) awaitedTaskIds.add(res.task_id);
      setItems((items) => [
        ...items,
        {
          id: nextId("tool"),
          kind: "tool",
          taskId: res.task_id ?? undefined,
          name: res.message ?? "Running in the background…",
          history: [],
          done: false,
        },
      ]);
      break;
    }
    case "error": {
      setItems((items) => [
        ...items,
        { id: nextId("error"), kind: "error", text: res.message ?? "An error occurred." },
      ]);
      break;
    }
  }
}

function appendError(text: string): void {
  setItems((items) => [...items, { id: nextId("error"), kind: "error", text }]);
}

// --- SSE handlers -----------------------------------------------------------

function onStatus(e: StatusEvent): void {
  const history = e.history ?? [e.message];
  setItems((items) => {
    const idx = items.findIndex((it) => it.kind === "tool" && it.turnId === e.turn_id);
    if (idx >= 0) {
      const next = [...items];
      next[idx] = { ...(next[idx] as ToolItem), name: e.message, history };
      return next;
    }
    return [
      ...items,
      {
        id: nextId("tool"),
        kind: "tool",
        turnId: e.turn_id,
        name: e.message,
        history,
        done: false,
      },
    ];
  });
}

function onTaskProgress(e: TaskProgressEvent): void {
  if (!awaitedTaskIds.has(e.task_id)) return;
  setItems((items) =>
    items.map((it) =>
      it.kind === "tool" && it.taskId === e.task_id
        ? { ...it, name: e.message, history: [...it.history, e.message] }
        : it,
    ),
  );
}

function onTaskDone(e: TaskDoneEvent): void {
  if (!awaitedTaskIds.has(e.task_id)) return;
  awaitedTaskIds.delete(e.task_id);
  // Close out the task's progress ToolStep.
  setItems((items) =>
    items.map((it) =>
      it.kind === "tool" && it.taskId === e.task_id ? { ...it, done: true } : it,
    ),
  );
  if (e.response) {
    applyResponse(e.response);
  } else if (e.message) {
    appendError(e.message);
  }
}

// --- actions ----------------------------------------------------------------

/** Rebind the server session to `conversationId` and replay its transcript.
 * Shared by `loadConversation()` (sidebar click) and `bootstrap()` (recovering
 * the open conversation after a reload) so the two cannot drift apart. */
async function applyResume(conversationId: string, seq: number): Promise<void> {
  // Same staleness discipline as `post()`: a resume superseded by a newer rebind
  // (another resume, or a New chat) must not apply its transcript, and must not
  // clear the newer one's spinner. The server applies the same ordering to the
  // session binding itself via `bind_seq`.
  set({ resumingConversationId: conversationId });
  try {
    const detail = await api.resumeConversation(conversationId, seq);
    if (!isLatestBind(seq)) return;
    set({
      conversationId: detail.conversation_id,
      autoApprove: detail.auto_approve_steps,
      items: itemsFromTranscript(detail.messages, detail.artifacts),
    });
  } finally {
    if (isLatestBind(seq)) set({ resumingConversationId: null });
  }
}

let bootstrapping = false;
/** Bumped by `suspendForReauth()` and `clear()`. A bootstrap captures it on entry
 * and writes no more state once it has changed: the session it was binding is
 * gone, and a stale `ready: true` would make the next `bootstrap()` return at once. */
let bootstrapGen = 0;

async function bootstrap(profile?: string): Promise<void> {
  // The run-once guard lives here rather than in a React ref on purpose. A Fast
  // Refresh re-executes this module (resetting `state`, so `ready` goes back to
  // false) but does *not* reset a component ref — so a ref guard stayed `true`
  // while `ready` was false, and the UI wedged on an empty transcript with
  // nothing in the console. Guard and guarded state are re-initialised together
  // here, so that cannot happen.
  if (bootstrapping || state.ready) return;
  bootstrapping = true;
  const gen = bootstrapGen;
  const isCurrent = () => gen === bootstrapGen;
  // A reload used to drop the user into an empty new chat with the previous
  // conversation orphaned in Valkey. If this tab had one open, resume it. The
  // marker goes up before `getConfig()` so the reload shows the spinner, not the
  // welcome screen, for that round trip too.
  const saved = readOpenConversationId();
  if (saved) set({ resumingConversationId: saved });
  try {
    const config = await api.getConfig();
    if (!isCurrent()) return;
    set({ config });

    if (saved) {
      try {
        await applyResume(saved, nextBindSeq());
        if (!isCurrent()) return;
        set({ ready: true });
        return;
      } catch (err) {
        if (!isCurrent()) return;
        if (!(err instanceof ApiError) || err.status !== 404) throw err;
        // 404 is definitive: soft-deleted, not ours, or evicted from Valkey.
        // Drop the id and start clean. Any other failure (network, 5xx) is
        // transient, so it propagates to the outer catch instead — that keeps
        // the saved id for the next attempt rather than silently forking a new
        // conversation and abandoning the old one on a momentary blip.
        saveOpenConversationId(null);
      }
    }

    const seq = nextBindSeq();
    const session = await api.createSession(profile, seq);
    if (!isCurrent()) return;
    // A newer rebind (a sidebar click) owns the session: the server kept it and
    // still answered 200 with an unbound id, so only mark the store ready.
    if (!isLatestBind(seq)) {
      set({ ready: true });
      return;
    }
    set({
      ready: true,
      conversationId: session.conversation_id,
      autoApprove: session.auto_approve_steps,
    });
  } catch (err) {
    if (!isCurrent()) return;
    // Surface a bootstrap failure but still let the UI render (empty). Drop the
    // early resume marker too, or a failed `getConfig()` leaves the spinner up.
    set({ ready: true });
    if (saved && state.resumingConversationId === saved) set({ resumingConversationId: null });
    appendError(err instanceof Error ? err.message : "Failed to start session.");
  } finally {
    // A superseding call already reset the flag, and a newer bootstrap may own it now.
    if (isCurrent()) bootstrapping = false;
  }
}

/** React to an `/api/events` error. See `EventStreamHandlers.onError` for why
 * `closed` is the whole question. */
async function onStreamError({ closed }: { closed: boolean }): Promise<void> {
  if (!closed) return;
  // A closed stream is usually an expired session cookie (the TTL is 24h, so a
  // tab left open overnight hits it), but it can also be a 502 from a
  // restarting backend. Probe before declaring the session dead: bouncing
  // someone to Login over a momentary proxy failure is the bug that made this
  // whole area feel flaky in the first place.
  try {
    await api.me();
    appendError("Live updates stopped. Reload the page to reconnect.");
  } catch (err) {
    if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
      set({ authLost: true });
    } else {
      appendError("Live updates stopped — the server is unreachable. Reload the page to reconnect.");
    }
  }
}

function connect(): void {
  if (closeStream) return;
  closeStream = openEventStream({
    onStatus,
    onTaskProgress,
    onTaskDone,
    onTurnDone,
    // On every (re)connect: a turn_done published while the stream was down went
    // nowhere, so ask once where the awaited turn stands.
    onOpen: () => {
      if (activeTurn) void recoverTurn(activeTurn.id);
    },
    onError: (info) => void onStreamError(info),
  });
}

function disconnect(): void {
  closeStream?.();
  closeStream = null;
}

/**
 * The one turn this tab is waiting on, or `null`. A turn's result can reach the page
 * two ways with the same body (`backend/CONTRACT.md`, "Delivery"): its POST reply and a
 * `turn_done` event. Whichever arrives first settles the turn through `settle()`, which
 * acts only while `activeTurn` still names that turn — so the second copy, a stopped
 * turn's late reply, and another tab's `turn_done` are all ignored. `stop()`, `reset()`,
 * `loadConversation()` and the auth teardowns clear it along with `awaiting`.
 */
let activeTurn: { id: string; conversationId: string | null } | null = null;

/** End turn `turnId` with `res`, once. Returns whether it was the turn being waited on. */
function settle(turnId: string, res: ChatMessageResponse): boolean {
  const turn = activeTurn;
  if (!turn || turn.id !== turnId) return false;
  // Cleared before applyResponse: an auto-approved plan starts the next turn from
  // inside it, and that turn must find the slot free.
  activeTurn = null;
  set({ awaiting: false });
  if (state.conversationId === turn.conversationId) {
    applyResponse(res);
  } else {
    // The user switched conversation after sending: the reply is persisted and shows
    // when that conversation is reopened. Let the history list refresh its status.
    bumpHistory();
  }
  return true;
}

function errorResponse(turnId: string, message: string): ChatMessageResponse {
  return { turn_id: turnId, status: "error", message };
}

/** Whether a failed POST may still have reached the backend, so the turn may be running:
 * a network failure (fetch's TypeError) or a gateway giving up on a long request. */
function mayStillBeRunning(err: unknown): boolean {
  if (err instanceof ApiError) return err.status === 502 || err.status === 503 || err.status === 504;
  return true;
}

/**
 * Ask the backend once where turn `turnId` stands, after this tab lost track of it: its
 * POST failed at the network level, or the event stream reconnected (a `turn_done` sent
 * while it was down went nowhere). Not a poll — `turn_done` or the next reconnect
 * covers a turn that is still running.
 */
async function recoverTurn(turnId: string): Promise<void> {
  let turn;
  try {
    turn = await api.getTurn(turnId);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      // The backend never started it (or it expired): nothing will settle it.
      settle(turnId, errorResponse(turnId, "Error communicating with agent."));
    }
    return; // unreachable backend: the stream's reconnect calls this again
  }
  if (turn.state === "done" && turn.response) settle(turnId, turn.response);
}

async function post(body: ChatMessageRequest): Promise<void> {
  const turnId = crypto.randomUUID();
  // The conversation is captured now: if the user switches before the turn ends,
  // the result belongs to this one, not to whatever is on screen (see `settle`). The
  // backend applies the same guard to its own session writes (`services/chat.py`).
  activeTurn = { id: turnId, conversationId: state.conversationId };
  set({ awaiting: true });
  try {
    const res = await api.sendMessage({ ...body, turn_id: turnId });
    settle(turnId, res);
  } catch (err) {
    if (mayStillBeRunning(err)) {
      await recoverTurn(turnId);
    } else {
      const message =
        err instanceof ApiError ? `Error communicating with agent: ${err.message}` : "Error communicating with agent.";
      settle(turnId, errorResponse(turnId, message));
    }
  }
}

/** A finished turn announced over the event stream (see `activeTurn`). */
function onTurnDone(e: TurnDoneEvent): void {
  settle(e.turn_id, e.response);
}

/** Send a user turn (optionally with staged uploads). */
async function sendTurn(query: string, uploads: UploadDescriptor[] = []): Promise<void> {
  const text = query.trim();
  if (!text && uploads.length === 0) return;
  setItems((items) => [
    ...items,
    { id: nextId("user"), kind: "user", text: text || "(uploaded file)" },
  ]);
  await post({ query: text, upload_ids: uploads.length ? uploads : null });
}

/** Answer a needs_info form (keys are FormField.id). */
async function submitFollowup(itemId: string, answers: Record<string, unknown>): Promise<void> {
  let query = "";
  setItems((items) =>
    items.map((it) => {
      if (it.id === itemId && it.kind === "needs_info") {
        query = it.message;
        return { ...it, submitted: true };
      }
      return it;
    }),
  );
  await post({ query, followup_answers: answers });
}

/** Approve or reject a pending plan. */
async function decidePlan(itemId: string, approved: boolean): Promise<void> {
  setItems((items) =>
    items.map((it) =>
      it.id === itemId && it.kind === "plan"
        ? { ...it, decided: approved ? "approved" : "rejected" }
        : it,
    ),
  );
  await post({ query: "", plan_approved: approved, plan_rejected: !approved });
}

/** Client-side stop — no server cancel endpoint exists yet (Decision D). */
function stop(): void {
  activeTurn = null;
  set({ awaiting: false });
}

/** New chat: fresh conversation_id + cleared transcript (no full reload). */
async function reset(profile?: string): Promise<void> {
  disconnect();
  awaitedTaskIds.clear();
  // Clearing `resumingConversationId` drops the spinner of any resume still in
  // flight; taking a new bind seq supersedes it, so it can apply neither its
  // transcript here nor its binding on the server.
  activeTurn = null;
  set({ items: [], awaiting: false, resumingConversationId: null });
  const seq = nextBindSeq();
  try {
    const session = await api.createSession(profile, seq);
    if (!isLatestBind(seq)) return;
    set({ conversationId: session.conversation_id, autoApprove: session.auto_approve_steps });
  } catch (err) {
    if (!isLatestBind(seq)) return;
    appendError(err instanceof Error ? err.message : "Failed to start a new conversation.");
  }
  connect();
  bumpHistory();
}

/** Reopen a past conversation: rebinds the session server-side (so the next
 * turn continues it) and replays its transcript. Mirrors `reset()`'s shape. */
async function loadConversation(conversationId: string): Promise<void> {
  disconnect();
  awaitedTaskIds.clear();
  activeTurn = null;
  set({ items: [], awaiting: false });
  const seq = nextBindSeq();
  try {
    await applyResume(conversationId, seq);
  } catch (err) {
    // A resume that lost the race must stay silent: appending its error would drop
    // a message from an abandoned conversation into the one now being loaded.
    if (!isLatestBind(seq)) return;
    appendError(err instanceof Error ? err.message : "Failed to open conversation.");
  }
  // Whichever rebind is newer owns the tail — reconnecting and bumping the history
  // list here would fire once per click during rapid switching.
  if (!isLatestBind(seq)) return;
  connect();
  bumpHistory();
}

export const chatStore = {
  bootstrap,
  connect,
  disconnect,
  sendTurn,
  loadConversation,
  submitFollowup,
  decidePlan,
  stop,
  reset,
  /** Auth expired mid-session: tear the stream down and let the UI fall back to
   * Login, but **keep** the remembered conversation id so signing back in
   * resumes the same conversation instead of opening an empty one. */
  suspendForReauth(): void {
    disconnect();
    // Everything re-derives from the resume on sign-in: bootstrap replays the
    // transcript, so stale items would only flash under the login screen, and
    // awaited ids from before the re-auth must not claim events after it.
    awaitedTaskIds.clear();
    nextBindSeq(); // supersede an in-flight rebind; its session is gone
    bootstrapGen += 1; // and an in-flight bootstrap, so it cannot mark the store ready
    bootstrapping = false;
    activeTurn = null;
    set({ ready: false, authLost: false, awaiting: false, resumingConversationId: null, items: [] });
  },
  /** Drop every trace of the signed-in user's chat: close the stream, forget
   * awaited tasks and the remembered conversation id, and reset state. Called
   * on logout (App.tsx), so the next user in this tab cannot inherit the
   * previous one's open conversation. */
  clear(): void {
    disconnect();
    awaitedTaskIds.clear();
    nextBindSeq(); // supersede an in-flight rebind
    saveOpenConversationId(null);
    bootstrapGen += 1;
    bootstrapping = false;
    activeTurn = null;
    state = initialState;
    emit();
  },
};

// --- React binding ----------------------------------------------------------

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}
function getSnapshot(): ChatState {
  return state;
}

/** Subscribe a component to the whole chat state. */
export function useChatState(): ChatState {
  return useSyncExternalStore(subscribe, getSnapshot);
}

/** Narrow subscription for App.tsx. Deliberately not `useChatState().authLost`:
 * App renders the entire tree, and the full state changes on every streamed
 * status update. Returning a boolean keeps re-renders to the transition itself. */
export function useAuthLost(): boolean {
  return useSyncExternalStore(subscribe, () => state.authLost);
}
