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

import { BaseEdge, EdgeLabelRenderer, getBezierPath, type Edge, type EdgeProps } from "@xyflow/react";
import { Plus } from "lucide-react";
import { SKILL_TONE_DOT_CLASSES, type SkillTone } from "./skillTone";

export interface WireData extends Record<string, unknown> {
  dashed?: boolean;
  /** A connection of the wrong type (D.6): drawn dashed in red. */
  invalid?: boolean;
  /** Shows the "+" insert button at the wire's midpoint, with its menu open (D.5). */
  insertMenu?: boolean;
}

export type WireEdge = Edge<WireData, "wire">;

const INSERT_OPTIONS: { label: string; tone: SkillTone }[] = [
  { label: "Insert skill node", tone: "analysis" },
  { label: "Insert checkpoint", tone: "control" },
  { label: "Insert QA gate", tone: "control" },
];

/**
 * The insert menu beside a wire's "+" (Figma D.5): one item per kind of step
 * that can be inserted, each with its dot. Display only: the items have no
 * handlers yet. The first is highlighted, as in D.5.
 */
function InsertMenu() {
  return (
    <ul
      role="menu"
      aria-label="Insert on wire"
      className="m-0 flex w-47 list-none flex-col gap-0.5 rounded-lg border border-base-content/15 bg-base-200 p-1.5 shadow-lg"
    >
      {INSERT_OPTIONS.map(({ label, tone }, i) => (
        <li key={label} role="none">
          <button
            type="button"
            role="menuitem"
            className={`flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-xs text-base-content hover:bg-base-content/10 ${
              i === 0 ? "bg-base-content/10" : ""
            }`}
          >
            <span aria-hidden="true" className={`size-1.5 shrink-0 rounded-full ${SKILL_TONE_DOT_CLASSES[tone]}`} />
            {label}
          </button>
        </li>
      ))}
    </ul>
  );
}

/**
 * A wire between two steps: a curve in the primary colour, dashed when
 * `dashed`, dashed in red when `invalid` (D.6). With `insertMenu` it carries a
 * "+" at its midpoint and the insert menu to the right (D.5).
 */
export function WorkflowWire({
  sourceX,
  sourceY,
  sourcePosition,
  targetX,
  targetY,
  targetPosition,
  data,
}: EdgeProps<WireEdge>) {
  const [path, midX, midY] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  const dashed = data?.dashed || data?.invalid;
  const style = {
    ...(dashed ? { strokeDasharray: "5 4" } : {}),
    ...(data?.invalid ? { stroke: "var(--color-error)" } : {}),
  };

  return (
    <>
      <BaseEdge path={path} style={style} />
      {data?.insertMenu && (
        <EdgeLabelRenderer>
          {/* The label layer ignores the pointer, so turn it back on here. */}
          <div
            className="pointer-events-auto absolute flex items-start gap-4"
            style={{ transform: `translate(-10px, -10px) translate(${midX}px, ${midY}px)` }}
          >
            <button
              type="button"
              aria-label="Insert on wire"
              aria-haspopup="menu"
              aria-expanded="true"
              className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary text-primary-content"
            >
              <Plus size={12} strokeWidth={2.5} aria-hidden="true" />
            </button>
            <div className="-mt-6">
              <InsertMenu />
            </div>
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
