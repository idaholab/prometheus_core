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
 * - `primary`: the queue's headline count, e.g. pending reviews (Figma E.1).
 * - `error`: needs action now, e.g. urgent. Gets a dot as well as the colour.
 * - `info`: informational, e.g. approved today.
 * - `neutral`: everything else, e.g. revision requested.
 */
export type QueueCounterTone = "primary" | "error" | "info" | "neutral";

export interface QueueCounter {
  id: string;
  label: string;
  count: number;
  tone: QueueCounterTone;
}

const TONE_CLASSES: Record<QueueCounterTone, string> = {
  primary: "text-primary",
  error: "text-error",
  info: "text-info",
  neutral: "text-base-content",
};

interface QueueSummaryProps {
  counters: QueueCounter[];
}

/**
 * The Approval Queue's summary counters (Figma E.1): a wrapping row of
 * outlined pills, each a coloured count and its label. Display only.
 */
export function QueueSummary({ counters }: QueueSummaryProps) {
  return (
    <ul aria-label="Queue summary" className="m-0 flex list-none flex-wrap gap-2 p-0">
      {counters.map(({ id, label, count, tone }) => (
        <li
          key={id}
          className="inline-flex items-center gap-2 whitespace-nowrap rounded-full border border-base-content/10 px-3.5 py-1"
        >
          {/* Sizes go on each span: the base layer sets span font-size, so it isn't inherited. */}
          <span className={`inline-flex items-center gap-1.5 text-[13px] font-bold ${TONE_CLASSES[tone]}`}>
            {tone === "error" && <span aria-hidden="true" className="size-1.5 rounded-full bg-error" />}
            {count}
          </span>
          <span className="text-[13px] text-base-content/70">{label}</span>
        </li>
      ))}
    </ul>
  );
}
