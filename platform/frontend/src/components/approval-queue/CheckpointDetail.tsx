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

import { useId } from "react";
import { Button } from "../ui/Button";
import { StatusPill } from "../ui/StatusPill";
import { Tabs, type Tab } from "../ui/Tabs";
import type { Checkpoint } from "./types";

type DetailTab = "artifact-preview" | "quality-metrics" | "agent-trace" | "requirements";

const DETAIL_TABS: Tab<DetailTab>[] = [
  { id: "artifact-preview", label: "Artifact Preview" },
  { id: "quality-metrics", label: "Quality Metrics" },
  { id: "agent-trace", label: "Agent Trace" },
  { id: "requirements", label: "Requirements" },
];

interface CheckpointDetailProps {
  checkpoint: Checkpoint;
}

/**
 * The selected checkpoint's details (Figma E.1): the header (ID, title,
 * priority and provenance), the detail tabs, and the review footer. Display
 * only: tab switching and the review actions land with AQ-5, and each tab's
 * content with its own ticket.
 */
export function CheckpointDetail({ checkpoint }: CheckpointDetailProps) {
  const { id, title, priority, workflow, agent, confidence } = checkpoint;
  const panelId = useId();
  const notesId = useId();
  const tab: DetailTab = "artifact-preview";
  const tabLabel = DETAIL_TABS.find((t) => t.id === tab)?.label;

  return (
    <article className="flex min-w-0 flex-col gap-6">
      <header className="flex min-w-0 flex-col gap-3">
        <div className="flex min-w-0 items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-0.5">
            {/* Sizes go on each span: the base layer sets span font-size, so it isn't inherited. */}
            <span className="font-mono text-[11px] text-primary">{id}</span>
            <h2 className="m-0 break-words text-lg font-bold text-base-content">{title}</h2>
          </div>
          <StatusPill label={priority} tone={priority === "urgent" ? "error" : "neutral"} className="mt-1" />
        </div>
        <dl className="m-0 flex flex-wrap items-center gap-x-6 gap-y-2 text-xs">
          <div className="flex min-w-0 gap-2">
            <dt className="uppercase text-base-content/50">Originating workflow:</dt>
            <dd className="m-0 break-all font-medium text-base-content">{workflow}</dd>
          </div>
          <div className="flex min-w-0 gap-2">
            <dt className="uppercase text-base-content/50">Producing agent:</dt>
            <dd className="m-0 break-words font-medium text-base-content">{agent}</dd>
          </div>
          <div className="flex min-w-0 gap-1.5 rounded bg-info/10 px-2.5 py-1 font-bold uppercase text-info">
            <dt>Confidence:</dt>
            <dd className="m-0">{confidence}</dd>
          </div>
        </dl>
      </header>

      <div className="flex min-w-0 flex-col gap-4">
        {/* Tab switching lands with AQ-5; until then the selection is fixed. */}
        <Tabs tabs={DETAIL_TABS} selected={tab} onChange={() => undefined} label="Checkpoint details" panelId={panelId} />
        <div
          id={panelId}
          role="tabpanel"
          aria-label={tabLabel}
          className="flex min-h-64 items-center justify-center rounded-lg border border-dashed border-base-content/10 bg-base-200 p-6 text-center text-sm text-base-content/40"
        >
          {tabLabel} coming soon
        </div>
      </div>

      <section aria-label="Review" className="flex min-w-0 flex-col gap-3">
        <label htmlFor={notesId} className="sr-only">
          Review notes
        </label>
        <textarea
          id={notesId}
          placeholder="Add review notes..."
          rows={3}
          className="textarea w-full resize-y rounded-lg border-base-content/10 bg-base-200 text-sm"
        />
        {/* The review actions land with AQ-5. */}
        <div className="flex flex-wrap gap-2">
          <Button label="Reject" variant="error" outline size="sm" />
          <Button label="Request Revision" outline size="sm" />
          <Button label="Approve & Deploy" variant="primary" size="sm" />
        </div>
      </section>
    </article>
  );
}
