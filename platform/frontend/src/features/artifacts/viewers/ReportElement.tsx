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
 * src/features/artifacts/viewers/ReportElement.tsx
 *
 * Renders a `report` artifact (render_hint === "report") as inline markdown rather
 * than a download (frontend presentation-parity note A-1). Markdown/plain-text
 * report artifacts don't carry their body on the wire, so when no inline `markdown`
 * prop is present this fetches the text from the content proxy
 * (`GET /api/artifacts/{id}/content`) and renders it with the shared Markdown
 * component. A fetch failure degrades to a "couldn't load" line + download link
 * rather than dropping the artifact.
 */

import { AlertCircle, FileDown, FileText } from "lucide-react";
import { Markdown } from "@/components/ui/Markdown";
import type { ViewerProps } from "@/features/artifacts/elements";
import { useArtifactText } from "./useArtifactText";

interface ReportProps {
  markdown?: string;
  title?: string;
  url?: string;
}

export function ReportElement({ element }: ViewerProps) {
  const { markdown = "", title, url = "" } = (element.props ?? {}) as ReportProps;
  const name = title || element.name || "Report";

  const { text, loadState } = useArtifactText(markdown, url);

  return (
    <div className="border border-base-300 rounded-lg overflow-hidden my-2 bg-base-200/40 max-w-3xl">
      <div className="flex items-center justify-between gap-3 px-3 py-2 border-b border-base-300 bg-base-200/60">
        <p className="text-sm font-medium text-base-content truncate flex items-center gap-1.5">
          <FileText size={13} className="text-base-content/50 shrink-0" />
          {name}
        </p>
        {url && (
          <a href={url} download={name} className="btn btn-ghost btn-xs shrink-0" aria-label={`Download ${name}`}>
            <FileDown size={13} />
            Download
          </a>
        )}
      </div>
      <div className="bg-base-100 px-4 py-3 text-sm [&_p]:my-2 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0 [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:my-2 [&_a]:underline">
        {loadState === "loading" && <span className="text-xs text-base-content/50">Loading report…</span>}
        {loadState === "error" && (
          <span className="text-xs text-error inline-flex items-center gap-1.5">
            <AlertCircle size={13} />
            Couldn't load this report.
          </span>
        )}
        {loadState === "idle" && text && <Markdown>{text}</Markdown>}
      </div>
    </div>
  );
}

export default ReportElement;
