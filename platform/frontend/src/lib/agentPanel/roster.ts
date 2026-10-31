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
 * friendly name when one is known and with the skill id otherwise. No wire change; the
 * status-line formats are pinned by `statusLines.fixture.json`, which both the
 * frontend and the client-agent test against.
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
  /** Role color: a daisyUI theme token (`var(--color-*)`), so it follows the light and
   * dark themes. The panel uses it directly as the connector, glow and glyph color. */
  color: string;
}

const token = (name: string) => `var(--color-${name})`;

/**
 * The theme tokens agents are drawn in. `error` is kept for a failed agent and
 * `accent` is left out (near-black in this theme), so every role color reads on the
 * base background in both themes.
 */
const ROLE_TOKENS = ["info", "warning", "success", "secondary", "primary"].map(token);

/** Friendlier labels and fixed colors for agents the platform ships with. Cosmetic only. */
const KNOWN_AGENTS: Record<AgentId, AgentDef> = {
  [PLANNER]: { name: "Planner", role: "client-agent", color: token("info") },
  forward_sampling_uq: { name: "UQ agent", role: "forward_sampling_uq", color: token("warning") },
  [RUNNER]: { name: "okflow runner", role: "HPC pipelines", color: token("success") },
  "okflow-config-agent": { name: "okflow config", role: "pipeline config", color: token("secondary") },
};

/** "okflow-config-agent" -> "okflow config"; a skill id is shown as-is. */
function friendlyName(id: AgentId): string {
  return id.endsWith("-agent") ? id.slice(0, -"-agent".length).replace(/-/g, " ") : id;
}

/** A stable theme token per skill id, so an unknown agent keeps its color across turns. */
function colorFor(id: string): string {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return ROLE_TOKENS[h % ROLE_TOKENS.length];
}

/** Any agent not listed above gets a readable name and its own stable color. */
export function agentDef(id: AgentId): AgentDef {
  return KNOWN_AGENTS[id] ?? { name: friendlyName(id), role: id, color: colorFor(id) };
}
