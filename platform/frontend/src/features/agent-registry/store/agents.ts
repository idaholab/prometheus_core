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
 * Holds the agents shown on the Agent Registry page. Same
 * useSyncExternalStore pattern as store/session.ts.
 *
 * The data is a placeholder constant until PPLT-244 adds the registry API;
 * that change replaces AGENTS and adds the load, and nothing else changes.
 * JSX-free and imports only react, so a node:test can cover it.
 */
import { useSyncExternalStore } from "react";

export type AgentStatus = "healthy" | "degraded" | "offline" | "escalating";
export type AgentDomain =
  | "Plant & Systems"
  | "Core & Fuel"
  | "Component"
  | "Structural & Seismic"
  | "Licensing & Regulatory"
  | "Manufacturing & Construction"
  | "Data & Knowledge";
export type AgentIcon =
  | "box"
  | "grid"
  | "activity"
  | "wind"
  | "thermometer"
  | "shield"
  | "database"
  | "file-text";

export interface Agent {
  id: string;
  name: string;
  description: string;
  domain: AgentDomain;
  version: string; // "1.4"; the card shows "V1.4"
  avgRunSeconds: number; // the card shows "AVG: 5m 20s"
  uptimePercent: number; // the card shows "99.8%"
  latencyMs: number; // the card shows "42ms"
  status: AgentStatus;
  icon: AgentIcon; // a key, so the store stays JSX-free and node-testable
}

export type AgentsStatus = "ready" | "empty" | "loading" | "error";
export interface AgentsState {
  agents: readonly Agent[];
  status: AgentsStatus;
}

// placeholder: replace with API (see PPLT-244)
const AGENTS: readonly Agent[] = [
  {
    id: "cad-geometry-validator",
    name: "CAD Geometry Validator",
    description: "Validates nuclear assembly CAD files against neutronics tolerance limits.",
    domain: "Structural & Seismic",
    version: "1.4",
    avgRunSeconds: 45,
    uptimePercent: 99.8,
    latencyMs: 42,
    status: "healthy",
    icon: "box",
  },
  {
    id: "mesh-generator",
    name: "Mesh Generator",
    description: "Creates multi-million cell hex-dominant meshes optimized for fluid calculations.",
    domain: "Plant & Systems",
    version: "2.1",
    avgRunSeconds: 320,
    uptimePercent: 99.5,
    latencyMs: 89,
    status: "healthy",
    icon: "grid",
  },
  {
    id: "mcnp-neutronics-solver",
    name: "MCNP Neutronics Solver",
    description: "Performs high-fidelity Monte Carlo N-Particle radiation transport simulations.",
    domain: "Core & Fuel",
    version: "6.3",
    avgRunSeconds: 4500,
    uptimePercent: 98.2,
    latencyMs: 156,
    status: "healthy",
    icon: "activity",
  },
  {
    id: "cfd-flow-analyzer",
    name: "CFD Flow Analyzer",
    description: "Computes single-phase convective flow and velocity profiles inside core assemblies.",
    domain: "Plant & Systems",
    version: "4.2",
    avgRunSeconds: 1120,
    uptimePercent: 99.9,
    latencyMs: 67,
    status: "healthy",
    icon: "wind",
  },
  {
    id: "thermal-hydraulic-modeler",
    name: "Thermal-Hydraulic Modeler",
    description: "Subchannel thermal analysis and fuel clad temperature solvers.",
    domain: "Core & Fuel",
    version: "3.0",
    avgRunSeconds: 720,
    uptimePercent: 97.6,
    latencyMs: 203,
    status: "healthy",
    icon: "thermometer",
  },
  {
    id: "dose-rate-calculator",
    name: "Dose Rate Calculator",
    description: "Calculates local biological dosage and shield penetration profiles.",
    domain: "Licensing & Regulatory",
    version: "1.2",
    avgRunSeconds: 90,
    uptimePercent: 99.1,
    latencyMs: 34,
    status: "offline",
    icon: "shield",
  },
  {
    id: "material-properties-lookup",
    name: "Material Properties Lookup",
    description: "Cross-checks design parameters against thermodynamic databases.",
    domain: "Data & Knowledge",
    version: "5.0",
    avgRunSeconds: 2,
    uptimePercent: 100,
    latencyMs: 12,
    status: "healthy",
    icon: "database",
  },
  {
    id: "report-generator",
    name: "Report Generator",
    description: "Compiles simulation data into regulatory nuclear compliance reports.",
    domain: "Licensing & Regulatory",
    version: "1.0",
    avgRunSeconds: 15,
    uptimePercent: 99.4,
    latencyMs: 78,
    status: "healthy",
    icon: "file-text",
  },
];

const state: AgentsState = {
  agents: AGENTS,
  status: AGENTS.length === 0 ? "empty" : "ready",
};
const listeners = new Set<() => void>();

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}
function getSnapshot(): AgentsState {
  return state;
}

/** Subscribe a component to the registry agents and their load status. */
export function useAgents(): AgentsState {
  return useSyncExternalStore(subscribe, getSnapshot);
}
