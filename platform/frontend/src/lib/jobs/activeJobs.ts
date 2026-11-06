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
 * Turns the conversation's Task Graph (`GET /api/conversations/{id}/tasks`) into
 * the rows of the status panel's Active Jobs tab: one row per specialist skill
 * dispatch, newest turn first, with any solver-pipeline links found in its
 * status messages.
 *
 * Only GitLab pipeline URLs (`https://<host>/<group>/<project>/-/pipelines/<id>`)
 * become links. Status text is free-form agent output, so any other URL in it
 * stays plain text rather than a clickable card.
 */

import type { TaskNode } from "../api/types.ts";

/** A task that has not reached a terminal state. */
export const RUNNING_STATES = new Set([
  "submitted",
  "working",
  "input-required",
]);

export interface JobLink {
  label: string;
  url: string;
  /** GitLab pipeline id, when the URL is a pipeline page. */
  pipelineId?: string;
  /** Latest state reported for that pipeline ("running", "failed", ...), if any. */
  state?: string;
}

export interface JobRow {
  taskId: string;
  /** The dispatched skill, or the turn's title for a root with no skill. */
  name: string;
  /** The chat turn this dispatch belongs to. */
  turnTitle: string;
  state: string;
  running: boolean;
  message: string;
  error: string | null;
  updatedAt: string | null;
  links: JobLink[];
  depth: number;
}

const URL_RE = /https?:\/\/[^\s"'<>)\]]+/g;
/** A GitLab pipeline page: `/-/pipelines/<id>` ending the path (no query or fragment). */
const PIPELINE_RE = /^https?:\/\/[^/\s]+\/[^\s?#]+\/-\/pipelines\/(\d+)\/?$/;
const PIPELINE_STATE_RE = /Pipeline (\d+):\s*([a-z_]+)\s*$/gim;

/** Latest reported state per pipeline id, from "Pipeline <id>: <state>" status lines. */
export function pipelineStates(text: string): Map<string, string> {
  const states = new Map<string, string>();
  for (const m of text.matchAll(PIPELINE_STATE_RE))
    states.set(m[1], m[2].toLowerCase());
  return states;
}

/** Every GitLab pipeline URL in `text`, labelled "GitLab pipeline <id>", deduped.
 * Any other URL is ignored: only pipeline pages become clickable. */
export function extractLinks(text: string | null | undefined): JobLink[] {
  const seen = new Set<string>();
  const links: JobLink[] = [];
  for (const raw of (text ?? "").match(URL_RE) ?? []) {
    const url = raw.replace(/[.,;:]+$/, "");
    const pipeline = PIPELINE_RE.exec(url);
    if (!pipeline || seen.has(url)) continue;
    seen.add(url);
    links.push({ label: `GitLab pipeline ${pipeline[1]}`, url, pipelineId: pipeline[1] });
  }
  return links;
}

/**
 * Flatten the task tree into job rows. Roots are chat turns; their descendants are
 * the dispatches that do the work, so a root becomes a row only when it has no
 * children. `history` maps a task id to every status message seen for it (the
 * Task Graph keeps only the latest), so a link reported early, such as a pipeline
 * URL at start, stays visible after later progress messages replace it.
 */
export function toJobRows(
  tasks: TaskNode[],
  history: Map<string, string[]> = new Map(),
): JobRow[] {
  const rows: JobRow[] = [];
  const visit = (node: TaskNode, turnTitle: string, depth: number) => {
    const children = node.children;
    if (depth > 0 || children.length === 0) {
      const seen = [
        ...(history.get(node.task_id) ?? []),
        node.last_status_message ?? "",
      ];
      const text = seen.join("\n");
      const states = pipelineStates(text);
      // Failed pipelines first: the one to open is usually the one that broke.
      const links = extractLinks(text)
        .map((link) =>
          link.pipelineId && states.has(link.pipelineId)
            ? { ...link, state: states.get(link.pipelineId) }
            : link,
        )
        .sort(
          (a, b) => Number(b.state === "failed") - Number(a.state === "failed"),
        );
      rows.push({
        taskId: node.task_id,
        name: node.skill || node.title || "task",
        turnTitle,
        state: node.state,
        running: RUNNING_STATES.has(node.state),
        message: node.last_status_message ?? "",
        error: node.error,
        updatedAt: node.updated_at,
        links,
        depth,
      });
    }
    for (const child of children) visit(child, turnTitle, depth + 1);
  };
  for (const root of tasks) visit(root, root.title, 0);
  return rows;
}

/** Fold the latest status message of every task into `history` (mutates and returns it). */
export function recordStatusHistory(
  tasks: TaskNode[],
  history: Map<string, string[]>,
): Map<string, string[]> {
  const walk = (node: TaskNode) => {
    const msg = node.last_status_message;
    if (msg) {
      const seen = history.get(node.task_id) ?? [];
      if (seen[seen.length - 1] !== msg)
        history.set(node.task_id, [...seen, msg].slice(-500));
    }
    for (const child of node.children) walk(child);
  };
  for (const root of tasks) walk(root);
  return history;
}

/** How many conversations keep their status history at once (oldest dropped first). */
const MAX_HISTORIES = 20;
const histories = new Map<string, Map<string, string[]>>();

/**
 * The status history (task id -> every status message seen) for one conversation.
 * It lives at module level, not in the Active Jobs component, so a link reported
 * early (a pipeline URL at start) survives the tab being switched away and back,
 * which unmounts the panel. Bounded to the most recently used conversations.
 */
export function historyFor(conversationId: string): Map<string, string[]> {
  let history = histories.get(conversationId);
  if (history) {
    histories.delete(conversationId); // re-insert: most recently used last
  } else {
    history = new Map();
    while (histories.size >= MAX_HISTORIES) histories.delete(histories.keys().next().value as string);
  }
  histories.set(conversationId, history);
  return history;
}

/** Drop every conversation's status history (tests). */
export function resetHistories(): void {
  histories.clear();
}
