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

/* A workflow wire MUST draw an order edge dotted, distinct from a data edge, with
 * invalid > dashed > order > solid, and MUST bow a layer-skipping wire in one column
 * so it does not cover the wire to the middle node. */
import { getBezierPath, Position, type GetBezierPathParams } from "@xyflow/react";
import { describe, expect, test } from "vitest";

import { wirePath, wireStyle } from "./wireStyle.ts";

/** A wire from a node's bottom handle to another node's top handle. */
function wire(sourceX: number, sourceY: number, targetX: number, targetY: number): GetBezierPathParams {
  return {
    sourceX,
    sourceY,
    sourcePosition: Position.Bottom,
    targetX,
    targetY,
    targetPosition: Position.Top,
  };
}

describe("wire_style", () => {
  test("an unset or data wire is solid", () => {
    expect(wireStyle(undefined)).toEqual({});
    expect(wireStyle({ kind: "data" })).toEqual({});
  });

  test("an order wire is dotted", () => {
    expect(wireStyle({ kind: "order" }).strokeDasharray).toBe("2 4");
  });

  test("a dashed order wire is dashed, without the muted order stroke", () => {
    const style = wireStyle({ kind: "order", dashed: true });

    expect(style.strokeDasharray).toBe("5 4");
    expect(style.stroke).toBeUndefined();
  });

  test("an invalid wire is dashed in red over dashed and order", () => {
    const style = wireStyle({ kind: "order", dashed: true, invalid: true });

    expect(style.strokeDasharray).toBe("5 4");
    expect(style.stroke).toBe("var(--color-error)");
  });

  test("wirePath bows a straight-down wire that skips a row and keeps every other wire a bezier", () => {
    // The seed's e4 wire runs straight down from the first row past the second.
    const skip = wire(320, 78, 320, 340);
    const [path, labelX] = wirePath(skip);

    expect(path).not.toBe(getBezierPath(skip)[0]);
    // Clear of the half-width of the 200px node in the skipped row.
    expect(labelX).toBeGreaterThan(320 + 100);

    const adjacent = wire(320, 78, 320, 170);
    expect(wirePath(adjacent)).toEqual(getBezierPath(adjacent).slice(0, 3));

    const diagonal = wire(100, 78, 320, 340);
    expect(wirePath(diagonal)).toEqual(getBezierPath(diagonal).slice(0, 3));
  });
});
