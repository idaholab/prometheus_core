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

export interface WorkflowVersion {
  id: string;
  /** Display string, e.g. "v1.2.0". */
  version: string;
  /** One-line summary of what changed, e.g. "+ QA Gate after analyses". */
  summary: string;
  /** Display string, e.g. "2 days ago" or "Oct 1". */
  date: string;
  author: string;
  latest?: boolean;
}

interface VersionItemProps {
  version: WorkflowVersion;
  selected?: boolean;
}

/**
 * A version in the Workflow History list (Figma D.8): version number, the
 * "Latest" badge on the newest one, its summary, and when and by whom.
 * Display only for now: selecting a version isn't built yet.
 */
export function VersionItem({ version: item, selected = false }: VersionItemProps) {
  const { version, summary, date, author, latest = false } = item;

  return (
    <article
      aria-label={version}
      aria-current={selected || undefined}
      className={`flex min-w-0 gap-3 rounded-lg px-3 py-2.5 ${selected ? "bg-primary/10" : ""}`}
    >
      <span
        aria-hidden="true"
        className={`mt-1.5 size-1.5 shrink-0 rounded-full ${selected ? "bg-primary" : "bg-base-content/40"}`}
      />
      {/* Sizes go on each span: the base layer sets span font-size, so it isn't inherited. */}
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex min-w-0 items-center justify-between gap-2">
          <h3 className="m-0 font-mono text-[13px] font-normal text-base-content">{version}</h3>
          {latest && (
            <span className="shrink-0 rounded bg-success/25 px-1.5 py-px font-mono text-[9px] uppercase leading-3 tracking-[0.04em] text-base-content">
              Latest
            </span>
          )}
        </div>
        <p className="m-0 wrap-break-word text-[11px] leading-snug text-base-content/80">{summary}</p>
        <span className="font-mono text-[9px] leading-3 text-base-content/50">
          {date} · by {author}
        </span>
      </div>
    </article>
  );
}
