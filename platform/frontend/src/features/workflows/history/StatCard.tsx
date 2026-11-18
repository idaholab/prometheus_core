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

interface StatCardProps {
  /** e.g. "Total runs". Casing is applied with CSS, so pass ordinary text. */
  label: string;
  /** e.g. "12". */
  value: string;
  /** The line under the value, e.g. "since 2 days ago". */
  detail: string;
}

/**
 * One figure in the History tab's run history (Figma D.8, PPLT-409 D.2c): a
 * small mono label, the value, and a line of context under it. Content only
 * comes from props, so every card looks the same.
 */
export function StatCard({ label, value, detail }: StatCardProps) {
  return (
    <article
      aria-label={label}
      className="flex min-w-0 flex-col gap-1 rounded-lg border border-base-content/10 bg-base-content/5 px-4 py-3"
    >
      <h4 className="m-0 font-mono text-[9px] font-normal uppercase leading-3 tracking-[0.04em] text-base-content/60">
        {label}
      </h4>
      <p className="m-0 wrap-break-word text-xl font-bold text-base-content">{value}</p>
      <p className="m-0 wrap-break-word font-mono text-[9px] leading-3 text-base-content/60">{detail}</p>
    </article>
  );
}
