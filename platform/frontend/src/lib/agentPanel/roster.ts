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
 * Live agent panel — how a status-line name becomes an agent on stage.
 *
 * The panel does NOT read a structured active_agent/edge field off the wire. It parses
 * the verbatim client-agent status strings the backend already emits over SSE
 * (`StatusEvent.message`, accumulated in a ToolItem's `history`). The orchestrator
 * names the SKILL it dispatches (`Invoking '<skill>'.`), so the roster is keyed by
 * skill id and is open-ended: any skill the loop names gets an agent, labelled with a
 * friendly name when one is known and with the skill id otherwise. No contract change;
 * a reworded status string needs `parseAgentStream` kept in step.
 */

/** The orchestrator, or the id of a skill the run has named. */
export type AgentId = string;

export const PLANNER: AgentId = "planner";

/**
 * Pseudo-agent for the okflow pipeline runner. It is never dispatched by the
 * orchestrator directly (the UQ agent calls it), so it is revealed by the UQ agent's
 * own progress lines rather than by an `Invoking` line.
 */
export const RUNNER: AgentId = "okflow_runner";

export interface AgentDef {
  name: string;
  role: string;
  /** Role color; daisyui-independent so the connector and glow can use it directly. */
  color: string;
}

/** Friendlier labels and fixed colors for agents the platform ships with. Cosmetic only. */
const KNOWN_AGENTS: Record<AgentId, AgentDef> = {
  [PLANNER]: { name: "Planner", role: "client-agent", color: "#6aa9ff" },
  forward_sampling_uq: { name: "UQ agent", role: "forward_sampling_uq", color: "#ff6b8a" },
  [RUNNER]: { name: "okflow runner", role: "HPC pipelines", color: "#b388ff" },
};

/** Stable hue per skill id, so an unknown agent keeps its color across turns. */
function colorFor(id: string): string {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  // Keep clear of the planner's blue band (roughly 200-230).
  const hue = (240 + (h % 320)) % 360;
  return `hsl(${hue} 70% 64%)`;
}

export function agentDef(id: AgentId): AgentDef {
  return KNOWN_AGENTS[id] ?? { name: id, role: id, color: colorFor(id) };
}
