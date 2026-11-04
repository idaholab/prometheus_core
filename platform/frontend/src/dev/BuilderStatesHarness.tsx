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
 * Dev-only review page for the Workflow Builder's states that nothing can
 * reach by clicking yet: the empty canvas (Figma D.3) and a skill being
 * dragged onto it (D.4), plus the base state (D.2) to compare against. Each
 * is the real WorkflowBuilder, with a theme toggle. It also covers the Node
 * Inspector's two states: selected in D.2 and D.4, empty in D.3.
 *
 * Open http://localhost:5150/?harness=builder-states under `npm run dev`.
 * main.tsx loads this only in dev, so it never reaches the production build.
 */
import { useState } from "react";
import type { InspectedNode } from "../components/workflows/NodeInspector";
import { WorkflowBuilder } from "../components/workflows/WorkflowBuilder";
import type { WorkflowGraphNode, WorkflowGraphWire } from "../components/workflows/WorkflowGraph";
import { useTheme } from "../lib/useTheme";
import {
  BUILDER_NODES,
  BUILDER_WIRES,
  DRAGGING_NODES,
  INSPECTED_NODE,
  SKILL_GROUPS,
} from "../pages/builderPlaceholders";

type StateId = "base" | "empty" | "dragging";

interface BuilderState {
  label: string;
  nodes: WorkflowGraphNode[];
  wires: WorkflowGraphWire[];
  inspected: InspectedNode | null;
}

const STATES: Record<StateId, BuilderState> = {
  base: { label: "Base (D.2)", nodes: BUILDER_NODES, wires: BUILDER_WIRES, inspected: INSPECTED_NODE },
  empty: { label: "Empty canvas (D.3)", nodes: [], wires: [], inspected: null },
  dragging: { label: "Dragging skill (D.4)", nodes: DRAGGING_NODES, wires: [], inspected: INSPECTED_NODE },
};

export function BuilderStatesHarness() {
  const [theme, setTheme] = useTheme();
  const [stateId, setStateId] = useState<StateId>("empty");
  const state = STATES[stateId];

  return (
    <div className="flex h-screen flex-col bg-base-100 text-base-content">
      <div className="flex flex-wrap items-center gap-3 border-b border-base-content/10 px-6 py-3">
        <h1 className="m-0 mr-2 text-sm font-bold">Builder states (dev)</h1>
        {(Object.keys(STATES) as StateId[]).map((id) => (
          <button
            key={id}
            type="button"
            className={`btn btn-sm ${id === stateId ? "btn-primary" : ""}`}
            aria-pressed={id === stateId}
            onClick={() => setStateId(id)}
          >
            {STATES[id].label}
          </button>
        ))}
        <button type="button" className="btn btn-sm ml-auto" onClick={() => setTheme(theme === "light" ? "dark" : "light")}>
          {theme === "light" ? "Dark theme" : "Light theme"}
        </button>
      </div>
      {/* Keyed so each state mounts fresh, as it would on the Builder page. */}
      <WorkflowBuilder
        key={stateId}
        name="Comprehensive Material Analysis"
        skillGroups={SKILL_GROUPS}
        nodes={state.nodes}
        wires={state.wires}
        inspected={state.inspected}
      />
    </div>
  );
}
