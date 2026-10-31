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
 * src/viewers/UQNotebookElement.tsx
 *
 * Renders a `uq` artifact (render_hint === "uq", json_type
 * prometheus.uq.result.v1, from a UQ agent) as an inline baked-notebook
 * report with a link to download the notebook and any buttons the producing agent
 * attached (`links`, see ArtifactLinks).
 *
 * URL resolution (all same-origin relative paths — no host / Bearer / secret)
 * ──────────────────────────────────────────────────────────────────────────
 *   - reportUrl   → `/notebook/render/{artifact_id}` — the baked static HTML
 *     report (figures pre-baked; no live kernel, never blank). Served by the
 *     notebook-render service through the `/notebook` frontend proxy, NOT the
 *     artifact content proxy.
 *   - downloadUrl → the artifact content proxy (`GET /api/artifacts/{id}/content`),
 *     which streams the `.ipynb` bytes for download.
 *
 * Mirrors PdfViewerElement / ReportElement (daisyui card + iframe + header link).
 */

import { FileDown, FileText } from "lucide-react";
import type { ArtifactLink } from "@/lib/api/types";
import type { ViewerProps } from "@/lib/elements/elements";
import { ArtifactLinks } from "./ArtifactLinks";

interface UQProps {
  reportUrl?: string;
  downloadUrl?: string;
  links?: ArtifactLink[];
  filename?: string;
  height?: string;
}

export function UQNotebookElement({ element }: ViewerProps) {
  const {
    reportUrl = "",
    downloadUrl = "",
    links = [],
    filename,
    height = "760px",
  } = (element.props ?? {}) as UQProps;

  const name = filename || element.name || "UQ analysis";

  if (!reportUrl) return null;

  return (
    <div className="border border-base-300 rounded-lg overflow-hidden my-2 bg-base-200/40 max-w-3xl">
      <div className="flex items-center justify-between gap-3 px-3 py-2 border-b border-base-300 bg-base-200/60">
        <p className="text-sm font-medium text-base-content truncate flex items-center gap-1.5">
          <FileText size={13} className="text-base-content/50 shrink-0" />
          {name}
        </p>
        <div className="flex items-center gap-1 shrink-0">
          <ArtifactLinks links={links} />
          {downloadUrl && (
            <a
              href={downloadUrl}
              download={name}
              className="btn btn-ghost btn-xs"
              aria-label={`Download ${name} notebook`}
            >
              <FileDown size={13} />
              .ipynb
            </a>
          )}
        </div>
      </div>
      <iframe
        src={reportUrl}
        title={name}
        style={{ height }}
        className="w-full bg-base-100"
      />
    </div>
  );
}

export default UQNotebookElement;
