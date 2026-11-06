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
 *   - reportUrl   → `/api/artifacts/{artifact_id}/report` — the baked static HTML
 *     report (figures pre-baked; no live kernel, never blank). The backend
 *     resolves it from shared storage (DeepLynx), so the producer can run on any
 *     host. Empty when the producer attached no report: only the download shows.
 *   - downloadUrl → the artifact content proxy (`GET /api/artifacts/{id}/content`),
 *     which streams the `.ipynb` bytes for download.
 *
 * The frame loads lazily. Its sandboxed document is opaque to us, so once it has
 * loaded the viewer re-checks the report URL (a private-cacheable response, so
 * usually a cache hit); a 404/502 swaps the frame for a short notice, leaving the
 * notebook download as the way in, instead of raw JSON in a 760px frame.
 *
 * Mirrors PdfViewerElement / ReportElement (daisyui card + iframe + header link).
 */

import { useEffect, useRef, useState } from "react";
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
  const [reportFailed, setReportFailed] = useState(false);
  const probe = useRef<AbortController | null>(null);

  useEffect(() => {
    setReportFailed(false);
    return () => probe.current?.abort();
  }, [reportUrl]);

  const checkReport = () => {
    probe.current?.abort();
    const controller = new AbortController();
    probe.current = controller;
    fetch(reportUrl, { credentials: "same-origin", signal: controller.signal })
      .then((resp) => {
        if (!resp.ok) setReportFailed(true);
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setReportFailed(err instanceof Error);
      });
  };

  if (!reportUrl && !downloadUrl) return null;

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
      {reportUrl && reportFailed && (
        <p role="status" className="m-0 px-3 py-4 text-sm text-base-content/70">
          The report could not be loaded.{downloadUrl ? " Download the notebook to view the results." : ""}
        </p>
      )}
      {reportUrl && !reportFailed && (
        // The report runs its own scripts (Plotly); a sandbox without
        // allow-same-origin keeps them away from the platform's cookies and DOM,
        // and any popup it opens stays sandboxed.
        <iframe
          src={reportUrl}
          title={name}
          sandbox="allow-scripts allow-popups"
          loading="lazy"
          onLoad={checkReport}
          style={{ height }}
          className="w-full bg-base-100"
        />
      )}
    </div>
  );
}

export default UQNotebookElement;
