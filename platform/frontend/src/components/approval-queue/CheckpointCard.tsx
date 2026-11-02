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
  onSelect?: () => void;
}

/**
 * A checkpoint in the Approval Queue list (Figma E.1): priority, ID and title,
 * confidence, workflow and age. The whole card selects the checkpoint.
 */
export function CheckpointCard({ checkpoint, selected = false, onSelect }: CheckpointCardProps) {
  const { id, title, priority, workflow, confidence, submitted } = checkpoint;

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`flex w-full min-w-0 flex-col gap-3 rounded-lg bg-base-200 p-4 text-left transition-colors hover:bg-base-content/5 ${
        selected ? "border-[1.5px] border-primary" : "border border-base-content/10"
      }`}
    >
      {/* Below 640px the title wraps onto its own full-width row, so it isn't
          squeezed between the priority and confidence. */}
      <div className="flex min-w-0 flex-wrap items-start gap-3">
        <div className="flex shrink-0 flex-col items-center gap-2">
          <Diamond aria-hidden="true" size={18} className="text-primary" />
          <StatusPill label={priority} tone={priority === "urgent" ? "error" : "neutral"} />
        </div>
        <div className="order-last flex min-w-0 basis-full flex-col gap-0.5 sm:order-none sm:flex-1 sm:basis-0">
          {/* Sizes go on each span: the base layer sets span font-size, so it isn't inherited. */}
          <span className="font-mono text-[10px] text-primary">{id}</span>
          <span className="break-words text-sm font-bold text-base-content">{title}</span>
        </div>
        <span className="ml-auto shrink-0 rounded bg-info/10 px-2 py-0.5 text-[10px] font-bold leading-3 text-info">
          {confidence}
        </span>
      </div>
      <div className="flex min-w-0 items-center justify-between gap-2">
        <span className="min-w-0 break-all font-mono text-[11px] text-base-content/70">{workflow}</span>
        <span className="shrink-0 text-[10px] text-base-content/40">{submitted}</span>
      </div>
    </button>
  );
}
