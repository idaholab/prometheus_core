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

import { Download, Grid3x3, Move, RotateCw, ZoomIn } from "lucide-react";
import { Button } from "../ui/Button";
import { SectionLabel } from "../ui/SectionLabel";
import { MetricCard } from "./MetricCard";
import type { CheckpointArtifact } from "./types";

interface ArtifactPreviewProps {
  artifact: CheckpointArtifact;
}

/**
 * The Artifact Preview tab (Figma E.1): the preview area and its toolbar, the
 * file details, the key metrics and the linked requirement. Display only: the
 * preview is a static graphic, and the toolbar and download buttons do nothing yet.
 */
export function ArtifactPreview({ artifact }: ArtifactPreviewProps) {
  const { previewLabel, fileName, size, generated, metrics, requirement } = artifact;

  return (
    // A container, so the metric grid follows the panel's width rather than the
    // viewport's: the panel is narrow at 1024px with the list beside it.
    <div className="@container flex min-w-0 flex-col gap-6">
      <div className="flex min-w-0 flex-col gap-3">
        <figure className="relative m-0 flex aspect-3/2 min-h-56 flex-col items-center justify-center gap-4 rounded-lg border border-base-content/10 bg-base-300 p-4 text-center">
          <div role="toolbar" aria-label="Preview controls" className="absolute right-3 top-3 flex gap-2">
            <Button icon={<RotateCw />} ariaLabel="Reset view" outline subtle size="sm" tooltipPlacement="left" />
            <Button icon={<ZoomIn />} ariaLabel="Zoom" outline subtle size="sm" tooltipPlacement="left" />
            <Button icon={<Move />} ariaLabel="Pan" outline subtle size="sm" tooltipPlacement="left" />
            <Button icon={<Download />} ariaLabel="Download preview" outline subtle size="sm" tooltipPlacement="left" />
          </div>
          <Grid3x3 aria-hidden="true" size={56} strokeWidth={1} className="text-base-content/30" />
          <figcaption className="text-sm text-base-content/50">{previewLabel}</figcaption>
        </figure>

        <div className="flex min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <dl className="m-0 flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-base-content/80">
            <div className="min-w-0">
              <dt className="sr-only">File</dt>
              <dd className="m-0 break-all">{fileName}</dd>
            </div>
            <div>
              <dt className="sr-only">Size</dt>
              <dd className="m-0">{size}</dd>
            </div>
            <div>
              <dt className="sr-only">Generated</dt>
              <dd className="m-0">Generated {generated}</dd>
            </div>
          </dl>
          <Button label="Download Artifact" icon={<Download />} variant="primary" outline size="sm" />
        </div>
      </div>

      <section className="flex min-w-0 flex-col gap-3">
        <SectionLabel as="h3">Key metrics summary</SectionLabel>
        <div className="grid grid-cols-1 gap-3 @md:grid-cols-2">
          {metrics.map((metric) => (
            <MetricCard key={metric.id} metric={metric} />
          ))}
        </div>
      </section>

      <section className="flex min-w-0 flex-col gap-3">
        <SectionLabel as="h3">Linked requirement</SectionLabel>
        <blockquote className="m-0 flex min-w-0 flex-col gap-2 rounded-lg border border-base-content/10 bg-base-200 px-3 py-3">
          <span className="font-mono text-[11px] font-bold uppercase text-base-content">
            {requirement.id} ({requirement.version})
          </span>
          <p className="m-0 wrap-break-word text-[13px] text-base-content/80">&ldquo;{requirement.text}&rdquo;</p>
        </blockquote>
      </section>
    </div>
  );
}
