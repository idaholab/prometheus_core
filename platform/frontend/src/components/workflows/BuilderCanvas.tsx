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

import { Minus, Plus } from "lucide-react";
import { Button } from "../ui/Button";
import { ErrorToast } from "../ui/ErrorToast";
import { WorkflowGraph, type WorkflowGraphNode, type WorkflowGraphWire } from "./WorkflowGraph";

interface BuilderCanvasProps {
  nodes: WorkflowGraphNode[];
  wires: WorkflowGraphWire[];
  /** Shown as an error toast in the bottom right, e.g. for an invalid connection (D.6). */
  error?: string;
}

/** D.2's canvas dot grid, from the theme's text colour so it shows in both themes. */
const CANVAS_DOTS =
  "radial-gradient(circle, color-mix(in oklab, var(--color-base-content) 15%, transparent) 1px, transparent 1px)";

/**
 * What an empty canvas shows (Figma D.3): a dashed drop area with an "or"
 * under its hint, then a "Start from template" button below it. Display only:
 * nothing can be dropped on it yet, and the button has no handler.
 */
function EmptyCanvasPrompt() {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-22 pb-10">
      <div className="flex w-60 flex-col items-center gap-1 rounded-md border border-dashed border-base-content/40 px-4 py-2">
        <p className="m-0 text-xs text-base-content">Drag a skill here to begin</p>
        <p className="m-0 font-mono text-[9px] text-base-content/50">or</p>
      </div>
      <button
        type="button"
        className="flex h-25 w-36.5 items-center justify-center rounded-md border border-base-content/15 bg-base-100 text-xs text-base-content transition-colors hover:bg-base-200"
      >
        Start from template
      </button>
    </div>
  );
}

/**
 * Canvas column of the Builder (Figma D.2): the workflow graph at 100% on a
 * dot grid, with a zoom control in the top left. With no nodes it shows the
 * empty-canvas prompt instead (D.3), and with an `error` an error toast in
 * the bottom right (D.6).
 *
 * The graph keeps its D.2 size: the drawing area is at least as big as the
 * D.2 layout, and in a smaller column it scrolls inside the canvas instead of
 * shrinking. The zoom control stays put while it scrolls. Display only: the
 * zoom buttons have no handlers yet, and the graph can't be selected, dragged
 * or connected.
 */
export function BuilderCanvas({ nodes, wires, error }: BuilderCanvasProps) {
  return (
    <div className="relative h-full min-h-130 bg-base-300">
      <div className="absolute inset-0 overflow-auto">
        <div
          className="relative h-full min-h-130 w-full min-w-150 bg-size-[20px_20px]"
          style={{ backgroundImage: CANVAS_DOTS }}
        >
          {nodes.length === 0 ? (
            <EmptyCanvasPrompt />
          ) : (
            <WorkflowGraph
              nodes={nodes}
              wires={wires}
              fit={false}
              className="absolute inset-0 rounded-none border-0 bg-transparent"
            />
          )}
        </div>
      </div>
      <div
        role="group"
        aria-label="Zoom"
        className="absolute top-4 left-4 flex items-center gap-0.5 rounded-md border border-base-content/10 bg-base-200 p-0.5"
      >
        <Button variant="ghost" size="xs" icon={<Minus />} ariaLabel="Zoom out" tooltipPlacement="bottom" />
        <span className="min-w-9 text-center font-mono text-[10px] text-base-content/70">100%</span>
        <Button variant="ghost" size="xs" icon={<Plus />} ariaLabel="Zoom in" tooltipPlacement="bottom" />
      </div>
      {error && <ErrorToast message={error} className="absolute right-5 bottom-5 left-5 sm:left-auto sm:w-69 xl:w-75" />}
    </div>
  );
}
