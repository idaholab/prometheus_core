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
 * src/dev/ViewerTestHarness.tsx
 *
 * TEMPORARY — delete this file when done testing.
 *
 * Bypasses the entire Chainlit/agent pipeline and renders ElementRenderer
 * directly against a hand-crafted fake element. Useful for testing a new
 * viewer's rendering/styling in isolation without needing a real agent to
 * emit the matching custom element over the wire.
 *
 * To use:
 *   1. Temporarily import <ViewerTestHarness /> somewhere it'll render —
 *      easiest is swapping it in for a route, or dropping it at the top of
 *      Chat.tsx / App.tsx behind an `if (import.meta.env.DEV)` check.
 *   2. `npm run dev`, look at it render.
 *   3. Remove the import and delete this file when done.
 */

import { ElementList } from "@/features/artifacts/ElementRenderer";
import type { AnyElement } from "@/features/artifacts/elements";

const FAKE_MERMAID_ELEMENT: AnyElement = {
  id: "test-mermaid-1",
  type: "custom",
  name: "MermaidViewer", // must match classifyElement()'s switch case exactly
  display: "inline",
  forId: "",
  props: {
    title: "Test Workflow Diagram",
    diagram: `graph TD
    A[Start] --> B{Material data available?}
    B -->|Yes| C[Run thermal analysis]
    B -->|No| D[Fetch material data]
    D --> C
    C --> E{Status acceptable?}
    E -->|Yes| F[Synthesize report]
    E -->|No| G[Flag for review]
    G --> F
    F --> H[Done]`,
  },
};

export function ViewerTestHarness() {
  return (
    <div className="p-8 max-w-2xl mx-auto">
      <h2 className="text-lg font-bold mb-4">Viewer Test Harness (temp)</h2>
      <ElementList elements={[FAKE_MERMAID_ELEMENT]} />
    </div>
  );
}
