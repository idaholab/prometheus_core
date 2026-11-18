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

import { SectionLabel } from "@/components/ui/SectionLabel";
import { VersionDetail, type WorkflowVersionDetail } from "./VersionDetail";
import { VersionItem, type WorkflowVersion } from "./VersionItem";

interface WorkflowHistoryProps {
  /** Newest first. */
  versions: WorkflowVersion[];
  selectedId?: string;
  /** The selected version's details, or none to leave the pane empty. */
  detail?: WorkflowVersionDetail;
}

/**
 * The Builder's History tab (Figma PPLT-409 D.2c, keeping D.8's layout): one
 * panel holding the version list and the selected version's details. Side by
 * side from 1024px, each pane scrolling on its own; stacked below that, with
 * the Builder scrolling. Clicking a version does nothing yet.
 * Display only; WorkflowBuilder supplies the data.
 */
export function WorkflowHistory({ versions, selectedId, detail }: WorkflowHistoryProps) {
  return (
    <div className="flex min-w-0 flex-1 flex-col p-6 lg:min-h-0">
      <div className="flex min-w-0 flex-1 flex-col rounded-xl border border-base-content/10 lg:flex-row lg:overflow-hidden">
        <section
          aria-label="Version history"
          className="flex min-w-0 flex-col gap-3 p-5 lg:w-75 lg:shrink-0 lg:overflow-y-auto lg:border-r lg:border-base-content/10"
        >
          <SectionLabel variant="panel">Version history</SectionLabel>
          <ul className="m-0 flex list-none flex-col gap-1 p-0">
            {versions.map((version) => (
              <li key={version.id}>
                <VersionItem version={version} selected={version.id === selectedId} />
              </li>
            ))}
          </ul>
        </section>

        <section
          aria-label="Version details"
          className="flex min-h-48 min-w-0 flex-1 flex-col border-t border-base-content/10 p-6 lg:overflow-y-auto lg:border-t-0"
        >
          {detail && <VersionDetail detail={detail} />}
        </section>
      </div>
    </div>
  );
}
