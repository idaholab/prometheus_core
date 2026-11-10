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

import { usePageHeader } from "@/features/shell";
import { ApprovalQueue } from "@/features/approval-queue";
import type { QueueCounter } from "@/features/approval-queue";
import type { Checkpoint } from "@/features/approval-queue";

// Placeholder counters from the DES-2 corrected Figma E.1 frame.
const COUNTERS: QueueCounter[] = [
  { id: "pending", label: "Pending Reviews", count: 4, tone: "primary" },
  { id: "urgent", label: "Urgent", count: 2, tone: "error" },
  { id: "approved-today", label: "Approved Today", count: 12, tone: "info" },
  { id: "revision-requested", label: "Revision Requested", count: 1, tone: "neutral" },
];

// Placeholder checkpoints from Figma E.1, most urgent first.
const CHECKPOINTS: Checkpoint[] = [
  {
    id: "CKP-8841",
    title: "Mesh Validation - Fuel Assembly RC-7",
    priority: "urgent",
    workflow: "TH-COUPLED-RC7",
    agent: "Mesh Generator v1.8",
    confidence: "98.4%",
    submitted: "14m ago",
    artifact: {
      previewLabel: "3D Mesh Preview - RC-7 Assembly",
      fileName: "mesh_rc7_assembly.vtk",
      size: "12.4 MB",
      generated: "14 min ago",
      metrics: [
        { id: "cell-count", name: "Cell Count", value: "42,198 hex", status: "pass", threshold: "40k" },
        { id: "orthogonal-quality", name: "Orthogonal Quality", value: "0.88", status: "pass", threshold: "0.7" },
        { id: "aspect-ratio", name: "Aspect Ratio", value: "3.2 max", status: "warn", threshold: "3.0" },
        { id: "skewness", name: "Skewness", value: "0.31 avg", status: "pass", threshold: "0.5" },
        { id: "volume-change", name: "Volume Change", value: "0.2%", status: "pass", threshold: "0.5%" },
        { id: "boundary-layers", name: "Boundary Layers", value: "5 layers", status: "pass", threshold: "4" },
      ],
      requirement: {
        id: "REQ-TR-842",
        version: "v2.1",
        text: "Fuel assembly coolant velocity must sustain cross-flow mesh bounds under 5.2 m/s transient states without boundary model distortion.",
      },
    },
  },
  {
    id: "CKP-8842",
    title: "Neutronics Output - Core Loading A3",
    priority: "urgent",
    workflow: "NEUTRON-TRANS-A3",
    agent: "Neutronics Solver v3.2",
    confidence: "94.2%",
    submitted: "28m ago",
  },
  {
    id: "CKP-8839",
    title: "Structural FEA Approval - RPV Nozzle",
    priority: "standard",
    workflow: "STRESS-QUAL-WELD",
    agent: "FEA Analyst v2.4",
    confidence: "91.5%",
    submitted: "1h 10m ago",
  },
  {
    id: "CKP-8845",
    title: "CFD Results Verification - Coolant Delta-T",
    priority: "standard",
    workflow: "COOLANT-CFD-D-T",
    agent: "CFD Solver v4.0",
    confidence: "96.8%",
    submitted: "2h 05m ago",
  },
];

/**
 * Approval Queue section page: owns the page's data and header. Layout lives in
 * ApprovalQueue. Route params and filters will land here with the router.
 */
export function PageApprovalQueue() {
  usePageHeader({ title: "Human-in-the-Loop Checkpoint Console" });

  // The first checkpoint is selected, as in E.1. Changing the selection lands with AQ-5.
  return <ApprovalQueue counters={COUNTERS} checkpoints={CHECKPOINTS} selectedId={CHECKPOINTS[0].id} />;
}
