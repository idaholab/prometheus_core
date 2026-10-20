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
 * prometheus.uq.result.v1 from multiphysics-uq-agent) as an inline baked-notebook
 * report plus a link to the standalone 3D UQ console.
 *
 * URL resolution (all same-origin relative paths — no host / Bearer / secret)
 * ──────────────────────────────────────────────────────────────────────────
 *   - reportUrl   → `/notebook/render/{artifact_id}` — the baked static HTML
 *     report (figures pre-baked; no Voila/kernel, never blank). Served by the
 *     notebook-render service through the `/notebook` frontend proxy, NOT the
 *     artifact content proxy.
 *   - dashboardUrl→ `/uq-console/index.html?result=/notebook/result/{artifact_id}` —
 *     the standalone 3D UQ console, opened in a new tab. Carries this run's
 *     data URL from day one (the page does not yet consume it — see caption).
 *   - downloadUrl → the artifact content proxy (`GET /api/artifacts/{id}/content`),
 *     which streams the `.ipynb` bytes for download.
 *
 * Mirrors PdfViewerElement / ReportElement (daisyui card + iframe + header link).
 */

import { ExternalLink, FileDown, FileText } from "lucide-react";
import type { ViewerProps } from "@/lib/elements/elements";

interface UQProps {
  reportUrl?: string;
  dashboardUrl?: string;
  downloadUrl?: string;
  filename?: string;
  height?: string;
}

export function UQNotebookElement({ element }: ViewerProps) {
  const {
    reportUrl = "",
    dashboardUrl = "",
    downloadUrl = "",
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
          {dashboardUrl && (
            <a
              href={dashboardUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-ghost btn-xs"
              aria-label="Open interactive 3D UQ dashboard in a new tab"
            >
              <ExternalLink size={13} />
              Open interactive dashboard
            </a>
          )}
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
      <p className="px-3 py-2 text-xs text-base-content/50 border-t border-base-300">
        The baked report above is authoritative for this run. The interactive
        3D UQ console is a conceptual demo and is not yet wired to this run's
        numbers.
      </p>
    </div>
  );
}

export default UQNotebookElement;
