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

import { AlertTriangle, CheckCircle2, type LucideIcon } from "lucide-react";
import type { CheckpointMetric, MetricStatus } from "./types";

/** Tinted background plus an icon in the status colour. Text stays base-content
 * so it passes AA in both themes: success and warning are too light to read as
 * text on the light theme's cards (same approach as StatusPill). */
const STATUS_STYLES: Record<MetricStatus, { icon: LucideIcon; pill: string; iconClass: string }> = {
  pass: { icon: CheckCircle2, pill: "bg-success/10", iconClass: "text-success" },
  warn: { icon: AlertTriangle, pill: "bg-warning/15", iconClass: "text-warning" },
};

interface MetricCardProps {
  metric: CheckpointMetric;
}

/**
 * One key metric on the Artifact Preview tab (Figma E.1): name and pass/warn
 * status on top, value and threshold below. The status label carries the
 * meaning; the icon and colour back it up.
 */
export function MetricCard({ metric }: MetricCardProps) {
  const { name, value, status, threshold } = metric;
  const { icon: Icon, pill, iconClass } = STATUS_STYLES[status];

  return (
    <article
      aria-label={name}
      className="flex min-w-0 flex-col gap-2 rounded-lg border border-base-content/10 bg-base-200 px-3 py-2.5"
    >
      <div className="flex min-w-0 items-start justify-between gap-2">
        <h4 className="m-0 min-w-0 wrap-break-word text-xs font-normal text-base-content/80">{name}</h4>
        {/* Sizes go on each span: the base layer sets span font-size, so it isn't inherited. */}
        <span
          className={`inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[10px] uppercase leading-3 text-base-content ${pill}`}
        >
          <Icon aria-hidden="true" size={12} strokeWidth={2.25} className={iconClass} />
          {status}
        </span>
      </div>
      <div className="flex min-w-0 flex-wrap items-end justify-between gap-x-2 gap-y-1">
        <span className="min-w-0 wrap-break-word text-sm font-bold text-base-content">{value}</span>
        <span className="shrink-0 text-[10px] uppercase leading-4 text-base-content/50">Threshold: {threshold}</span>
      </div>
    </article>
  );
}
