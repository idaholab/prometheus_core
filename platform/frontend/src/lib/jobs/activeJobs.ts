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
 */

import type { TaskNode } from "../api/types.ts";

/** A task that has not reached a terminal state. */
export const RUNNING_STATES = new Set(["submitted", "working", "input-required"]);

export interface JobLink {
  label: string;
  url: string;
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
const PIPELINE_RE = /\/-\/pipelines\/(\d+)/;

/** Every URL in `text`, labelled ("GitLab pipeline 123" for GitLab pipeline URLs), deduped. */
export function extractLinks(text: string | null | undefined): JobLink[] {
  const seen = new Set<string>();
  const links: JobLink[] = [];
  for (const raw of (text ?? "").match(URL_RE) ?? []) {
    const url = raw.replace(/[.,;:]+$/, "");
    if (seen.has(url)) continue;
    seen.add(url);
    const pipeline = PIPELINE_RE.exec(url);
    links.push({ label: pipeline ? `GitLab pipeline ${pipeline[1]}` : url, url });
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
export function toJobRows(tasks: TaskNode[], history: Map<string, string[]> = new Map()): JobRow[] {
  const rows: JobRow[] = [];
  const visit = (node: TaskNode, turnTitle: string, depth: number) => {
    const children = node.children ?? [];
    if (depth > 0 || children.length === 0) {
      const seen = [...(history.get(node.task_id) ?? []), node.last_status_message ?? ""];
      const links = extractLinks(seen.join("\n"));
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
export function recordStatusHistory(tasks: TaskNode[], history: Map<string, string[]>): Map<string, string[]> {
  const walk = (node: TaskNode) => {
    const msg = node.last_status_message;
    if (msg) {
      const seen = history.get(node.task_id) ?? [];
      if (seen[seen.length - 1] !== msg) history.set(node.task_id, [...seen, msg].slice(-50));
    }
    for (const child of node.children ?? []) walk(child);
  };
  for (const root of tasks) walk(root);
  return history;
}
