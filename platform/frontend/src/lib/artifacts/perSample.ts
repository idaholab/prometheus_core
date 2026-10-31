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

import type { ArtifactMeta } from "../api/types.ts";

/** Tags that mark one-file-per-sample plumbing rather than a result a person opens. */
export const PER_SAMPLE_TAGS = ["uq-sample", "zdo", "diagnostics"] as const;

/**
 * Per-sample plumbing: one file per UQ sample (its pipeline config, its ZDO, its
 * failure log). A 100-sample run makes hundreds, so the Artifacts tab keeps them
 * out of its main list and shows them collapsed underneath. The UQ agent tags its
 * per-sample configs `uq-sample`; the okflow runner tags ZDOs `zdo` and failure
 * reports `diagnostics`.
 */
export function isPerSampleArtifact(
  artifact: Pick<ArtifactMeta, "tags">,
): boolean {
  const tags = artifact.tags ?? [];
  return PER_SAMPLE_TAGS.some((tag) => tags.includes(tag));
}
