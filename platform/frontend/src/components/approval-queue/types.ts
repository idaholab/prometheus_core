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
}
