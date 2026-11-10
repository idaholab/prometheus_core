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

import { FileText } from "lucide-react";
import type { ArtifactType } from "./store/dataManagement";
import { DataTable, type DataTableColumn } from "@/components/ui/DataTable";
import { FilterChips } from "@/components/ui/FilterChips";

/** One artifact row with its size already formatted for display. */
export interface ArtifactRow {
  id: string;
  name: string;
  agent: string;
  runId: string;
  size: string;
  created: string;
}

interface Props {
  usedLabel: string;
  totalLabel: string;
  percent: number;
  artifacts: ArtifactRow[];
}

/** The type chips; `type` is null for All. The chips do not filter yet (DM-4). */
const ARTIFACT_CHIPS: readonly { label: string; type: ArtifactType | null }[] = [
  { label: "All", type: null },
  { label: "Reports", type: "report" },
  { label: "Meshes", type: "mesh" },
  { label: "Results", type: "result" },
];
const CHIPS = ARTIFACT_CHIPS.map((chip) => ({ id: chip.label, label: chip.label }));

const COLUMNS: DataTableColumn<ArtifactRow>[] = [
  {
    id: "name",
    header: "Artifact Name",
    value: (row) => row.name,
    cell: (row) => (
      <span className="flex min-w-0 max-w-32 items-center gap-2">
        <span className="shrink-0 text-primary">
          <FileText size={14} aria-hidden="true" />
        </span>
        <span className="truncate" title={row.name}>
          {row.name}
        </span>
      </span>
    ),
  },
  {
    id: "agent",
    header: "Generating Agent",
    value: (row) => row.agent,
    cell: (row) => (
      <span className="block max-w-32 truncate" title={row.agent}>
        {row.agent}
      </span>
    ),
  },
  {
    id: "run",
    header: "Run ID",
    value: (row) => row.runId,
    cell: (row) => (
      <button type="button" className="link link-primary font-mono">
        {row.runId}
      </button>
    ),
  },
  { id: "size", header: "Size", value: (row) => row.size },
  { id: "created", header: "Created", value: (row) => row.created },
];

/**
 * The artifact storage bar and the generated artifacts registry. Props only;
 * the chips and the run IDs look interactive and do nothing yet (DM-4).
 */
export function StoragePanel({ usedLabel, totalLabel, percent, artifacts }: Props) {
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="card min-w-0 bg-base-200 border border-base-300">
        <div className="card-body gap-2.5 p-4">
          <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-semibold text-base-content/60">ARTIFACT STORAGE PERSISTENCE</span>
            <span className="font-mono text-xs text-base-content">
              {usedLabel} / {totalLabel} USED ({percent}%)
            </span>
          </div>
          <progress
            className="progress progress-primary w-full"
            value={percent}
            max={100}
            aria-label="Artifact storage used"
          />
        </div>
      </div>

      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
          <span className="text-xs font-semibold text-base-content/60">GENERATED ARTIFACTS REGISTRY</span>
          <FilterChips chips={CHIPS} selected="All" label="Artifact types" />
        </div>
        <DataTable columns={COLUMNS} data={artifacts} rowId={(row) => row.id} label="Generated artifacts" />
      </div>
    </div>
  );
}
