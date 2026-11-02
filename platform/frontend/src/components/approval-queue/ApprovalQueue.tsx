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

import { SectionLabel } from "../ui/SectionLabel";
import { CheckpointCard } from "./CheckpointCard";
import { CheckpointDetail } from "./CheckpointDetail";
import type { Checkpoint } from "./types";

interface ApprovalQueueProps {
  checkpoints: Checkpoint[];
  selectedId?: string;
  onSelect?: (id: string) => void;
}

/**
 * Approval Queue layout (Figma E.1): the checkpoint list, then the selected
 * checkpoint's details. Side by side from 1024px (the list at up to Figma's
 * 560px, narrower when the sidebar leaves less room), each pane scrolling on its
 * own; stacked below that, with the page scrolling. Display only;
 * PageApprovalQueue supplies the data.
 */
export function ApprovalQueue({ checkpoints, selectedId, onSelect }: ApprovalQueueProps) {
  const selected = checkpoints.find((c) => c.id === selectedId);

  return (
    <div className="flex min-w-0 flex-1 flex-col overflow-y-auto lg:flex-row lg:overflow-hidden">
      <section
        aria-label="Checkpoint queue"
        className="flex min-w-0 flex-col gap-3 border-base-300 p-6 lg:w-[clamp(320px,45%,560px)] lg:shrink-0 lg:overflow-y-auto lg:border-r"
      >
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-1">
          <SectionLabel className="break-all">System approval_checkpoint_queue</SectionLabel>
          <span className="text-[11px] uppercase text-base-content/40">Order: criticality_desc</span>
        </div>
        <ul className="m-0 flex list-none flex-col gap-3 p-0">
          {checkpoints.map((checkpoint) => (
            <li key={checkpoint.id}>
              <CheckpointCard
                checkpoint={checkpoint}
                selected={checkpoint.id === selectedId}
                onSelect={() => onSelect?.(checkpoint.id)}
              />
            </li>
          ))}
        </ul>
      </section>

      <section
        aria-label="Checkpoint details"
        className="flex min-w-0 flex-1 flex-col border-t border-base-300 p-6 lg:overflow-y-auto lg:border-t-0"
      >
        {selected ? (
          <CheckpointDetail checkpoint={selected} />
        ) : (
          <p className="m-0 text-sm text-base-content/50">Select a checkpoint to review it.</p>
        )}
      </section>
    </div>
  );
}
