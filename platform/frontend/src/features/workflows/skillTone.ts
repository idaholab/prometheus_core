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
 * Dot colour for a group's skills (Figma D.2):
 * - `data`: cyan, e.g. Get Material Data.
 * - `analysis`: green, used by Analysis and Synthesis.
 * - `control`: indigo, e.g. Checkpoint (SME).
 */
export type SkillTone = "data" | "analysis" | "control";

/** Shared by the library's items and the canvas's skill nodes, so their dots match. */
export const SKILL_TONE_DOT_CLASSES: Record<SkillTone, string> = {
  data: "bg-info",
  analysis: "bg-success",
  control: "bg-primary",
};
