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
 * src/components/ElementRenderer.tsx
 *
 * Dispatches an element to the right viewer, or shows a fallback.
 *
 * Usage — inside the assistant message block in Chat.tsx:
 *
 *   <ElementList elements={m.elements as AnyElement[]} onSend={handleSend} />
 *
 * Also add to Chat.tsx imports:
 *   import { ElementList } from "./ElementRenderer";
 *   import type { AnyElement } from "./elements";
 *
 */

import { Component, Suspense } from "react";
import { AlertCircle } from "lucide-react";
import {
  classifyElement,
  VIEWER_REGISTRY,
  type AnyElement,
  type ViewerProps,
} from "./elements";
import {
  dedupeElements,
  elementKey,
} from "./elementDeduplication";
import { NoViewerFallback } from "./viewers/FileDownloadElement";

// ---------------------------------------------------------------------------
// Error boundary
// ---------------------------------------------------------------------------

class ViewerErrorBoundary extends Component<
  { children: React.ReactNode },
  { crashed: boolean }
> {
  state = { crashed: false };
  static getDerivedStateFromError() { return { crashed: true }; }
  render() {
    if (this.state.crashed) {
      return (
        <div className="flex items-center gap-2 text-sm text-error/70 bg-error/10 rounded px-3 py-2 my-1">
          <AlertCircle size={14} />
          <span>Viewer crashed.</span>
        </div>
      );
    }
    return this.props.children;
  }
}

// ---------------------------------------------------------------------------
// Single element dispatcher
// ---------------------------------------------------------------------------

function ElementRenderer({ element, onSend }: ViewerProps) {
  const kind   = classifyElement(element);
  const Viewer = VIEWER_REGISTRY[kind];

  const inner = Viewer
    ? <Suspense fallback={null}><Viewer element={element} onSend={onSend} /></Suspense>
    : <NoViewerFallback element={element} />;

  return <ViewerErrorBoundary>{inner}</ViewerErrorBoundary>;
}

// ---------------------------------------------------------------------------
// List renderer — drop this into Chat.tsx
// ---------------------------------------------------------------------------

export function ElementList({
  elements,
  onSend,
}: {
  elements?: AnyElement[];
  onSend?: (text: string) => void;
}) {
  if (!elements?.length) return null;
  const uniqueElements = dedupeElements(elements, classifyElement);
  if (!uniqueElements.length) return null;

  return (
    <div className="mt-2 space-y-1">
      {uniqueElements.map((el, i) => (
        <ElementRenderer
          key={elementKey(el) || i}
          element={el}
          onSend={onSend}
        />
      ))}
    </div>
  );
}
