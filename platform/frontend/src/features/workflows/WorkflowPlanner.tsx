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

import { Button } from "@/components/ui/Button";
import { SectionLabel } from "@/components/ui/SectionLabel";
import { WorkflowGraph, type WorkflowGraphNode, type WorkflowGraphWire } from "./WorkflowGraph";

export interface WorkflowPlan {
  /** Breadcrumb above the graph, e.g. ["Chat", "Workflow Plan", "comprehensive_material_analysis"]. */
  path: string[];
  /** Orchestrator state shown opposite the path, e.g. "Orchestrator: Active | Mode: DAG". */
  status: string;
  nodes: WorkflowGraphNode[];
  wires: WorkflowGraphWire[];
  agents: number;
  /** Display string, e.g. "3hr 40s". */
  pipelineTime: string;
  /** Display string, e.g. "2 Active". */
  checkpoints: string;
  inputs: string[];
  outputs: string[];
}

/** Sizes go on each element: the base layer sets span and li font-size, so it isn't inherited. */
function FileList({ label, files }: { label: string; files: string[] }) {
  return (
    <div className="flex flex-col gap-2">
      <SectionLabel as="h3">{label}</SectionLabel>
      <ul className="m-0 flex list-none flex-col gap-1 p-0">
        {files.map((file) => (
          <li key={file} className="break-all text-[11px] leading-4 text-base-content">
            • {file}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Workflow Execution Planner (Figma D.1): the plan's path, its summary and
 * actions, and its graph.
 *
 * - From xl (1280px), as in D.1: the graph on the left, the summary in a column
 *   on the right.
 * - Below xl the summary moves between the path and the graph, as a compact
 *   band (columns from md), so the totals and actions sit above the tall graph
 *   and the graph gets the panel's full width.
 * - Below lg (1024px) the graph keeps its D.1 size and scrolls sideways in its
 *   own area instead of shrinking to fit.
 *
 * DOM order follows the stacked order. "Modify Plan" calls `onModifyPlan`;
 * "Approve & Execute Pipeline" has no handler yet.
 */
export function WorkflowPlanner({ plan, onModifyPlan }: { plan: WorkflowPlan; onModifyPlan?: () => void }) {
  return (
    <div className="grid grid-cols-1 overflow-hidden rounded-lg border border-base-content/10 bg-base-200 xl:grid-cols-[minmax(0,1fr)_340px] xl:grid-rows-[auto_1fr]">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-5 py-5 uppercase xl:col-start-1 xl:row-start-1 xl:pb-4">
        {/* Segments wrap at the slashes, never mid-word. */}
        <span className="flex min-w-0 flex-wrap gap-x-1.5">
          {plan.path.map((segment, i) => (
            <span key={segment} className="break-all text-[10px] leading-3 tracking-widest text-primary">
              {i > 0 && "/ "}
              {segment}
            </span>
          ))}
        </span>
        <span className="text-[10px] leading-3 text-base-content/50">{plan.status}</span>
      </div>

      <aside className="flex flex-col gap-5 border-y border-base-content/10 p-5 md:grid md:grid-cols-3 md:items-start md:gap-x-10 xl:col-start-2 xl:row-span-2 xl:row-start-1 xl:flex xl:items-stretch xl:border-y-0 xl:border-l xl:p-6">
        <div className="flex flex-col gap-2.5">
          <SectionLabel as="h3">Plan Summary</SectionLabel>
          <dl className="m-0 flex flex-col gap-2 text-[13px]">
            <div className="flex justify-between gap-2">
              <dt className="text-base-content/60">Total Agents Involved</dt>
              <dd className="m-0 text-base-content">
                {plan.agents} {plan.agents === 1 ? "Agent" : "Agents"}
              </dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-base-content/60">Pipeline Time</dt>
              <dd className="m-0 text-primary">{plan.pipelineTime}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-base-content/60">Checkpoints</dt>
              <dd className="m-0 text-primary">{plan.checkpoints}</dd>
            </div>
          </dl>
        </div>
        <FileList label="Input Requirements" files={plan.inputs} />
        <FileList label="Expected Outputs" files={plan.outputs} />
        <div className="grid gap-2.5 md:col-span-3 md:grid-cols-2 xl:grid-cols-1 xl:pt-5">
          <Button label="Approve & Execute Pipeline" variant="primary" wide />
          <Button label="Modify Plan" outline wide onClick={onModifyPlan} />
        </div>
      </aside>

      <div className="overflow-x-auto p-5 xl:col-start-1 xl:row-start-2 xl:pt-0">
        <WorkflowGraph
          nodes={plan.nodes}
          wires={plan.wires}
          className="h-157 w-full min-w-193 lg:min-w-0"
        />
      </div>
    </div>
  );
}
