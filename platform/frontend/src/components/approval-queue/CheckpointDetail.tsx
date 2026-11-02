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

import { StatusPill } from "../ui/StatusPill";
import type { Checkpoint } from "./types";

interface CheckpointDetailProps {
  checkpoint: Checkpoint;
}

/**
 * The selected checkpoint's details (Figma E.1): ID, title, priority and
 * provenance. The artifact preview, metrics and review actions are placeholders
 * for now.
 */
export function CheckpointDetail({ checkpoint }: CheckpointDetailProps) {
  const { id, title, priority, workflow, agent, confidence } = checkpoint;

  return (
    <article className="flex min-w-0 flex-col gap-6">
      <header className="flex min-w-0 flex-col gap-2">
        <div className="flex min-w-0 items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="font-mono text-[11px] text-primary">{id}</span>
            <h2 className="m-0 break-words text-lg font-bold text-base-content">{title}</h2>
          </div>
          <StatusPill label={priority} tone={priority === "urgent" ? "error" : "neutral"} />
        </div>
        <dl className="m-0 flex flex-wrap items-center gap-x-6 gap-y-1 text-xs">
          <div className="flex min-w-0 gap-2">
            <dt className="uppercase text-base-content/40">Originating workflow:</dt>
            <dd className="m-0 break-all text-base-content">{workflow}</dd>
          </div>
          <div className="flex min-w-0 gap-2">
            <dt className="uppercase text-base-content/40">Producing agent:</dt>
            <dd className="m-0 break-words text-base-content">{agent}</dd>
          </div>
          <div className="flex min-w-0 gap-2">
            <dt className="uppercase text-info">Confidence:</dt>
            <dd className="m-0 font-bold text-info">{confidence}</dd>
          </div>
        </dl>
      </header>

      <div className="flex min-h-64 items-center justify-center rounded-lg border border-dashed border-base-content/10 bg-base-200 p-6 text-center text-sm text-base-content/40">
        Artifact preview, quality metrics and review actions coming soon
      </div>
    </article>
  );
}
