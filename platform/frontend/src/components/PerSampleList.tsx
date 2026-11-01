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

import { api } from "@/lib/api/client";
import type { ArtifactMeta } from "@/lib/api/types";

/** Per-sample files (see `lib/artifacts/perSample.ts`) folded into one closed
 * `<details>` list of download links, so a 100-sample UQ run does not bury its
 * results. Shared by the Artifacts tab and the chat transcript. Renders nothing
 * when there are none. */
export function PerSampleList({ artifacts }: { artifacts: readonly ArtifactMeta[] }) {
  if (artifacts.length === 0) return null;
  return (
    <details className="mt-2 rounded-lg border border-base-300 bg-base-200 px-3 py-2 text-xs">
      <summary className="cursor-pointer font-semibold text-base-content/70">
        {artifacts.length} per-sample files (configs, ZDOs, logs)
      </summary>
      <ul className="m-0 mt-2 max-h-64 list-none space-y-1 overflow-y-auto p-0">
        {artifacts.map((a) => (
          <li key={a.artifact_id}>
            <a
              href={api.artifactContentUrl(a.artifact_id)}
              target="_blank"
              rel="noreferrer"
              className="link link-hover"
            >
              {a.name}
            </a>
          </li>
        ))}
      </ul>
    </details>
  );
}
