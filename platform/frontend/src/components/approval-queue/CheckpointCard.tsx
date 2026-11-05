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

import { Diamond } from "lucide-react";
import { StatusPill } from "../ui/StatusPill";
import type { Checkpoint } from "./types";

interface CheckpointCardProps {
  checkpoint: Checkpoint;
  selected?: boolean;
}

/**
 * A checkpoint in the Approval Queue list (Figma E.1): priority, ID and title,
 * confidence, workflow and age. Display only for now; selecting a card comes
 * with the detail panel wiring.
 */
export function CheckpointCard({ checkpoint, selected = false }: CheckpointCardProps) {
  const { id, title, priority, workflow, confidence, submitted } = checkpoint;

  return (
    <article
      aria-label={`${id}: ${title}`}
      aria-current={selected || undefined}
      className={`@container flex w-full min-w-0 flex-col gap-3 rounded-lg bg-base-200 p-4 ${
        selected ? "border-[1.5px] border-primary" : "border border-base-content/10"
      }`}
    >
      {/* In a card narrower than 384px (phones, and the side-by-side list near
          1024px) the title wraps onto its own full-width row, so it isn't
          squeezed between the priority and confidence. */}
      <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-3">
        <div className="flex w-20 shrink-0 flex-col items-center gap-2">
          <Diamond aria-hidden="true" size={20} strokeWidth={1.5} className="text-primary" />
          <StatusPill label={priority} tone={priority === "urgent" ? "error" : "neutral"} />
        </div>
        <div className="order-last flex min-w-0 basis-full flex-col gap-0.5 @sm:order-0 @sm:flex-1 @sm:basis-0">
          {/* Sizes go on each span: the base layer sets span font-size, so it isn't inherited. */}
          <span className="font-mono text-[10px] text-primary">{id}</span>
          <h3 className="m-0 wrap-break-word text-sm font-bold leading-snug text-base-content">{title}</h3>
        </div>
        <span className="ml-auto shrink-0 self-start rounded bg-info/10 px-2 py-1 font-mono text-[10px] font-bold leading-3 text-info @sm:self-center">
          <span className="sr-only">Confidence </span>
          {confidence}
        </span>
      </div>
      <div className="flex min-w-0 items-center justify-between gap-2">
        <span className="min-w-0 break-all font-mono text-[11px] text-base-content/70">
          <span className="sr-only">Workflow </span>
          {workflow}
        </span>
        <span className="shrink-0 text-[10px] text-base-content/40">{submitted}</span>
      </div>
    </article>
  );
}
