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

import { usePageHeader } from "@/lib/store/pageHeader";
import { ApprovalQueue } from "../components/approval-queue/ApprovalQueue";
import type { QueueCounter } from "../components/approval-queue/QueueSummary";
import type { Checkpoint } from "../components/approval-queue/types";

// Placeholder counters from the DES-2 corrected Figma E.1 frame.
const COUNTERS: QueueCounter[] = [
  { id: "pending", label: "Pending Reviews", count: 4, tone: "primary" },
  { id: "urgent", label: "Urgent", count: 2, tone: "error" },
  { id: "approved-today", label: "Approved Today", count: 12, tone: "info" },
  { id: "revision-requested", label: "Revision Requested", count: 1, tone: "neutral" },
];

// Placeholder checkpoints from Figma E.1, in the queue's criticality order.
const CHECKPOINTS: Checkpoint[] = [
  {
    id: "CKP-8841",
    title: "Mesh Validation - Fuel Assembly RC-7",
    priority: "urgent",
    workflow: "TH-COUPLED-RC7",
    agent: "Mesh Generator v1.8",
    confidence: "98.4%",
    submitted: "14m ago",
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
