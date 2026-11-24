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

import type { CSSProperties } from "react";
import { getBezierPath, type GetBezierPathParams } from "@xyflow/react";
import type { GraphEdgeKind } from "@/lib/api/types";

export interface WireData extends Record<string, unknown> {
  dashed?: boolean;
  /** A connection of the wrong type (D.6): drawn dashed in red. */
  invalid?: boolean;
  /** Shows the "+" insert button at the wire's midpoint, with its menu open (D.5). */
  insertMenu?: boolean;
  /**
   * `order`: the target only runs after the source and reads no data; drawn dotted.
   * Unset or `data` draws a solid wire.
   */
  kind?: GraphEdgeKind;
}

/** A wire still being connected (D.2), and the dash of an invalid one (D.6). */
const DASHED_STYLE: CSSProperties = { strokeDasharray: "5 4" };

/** An order wire: round dots in a muted primary, so it reads apart from a dashed wire. */
const ORDER_STYLE: CSSProperties = {
  strokeDasharray: "2 4",
  strokeLinecap: "round",
  stroke: "color-mix(in oklab, var(--color-primary) 55%, transparent)",
};

/**
 * The stroke of a wire, first match wins: `invalid` is dashed in red, `dashed`
 * is dashed ("5 4"), an `order` wire is dotted ("2 4") in a muted primary, and
 * any other wire is solid in the primary colour React Flow draws by default.
 */
export function wireStyle(data: WireData | undefined): CSSProperties {
  if (data?.invalid) return { ...DASHED_STYLE, stroke: "var(--color-error)" };
  if (data?.dashed) return DASHED_STYLE;
  if (data?.kind === "order") return ORDER_STYLE;
  return {};
}

/**
 * Height in px between a straight-down wire's ends above which it skips a row.
 * Rows are 170px apart in the Console and the D.1 nodes are 42-98px tall, so a
 * wire to the next row spans 72-128px (152px on the D.5 Builder canvas), and a
 * wire across two rows spans at least 242px.
 */
const SKIP_ROW_SPAN = 200;

/**
 * Sideways shift in px of both control points of a bowed wire. The curve's x
 * offset is 3t(1-t) of it, so between two 78px template nodes it passes the
 * skipped row 102-112px from the column's centre: clear of the 200px-wide node
 * there, and short of the next column, whose node starts 120px away.
 */
const BOW_OFFSET = 150;

/**
 * The SVG path of a wire, and its label point. A wire that runs straight down
 * past a row would lie over the wire into that row's node and behind the node,
 * so it bows to the right instead; any other wire is React Flow's bezier.
 */
export function wirePath(params: GetBezierPathParams): [path: string, labelX: number, labelY: number] {
  const { sourceX, sourceY, targetX, targetY } = params;
  const span = targetY - sourceY;
  if (Math.abs(sourceX - targetX) >= 1 || span <= SKIP_ROW_SPAN) {
    const [path, labelX, labelY] = getBezierPath(params);
    return [path, labelX, labelY];
  }
  const bowX = sourceX + BOW_OFFSET;
  const path = `M${sourceX},${sourceY} C${bowX},${sourceY + span / 3} ${bowX},${targetY - span / 3} ${targetX},${targetY}`;
  // The curve's point at t = 0.5.
  return [path, sourceX + 0.75 * BOW_OFFSET, sourceY + span / 2];
}
