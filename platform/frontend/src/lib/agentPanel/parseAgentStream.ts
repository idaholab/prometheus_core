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
 * parseAgentStream — turn the verbatim client-agent status log into the live-panel view
 * state: which agents are on stage, which one is "now", the active A2A edge, docked
 * artifacts, each agent's outcome, and the collapsed per-sample pipeline badge.
 *
 * Input is the accumulated status `history` for one turn (StatusEvent.message lines,
 * oldest first) — exactly the strings the chat already shows in ToolStep. PURE and
 * string-only so it can be unit-tested against the real anchors without React.
 *
 * Anchors (verbatim strings from agents/client-agent/orchestrator):
 *   - `Next step: '<skill>'.` / `Invoking '<skill>'.`      -> reveal <skill>, planner -> skill
 *   - `[<skill>] <progress>`                               -> <skill> is working
 *   - `[<skill>] Pipeline <id>: <state>`                   -> reveal the okflow runner, track <id>
 *   - `[<skill>] Running okflow ...: <i>/<n> cases complete` -> runner loop badge xN, i done
 *   - `'<skill>' completed.`                               -> <skill> done, report docks
 *   - `'<skill>' failed: <error>` / `Capability '<skill>' is currently unavailable.`
 *                                                          -> <skill> failed (red), error kept
 *   - `Response ready.` (and the other final lines)        -> turn complete, nothing active
 *
 * Per-sample pipeline ticks are COLLAPSED into one badge on the runner, never one row
 * per sample.
 */

import { PLANNER, RUNNER, type AgentId } from "./roster.ts";

export interface EdgeState {
  from: AgentId;
  to: AgentId;
  /** "down" = request flowing toward the callee; "up" = results flowing back. */
  dir: "down" | "up";
  label: string;
}

export interface FileState {
  id: string;
  at: AgentId;
  label: string;
  /** true = clickable artifact (opens the rendered report). */
  click: boolean;
  /** the artifact id, when known, so the component can build a same-origin open URL. */
  artifactId?: string;
}

export interface LoopState {
  at: AgentId;
  /** total cases (samples) in the run. */
  n: number;
  /** cases finished so far. */
  completed: number;
  done: boolean;
}

export type AgentOutcome = "working" | "done" | "failed";

export interface AgentStatus {
  outcome: AgentOutcome;
  /** for a failure: the error text from the status line. */
  error?: string;
  /** for a failure that looks like a connectivity problem rather than a task error. */
  unreachable?: boolean;
}

export interface PipelineState {
  id: string;
  state: string;
}

export interface PanelState {
  /** agents named so far, in order of first appearance; once revealed they stay. */
  revealed: AgentId[];
  /** the agent that is "now" (motion-only glow). null when the turn is complete/idle. */
  active: AgentId | null;
  /** the single edge streaming right now, or null. */
  edge: EdgeState | null;
  /** every artifact docked so far; newest last. */
  files: FileState[];
  /** loop badges by agent (collapsed per-sample loop). */
  loops: Record<AgentId, LoopState>;
  /** per-agent outcome; absent until the agent has done something. */
  status: Record<AgentId, AgentStatus>;
  /** HPC pipelines named by `Pipeline <id>: <state>` lines, latest state each. */
  pipelines: PipelineState[];
  /** true once the turn's final line has been seen. */
  complete: boolean;
}

const RE_NEXT = /^Next step: '([^']+)'\.?$/;
const RE_ROUTING = /Routing decision:.*capability '([^']+)'/;
const RE_INVOKING = /^Invoking '([^']+)'\.?$/;
const RE_PROGRESS = /^\[([^\]]+)\]\s+(.*)$/;
const RE_COMPLETED = /^'([^']+)' completed\.$/;
const RE_FAILED = /^'([^']+)' failed:\s*(.*)$/;
const RE_UNAVAILABLE = /^Capability '([^']+)' is currently unavailable\.$/;
const RE_PIPELINE = /^Pipeline (\d+):\s*([a-z_]+)/i;
const RE_OKFLOW_PROGRESS = /^Running okflow\b.*?(\d+)\s*\/\s*(\d+)\s+cases?\b/i;
const RE_OKFLOW_TOTAL = /^Running okflow\b.*?\((\d+)\s+cases?\)/i;
const RE_TURN_DONE =
  /^(Response ready\.|Awaiting additional information\.|Plan ready for approval\.|Plan rejected by user\.|Background task complete\.)$/;
/** Errors that mean "could not talk to the agent" rather than "the agent said no". */
const RE_UNREACHABLE =
  /could not be reached|unreachable|connect(ion)? (refused|error|failed)|ConnectError|ConnectTimeout|Network communication error|Name or service not known|nodename nor servname|currently unavailable/i;
const PIPELINE_DONE = new Set(["success", "failed", "canceled", "skipped"]);

export function parseAgentStream(history: string[]): PanelState {
  const revealed: AgentId[] = [];
  const status: Record<AgentId, AgentStatus> = {};
  const files: FileState[] = [];
  const loops: Record<AgentId, LoopState> = {};
  const pipelines = new Map<string, string>();
  let active: AgentId | null = null;
  let edge: EdgeState | null = null;
  let complete = false;

  const reveal = (id: AgentId) => {
    if (!revealed.includes(id)) revealed.push(id);
  };
  const dockReport = (at: AgentId) => {
    if (!files.some((f) => f.id === `report:${at}`)) {
      files.push({ id: `report:${at}`, at, label: "report", click: true });
    }
  };
  const runnerLoop = (): LoopState => (loops[RUNNER] ??= { at: RUNNER, n: 0, completed: 0, done: false });

  const lines = (history ?? []).filter((l) => typeof l === "string" && l.trim().length > 0);
  if (lines.length > 0) reveal(PLANNER);

  for (const raw of lines) {
    const line = raw.trim();
    let m: RegExpMatchArray | null;

    if ((m = line.match(RE_NEXT) ?? line.match(RE_ROUTING) ?? line.match(RE_INVOKING))) {
      const skill = m[1];
      reveal(skill);
      status[skill] = { outcome: "working" };
      active = RE_INVOKING.test(line) ? skill : PLANNER;
      edge = { from: PLANNER, to: skill, dir: "down", label: "A2A" };
      complete = false;
      continue;
    }

    if ((m = line.match(RE_PROGRESS))) {
      const [, skill, text] = m;
      reveal(skill);
      status[skill] ??= { outcome: "working" };
      let p: RegExpMatchArray | null;
      if ((p = text.match(RE_PIPELINE))) {
        reveal(RUNNER);
        status[RUNNER] = { outcome: "working" };
        pipelines.set(p[1], p[2].toLowerCase());
        const loop = runnerLoop();
        loop.n = Math.max(loop.n, pipelines.size);
        active = RUNNER;
        edge = { from: skill, to: RUNNER, dir: "down", label: "pipelines" };
      } else if ((p = text.match(RE_OKFLOW_PROGRESS))) {
        reveal(RUNNER);
        const loop = runnerLoop();
        loop.completed = Number(p[1]) || 0;
        loop.n = Math.max(loop.n, Number(p[2]) || 0);
        loop.done = loop.n > 0 && loop.completed >= loop.n;
        if (loop.done) {
          status[RUNNER] = { outcome: "done" };
          active = skill;
          edge = { from: RUNNER, to: skill, dir: "up", label: "results" };
        } else {
          active = RUNNER;
          edge = { from: skill, to: RUNNER, dir: "down", label: "pipelines" };
        }
      } else if ((p = text.match(RE_OKFLOW_TOTAL))) {
        reveal(RUNNER);
        status[RUNNER] = { outcome: "working" };
        const loop = runnerLoop();
        loop.n = Math.max(loop.n, Number(p[1]) || 0);
        active = RUNNER;
        edge = { from: skill, to: RUNNER, dir: "down", label: "pipelines" };
      } else {
        active = skill;
        if (!edge || (edge.to !== skill && edge.from !== skill)) {
          edge = { from: PLANNER, to: skill, dir: "down", label: "A2A" };
        }
      }
      complete = false;
      continue;
    }

    if ((m = line.match(RE_COMPLETED))) {
      const skill = m[1];
      reveal(skill);
      status[skill] = { outcome: "done" };
      dockReport(skill);
      if (loops[RUNNER]) {
        loops[RUNNER] = { ...loops[RUNNER], done: true };
        if (status[RUNNER]?.outcome === "working") status[RUNNER] = { outcome: "done" };
      }
      active = PLANNER;
      edge = { from: skill, to: PLANNER, dir: "up", label: "result" };
      continue;
    }

    if ((m = line.match(RE_FAILED) ?? line.match(RE_UNAVAILABLE))) {
      const skill = m[1];
      const error = (m[2] ?? "capability is currently unavailable").trim();
      reveal(skill);
      status[skill] = { outcome: "failed", error, unreachable: RE_UNREACHABLE.test(line) };
      active = PLANNER;
      edge = null;
      continue;
    }

    if (RE_TURN_DONE.test(line)) {
      active = null;
      edge = null;
      complete = true;
      continue;
    }

    // Any other line (e.g. "Deciding the next step."): the orchestrator is working.
    if (!complete) active = PLANNER;
  }

  if (loops[RUNNER]) {
    const states = [...pipelines.values()];
    if (states.length > 0) {
      const finished = states.filter((s) => PIPELINE_DONE.has(s)).length;
      loops[RUNNER].completed = Math.max(loops[RUNNER].completed, finished);
      if (states.some((s) => s === "failed")) {
        status[RUNNER] = { outcome: "failed", error: "a pipeline failed" };
      }
    }
  }
  if (edge && (!revealed.includes(edge.from) || !revealed.includes(edge.to))) edge = null;

  return {
    revealed,
    active: active && revealed.includes(active) ? active : null,
    edge,
    files,
    loops,
    status,
    pipelines: [...pipelines].map(([id, state]) => ({ id, state })),
    complete,
  };
}
