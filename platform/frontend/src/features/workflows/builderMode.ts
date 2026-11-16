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
 * The Builder's two modes (Figma PPLT-409): changing this run of a workflow,
 * which leaves its template alone, or changing the template itself, which
 * makes a new version for everyone. Each mode's wording lives here so the
 * Console's Modify Plan menu, the mode badge and the mode strip agree.
 */
export type BuilderMode = "run" | "template";

export interface BuilderModeCopy {
  /** What the badge reads after "Changing:", e.g. "this run". */
  badge: string;
  /** The menu option that picks this mode, e.g. "Change this run". */
  option: string;
  /** The line under that option. */
  description: (workflowName: string) => string;
  tone: "info" | "warning";
}

export const BUILDER_MODES: Record<BuilderMode, BuilderModeCopy> = {
  run: {
    badge: "this run",
    option: "Change this run",
    description: () => "Default. Tweak steps for this run only; the template is untouched.",
    tone: "info",
  },
  template: {
    badge: "the template",
    option: "Edit the template",
    description: (workflowName) => `Change ${workflowName} for everyone (new version).`,
    tone: "warning",
  },
};
