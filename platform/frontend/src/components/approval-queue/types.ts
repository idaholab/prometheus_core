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

/** Shown as a StatusPill: urgent is error-toned, standard neutral (Figma E.1). */
export type CheckpointPriority = "urgent" | "standard";

export interface Checkpoint {
  /** Display ID, e.g. "CKP-8841". */
  id: string;
  title: string;
  priority: CheckpointPriority;
  /** Originating workflow, e.g. "TH-COUPLED-RC7". */
  workflow: string;
  /** Producing agent, e.g. "Mesh Generator v1.8". */
  agent: string;
  /** Display string, e.g. "98.4%". */
  confidence: string;
  /** Display string, e.g. "14m ago". */
  submitted: string;
  /** The artifact under review, shown on the Artifact Preview tab. */
  artifact?: CheckpointArtifact;
}

/** Shown as a tinted label with an icon: pass in success, warn in warning. */
export type MetricStatus = "pass" | "warn";

export interface CheckpointMetric {
  id: string;
  name: string;
  /** Display string, e.g. "42,198 hex". */
  value: string;
  status: MetricStatus;
  /** Display string, e.g. "40k". */
  threshold: string;
}

export interface CheckpointArtifact {
  /** Caption for the preview area, e.g. "3D Mesh Preview - RC-7 Assembly". */
  previewLabel: string;
  fileName: string;
  /** Display string, e.g. "12.4 MB". */
  size: string;
  /** Display string, e.g. "14 min ago". */
  generated: string;
  metrics: CheckpointMetric[];
  requirement: {
    id: string;
    /** Display string, e.g. "v2.1". */
    version: string;
    text: string;
  };
}
