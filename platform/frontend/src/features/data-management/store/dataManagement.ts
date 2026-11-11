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
 * Holds the Data Management page data: the connected data sources, the
 * artifact storage usage and the generated artifacts. Same
 * useSyncExternalStore pattern as store/session.ts.
 *
 * The data is placeholder only and nothing changes it; PPLT-244 replaces the
 * constants below with an api call in this file.
 */
import { useSyncExternalStore } from "react";

export type SourceStatus = "connected" | "syncing" | "disconnected";
export type ArtifactType = "report" | "mesh" | "result";
export type DataStatus = "ready" | "empty" | "loading" | "error";

export interface DataSource {
  id: string;
  /** Glossary §5.5 connector_class: DEEPLYNX, S3_BUCKET, FILE_SYSTEM, POSTGRESQL, REST_API or WEB_CRAWL. */
  connector_class: string;
  name: string;
  status: SourceStatus;
  enabled: boolean;
  last_sync: string;
  volume_bytes: number;
}

export interface StorageUsage {
  used_bytes: number;
  total_bytes: number;
}

export interface Artifact {
  id: string;
  name: string;
  type: ArtifactType;
  agent: string;
  run_id: string;
  size_bytes: number;
  created: string;
}

export interface DataManagementState {
  status: DataStatus;
  sources: DataSource[];
  storage: StorageUsage;
  artifacts: Artifact[];
}

// placeholder: replace with API (see PPLT-244)
const SOURCES: DataSource[] = [
  {
    id: "mcnp-input-decks",
    connector_class: "S3_BUCKET",
    name: "MCNP Input Deck Repository",
    status: "connected",
    enabled: true,
    last_sync: "10m ago",
    volume_bytes: 2.4e12,
  },
  {
    id: "cad-model-vault",
    connector_class: "FILE_SYSTEM",
    name: "CAD Model Vault (NX/STEP)",
    status: "connected",
    enabled: true,
    last_sync: "2h ago",
    volume_bytes: 890e9,
  },
  {
    id: "relap5-results",
    connector_class: "POSTGRESQL",
    name: "RELAP5 Results Database",
    status: "syncing",
    enabled: true,
    last_sync: "Syncing...",
    volume_bytes: 1.2e12,
  },
  {
    id: "materials-properties",
    connector_class: "REST_API",
    name: "Materials Properties DB",
    status: "connected",
    enabled: true,
    last_sync: "1d ago",
    volume_bytes: 320e9,
  },
  {
    id: "reactor-operating-logs",
    connector_class: "S3_BUCKET",
    name: "Reactor Operating Logs",
    status: "disconnected",
    enabled: false,
    last_sync: "3d ago",
    volume_bytes: 4.1e12,
  },
  {
    id: "nrc-regulatory-library",
    connector_class: "WEB_CRAWL",
    name: "NRC Regulatory Library",
    status: "connected",
    enabled: true,
    last_sync: "5h ago",
    volume_bytes: 150e9,
  },
];

// placeholder: replace with API (see PPLT-244)
const STORAGE: StorageUsage = { used_bytes: 1.8e12, total_bytes: 5.0e12 };

// placeholder: replace with API (see PPLT-244)
const ARTIFACTS: Artifact[] = [
  {
    id: "RUN-3942-thermal_hydraulic_summary.pdf",
    name: "thermal_hydraulic_summary.pdf",
    type: "report",
    agent: "Thermal-Hydraulic Modeler",
    run_id: "RUN-3942",
    size_bytes: 12.4e6,
    created: "2h ago",
  },
  {
    id: "RUN-3941-core_mesh_v3.exo",
    name: "core_mesh_v3.exo",
    type: "mesh",
    agent: "Mesh Generator",
    run_id: "RUN-3941",
    size_bytes: 1.8e9,
    created: "3h ago",
  },
  {
    id: "RUN-3938-dose_rate_map.csv",
    name: "dose_rate_map.csv",
    type: "result",
    agent: "Dose Rate Calculator",
    run_id: "RUN-3938",
    size_bytes: 450e6,
    created: "5h ago",
  },
  {
    id: "RUN-3935-cfd_flow_field.vtu",
    name: "cfd_flow_field.vtu",
    type: "result",
    agent: "CFD Flow Analyzer",
    run_id: "RUN-3935",
    size_bytes: 84e3,
    created: "1d ago",
  },
  {
    id: "RUN-3930-neutronics_report.pdf",
    name: "neutronics_report.pdf",
    type: "report",
    agent: "MCNP Neutronics Solver",
    run_id: "RUN-3930",
    size_bytes: 1.2e6,
    created: "2d ago",
  },
  {
    id: "RUN-3928-keff_tally_results.csv",
    name: "keff_tally_results.csv",
    type: "result",
    agent: "MCNP Neutronics Solver",
    run_id: "RUN-3928",
    size_bytes: 340e6,
    created: "3d ago",
  },
];

export function derive(sources: DataSource[], artifacts: Artifact[]): DataStatus {
  return sources.length === 0 && artifacts.length === 0 ? "empty" : "ready";
}

const state: DataManagementState = {
  status: derive(SOURCES, ARTIFACTS),
  sources: SOURCES,
  storage: STORAGE,
  artifacts: ARTIFACTS,
};
const listeners = new Set<() => void>();

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}
function getSnapshot(): DataManagementState {
  return state;
}

/** Subscribe a component to the Data Management page data. */
export function useDataManagement(): DataManagementState {
  return useSyncExternalStore(subscribe, getSnapshot);
}

/** Used storage as a whole percentage of the total (36 for the placeholder). */
export function storagePercent(s: StorageUsage): number {
  return Math.round((s.used_bytes / s.total_bytes) * 100);
}

const UNITS = ["B", "KB", "MB", "GB", "TB"];

/** Bytes in decimal units with at most one decimal: 1.8e12 -> "1.8 TB", 5e12 -> "5 TB". */
export function formatBytes(bytes: number): string {
  let value = bytes;
  let unit = 0;
  while (value >= 1000 && unit < UNITS.length - 1) {
    value /= 1000;
    unit += 1;
  }
  return `${Number(value.toFixed(1))} ${UNITS[unit]}`;
}
