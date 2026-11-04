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

import { Button } from "../ui/Button";
import { SectionLabel } from "../ui/SectionLabel";
import { BuilderCanvas } from "./BuilderCanvas";
import { NodeInspector, type InspectedNode } from "./NodeInspector";
import { SkillLibrary, type SkillGroup } from "./SkillLibrary";
import type { WorkflowGraphNode, WorkflowGraphWire } from "./WorkflowGraph";

interface WorkflowBuilderProps {
  /** Workflow being edited, e.g. "Comprehensive Material Analysis". */
  name: string;
  /** Skills offered in the library column, in display order. */
  skillGroups: SkillGroup[];
  /** The workflow's graph, drawn on the canvas. */
  nodes: WorkflowGraphNode[];
  wires: WorkflowGraphWire[];
  /** The node shown in the inspector, or null for its empty state. */
  inspected: InspectedNode | null;
  /** An error shown as a toast on the canvas, e.g. an invalid connection (D.6). */
  canvasError?: string;
}

/**
 * Workflow Builder shell (Figma D.2): a toolbar with the workflow's name and
 * actions, over three columns: Skill Library, Canvas and Node Inspector.
 *
 * - From lg (1024px) the columns sit side by side, at D.2's widths from xl.
 * - Below lg they stack, library first, and the page scrolls vertically.
 *
 * The toolbar buttons have no handlers yet.
 */
export function WorkflowBuilder({ name, skillGroups, nodes, wires, inspected, canvasError }: WorkflowBuilderProps) {
  return (
    <div className="flex flex-1 flex-col overflow-y-auto lg:overflow-hidden">
      <div className="flex flex-wrap items-center gap-x-9 gap-y-3 border-b border-base-content/10 bg-base-200 px-6 py-3">
        <div className="flex min-w-0 flex-col gap-1">
          <SectionLabel variant="panel">Workflow name</SectionLabel>
          <p className="m-0 text-sm font-semibold text-base-content">{name}</p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Button label="Validate" size="sm" />
          <Button label="Save" size="sm" />
          <Button label="Run Workflow" size="sm" variant="primary" />
        </div>
      </div>

      <div className="grid flex-1 grid-cols-1 lg:min-h-0 lg:grid-cols-[200px_minmax(0,1fr)_240px] xl:grid-cols-[240px_minmax(0,1fr)_280px]">
        <aside
          aria-label="Skill library"
          className="border-b border-base-content/10 bg-base-200 p-4 lg:overflow-y-auto lg:border-r lg:border-b-0"
        >
          <SkillLibrary groups={skillGroups} />
        </aside>

        <section aria-label="Canvas" className="min-w-0 lg:min-h-0">
          <BuilderCanvas nodes={nodes} wires={wires} error={canvasError} />
        </section>

        <aside
          aria-label="Node inspector"
          className="border-t border-base-content/10 bg-base-200 p-4 lg:overflow-y-auto lg:border-t-0 lg:border-l"
        >
          <NodeInspector node={inspected} />
        </aside>
      </div>
    </div>
  );
}
