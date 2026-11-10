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

import { FileDown } from "lucide-react";
import type { AnyElement, ViewerProps } from "@/features/artifacts/elements";
import { artifactFilePresentation } from "@/features/artifacts/artifactPresentation";

/**
 * Shared artifact-label + download-button card. Two callers, one markup:
 *  - FileDownloadElement: registered in VIEWER_REGISTRY for plain "file" kind
 *  - NoViewerFallback: used by ElementRenderer when no viewer is registered
 *    for the element's kind at all (a custom element type not yet built)
 * They render identically except for the subtitle, so it's one component
 * with an optional subtitle rather than two near-duplicate files.
 */
function FileCard({ element, subtitle }: { element: AnyElement; subtitle?: string }) {
  const { label, filename } = artifactFilePresentation(element);
  const url = element.url;

  if (!url) return null;

  return (
    <div className="flex items-center gap-3 bg-base-200 border border-base-300 rounded-lg px-3 py-2.5 my-2 max-w-sm">
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-base-content line-clamp-2 break-words">{label}</p>
        {subtitle && <p className="text-xs text-base-content/40 mt-0.5">{subtitle}</p>}
      </div>
      <a
        href={url}
        download={filename}
        className="btn btn-ghost btn-xs shrink-0"
        aria-label={`Download ${label}`}
      >
        <FileDown size={13} />
        Download
      </a>
    </div>
  );
}

/** File elements with no dedicated viewer — the generic download fallback. */
export function FileDownloadElement({ element }: ViewerProps) {
  return <FileCard element={element} />;
}

/** Used by ElementRenderer when VIEWER_REGISTRY has no component for the element's kind at all. */
export function NoViewerFallback({ element }: { element: AnyElement }) {
  return <FileCard element={element} subtitle="No viewer available yet" />;
}
