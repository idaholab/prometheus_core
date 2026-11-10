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
 * src/features/artifacts/viewers/PdfViewerElement.tsx
 *
 * Renders a Chainlit cl.Pdf element as an inline iframe.
 *
 * URL resolution
 * ──────────────
 * The artifact adapter (artifactAdapter.ts) sets `element.url` to the content
 * proxy `GET /api/artifacts/{id}/content`, which streams the PDF bytes inline.
 */

import { FileDown } from "lucide-react";
import type { ViewerProps } from "@/features/artifacts/elements";

export function PdfViewerElement({ element }: ViewerProps) {
  const url = element.url ?? null;

  if (!url) return null;

  const name = element.name ?? "document.pdf";

  return (
    <div className="border border-base-300 rounded-lg overflow-hidden my-2 bg-base-200/40 max-w-3xl">
      <div className="flex items-center justify-between px-3 py-2 border-b border-base-300 bg-base-200/60">
        <p className="text-sm font-medium text-base-content truncate">{name}</p>
        <a
          href={url}
          download={name}
          className="btn btn-ghost btn-xs shrink-0"
          aria-label={`Download ${name}`}
        >
          <FileDown size={13} />
          Download
        </a>
      </div>
      <iframe
        src={url}
        title={name}
        className="w-full h-[600px] bg-base-100"
      />
    </div>
  );
}
