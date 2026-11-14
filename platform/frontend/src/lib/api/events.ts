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
 * SSE client for `GET /api/events` (decision D2).
 *
 * One `EventSource` per session, opened after auth. The backend frames each event
 * with an `event:` name equal to its `type` discriminator, so we listen per type.
 * `: ping` heartbeats are SSE comments — `EventSource` ignores them automatically —
 * and `EventSource` reconnects on transport drop on its own.
 *
 * `withCredentials: true` sends the auth cookie; without it `/api/events` 401s while
 * plain `fetch` POSTs still work (a subtle cross-origin footgun called out in the
 * backend events audit).
 */

import type { StatusEvent, TaskDoneEvent, TaskProgressEvent, TurnDoneEvent } from "./types";

export interface EventStreamHandlers {
  onStatus?: (e: StatusEvent) => void;
  onTaskProgress?: (e: TaskProgressEvent) => void;
  onTaskDone?: (e: TaskDoneEvent) => void;
  onTurnDone?: (e: TurnDoneEvent) => void;
  /** Fires on the first connect and on every reconnect. */
  onOpen?: () => void;
  /** `closed` distinguishes the two very different things `EventSource` reports
   * as the same `error` event: `false` means it is retrying on its own (a
   * transport blip, a dropped connection) and may recover; `true` means
   * `readyState === CLOSED`, which it only reaches for a non-2xx response — the
   * 401 from an expired session cookie, most often, or the proxy's 5xx while the
   * backend restarts — and from which it never retries. Without this distinction the caller cannot tell "reconnecting" from
   * "dead forever", and a dead stream looks exactly like an idle one. */
  onError?: (info: { closed: boolean; event: Event }) => void;
}

/**
 * Open the session event stream. Returns a `close()` to tear it down (call on
 * logout / unmount). Safe to call once per authenticated session.
 */
export function openEventStream(handlers: EventStreamHandlers): () => void {
  const source = new EventSource("/api/events", { withCredentials: true });

  const parse = <T>(ev: MessageEvent): T | null => {
    try {
      return JSON.parse(ev.data) as T;
    } catch {
      return null;
    }
  };

  const onStatus = (ev: MessageEvent) => {
    const data = parse<StatusEvent>(ev);
    if (data) handlers.onStatus?.(data);
  };
  const onTaskProgress = (ev: MessageEvent) => {
    const data = parse<TaskProgressEvent>(ev);
    if (data) handlers.onTaskProgress?.(data);
  };
  const onTaskDone = (ev: MessageEvent) => {
    const data = parse<TaskDoneEvent>(ev);
    if (data) handlers.onTaskDone?.(data);
  };
  const onTurnDone = (ev: MessageEvent) => {
    const data = parse<TurnDoneEvent>(ev);
    if (data) handlers.onTurnDone?.(data);
  };

  source.addEventListener("status", onStatus as EventListener);
  source.addEventListener("task_progress", onTaskProgress as EventListener);
  source.addEventListener("task_done", onTaskDone as EventListener);
  source.addEventListener("turn_done", onTurnDone as EventListener);
  if (handlers.onOpen) source.addEventListener("open", handlers.onOpen);
  // EventSource fires `error` on transient disconnects too (it auto-reconnects);
  // surface it but don't tear down — let the browser retry. `readyState` is read
  // at dispatch time, which is what tells the two cases apart.
  const onError = (event: Event) => {
    handlers.onError?.({ closed: source.readyState === EventSource.CLOSED, event });
  };
  if (handlers.onError) source.addEventListener("error", onError);

  return () => {
    source.removeEventListener("error", onError);
    source.removeEventListener("status", onStatus as EventListener);
    source.removeEventListener("task_progress", onTaskProgress as EventListener);
    source.removeEventListener("task_done", onTaskDone as EventListener);
    source.removeEventListener("turn_done", onTurnDone as EventListener);
    if (handlers.onOpen) source.removeEventListener("open", handlers.onOpen);
    source.close();
  };
}
