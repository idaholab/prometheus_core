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

import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { SectionLabel } from "@/components/ui/SectionLabel";
import { StatCard } from "./StatCard";

export interface WorkflowVersionChange {
  kind: "added" | "changed";
  /** e.g. "Added QA Gate checkpoint after the parallel analyses". */
  text: string;
}

/** A version's details, shown when it's selected on the History tab. */
export interface WorkflowVersionDetail {
  /** Matches the WorkflowVersion it describes. */
  id: string;
  /** Display string, e.g. "v1.2.0". */
  version: string;
  /** The workflow's id, e.g. "comprehensive_material_analysis". */
  workflowId: string;
  /** The version this one was made from, e.g. "v1.1.0"; none for the first. */
  derivedFrom?: string;
  changes: WorkflowVersionChange[];
  /** What this version invalidated, e.g. cached runs downstream of a new step. */
  invalidated?: string;
  stats: { label: string; value: string; detail: string }[];
  /** Projects the version has run in, with how many runs, e.g. "9 runs". */
  runIn: { project: string; runs: string }[];
}

/**
 * The change markers' tint and glyph, in D.2c's green and amber. The glyph
 * takes the tone colour on the dark theme only: green and amber are too light
 * to read on the light theme's base, so there it stays base-content.
 */
const CHANGE_MARKERS = {
  added: { glyph: "+", label: "Added", className: "border-success/40 bg-success/15 dark:text-success" },
  changed: { glyph: "~", label: "Changed", className: "border-warning/40 bg-warning/20 dark:text-warning" },
} as const;

interface VersionDetailProps {
  detail: WorkflowVersionDetail;
}

/**
 * The selected version's details on the History tab (Figma D.8, PPLT-409
 * D.2c): the version and where it came from, with Restore; what changed;
 * what it invalidated; and its run history as stat cards and the projects
 * it ran in. Display only: Restore has no handler (restoring is out of scope).
 */
export function VersionDetail({ detail }: VersionDetailProps) {
  const { version, workflowId, derivedFrom, changes, invalidated, stats, runIn } = detail;

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 className="m-0 text-xl text-base-content">{version}</h2>
          <p className="m-0 wrap-break-word font-mono text-[11px] text-base-content/60">
            {workflowId}
            {derivedFrom && ` · derived from ${derivedFrom}`}
          </p>
        </div>
        <Button label="Restore this version" size="sm" />
      </div>

      <section aria-label="Changes in this version" className="flex flex-col gap-2">
        <SectionLabel variant="panel" as="h3">Changes in this version</SectionLabel>
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {changes.map((change) => {
            const marker = CHANGE_MARKERS[change.kind];
            return (
              <li key={change.text} className="flex min-w-0 items-start gap-2.5 text-[13px] text-base-content/90">
                {/* Sizes go on each span: the base layer sets span font-size, so it isn't inherited. */}
                <span
                  aria-hidden="true"
                  className={`mt-px flex size-4 shrink-0 items-center justify-center rounded border font-mono text-[11px] leading-none text-base-content ${marker.className}`}
                >
                  {marker.glyph}
                </span>
                <span className="sr-only">{marker.label}: </span>
                <span className="min-w-0 wrap-break-word text-[13px]">{change.text}</span>
              </li>
            );
          })}
        </ul>
      </section>

      {invalidated && (
        <section aria-label="Invalidated by this change" className="flex flex-col gap-2">
          <SectionLabel variant="panel" as="h3">Invalidated by this change</SectionLabel>
          <p className="m-0 flex min-w-0 items-start gap-2.5 rounded-lg border border-error/50 bg-error/10 px-4 py-3 text-xs text-error">
            <AlertTriangle aria-hidden="true" size={14} className="mt-px shrink-0 text-warning" />
            <span className="min-w-0 wrap-break-word text-xs">{invalidated}</span>
          </p>
        </section>
      )}

      <section aria-label="Run history" className="flex flex-col gap-3">
        <SectionLabel variant="panel" as="h3">Run history</SectionLabel>
        {/* As many 10rem columns as fit, so the cards wrap rather than squeeze. */}
        <div className="grid grid-cols-[repeat(auto-fit,minmax(10rem,1fr))] gap-3">
          {stats.map((stat) => (
            <StatCard key={stat.label} {...stat} />
          ))}
        </div>
        <div className="flex flex-col gap-1.5">
          <p className="m-0 font-mono text-[10px] text-base-content/60">Run in:</p>
          <ul aria-label="Run in" className="m-0 flex list-none flex-col gap-1.5 p-0">
            {runIn.map(({ project, runs }) => (
              <li key={project} className="flex min-w-0 items-center gap-2.5">
                <span aria-hidden="true" className="size-1.5 shrink-0 rounded-full bg-primary" />
                <span className="min-w-0 flex-1 wrap-break-word text-xs text-base-content/90">{project}</span>
                <span className="shrink-0 font-mono text-[10px] text-base-content/60">{runs}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  );
}
