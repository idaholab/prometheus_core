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

import { Button } from "../ui/Button";
import { SectionLabel } from "../ui/SectionLabel";
import { SkillLibrary, type SkillGroup } from "./SkillLibrary";

interface WorkflowBuilderProps {
  /** Workflow being edited, e.g. "Comprehensive Material Analysis". */
  name: string;
  /** Skills offered in the library column, in display order. */
  skillGroups: SkillGroup[];
}

/** D.2's canvas dot grid, from the theme's text colour so it shows in both themes. */
const CANVAS_DOTS =
  "radial-gradient(circle, color-mix(in oklab, var(--color-base-content) 15%, transparent) 1px, transparent 1px)";

/**
 * Workflow Builder shell (Figma D.2): a toolbar with the workflow's name and
 * actions, over three columns: Skill Library, Canvas and Node Inspector.
 *
 * - From lg (1024px) the columns sit side by side, at D.2's widths from xl.
 * - Below lg they stack, library first, and the page scrolls vertically.
 *
 * The canvas and inspector are filled in by WB-3 and WB-4, and the toolbar
 * buttons have no handlers yet.
 */
export function WorkflowBuilder({ name, skillGroups }: WorkflowBuilderProps) {
  return (
    <div className="flex flex-1 flex-col overflow-y-auto lg:overflow-hidden">
      <div className="flex flex-wrap items-center gap-x-9 gap-y-3 border-b border-base-content/10 bg-base-200 px-6 py-3">
        <div className="flex min-w-0 flex-col gap-1">
          <SectionLabel variant="panel">Workflow name</SectionLabel>
          <p className="m-0 text-sm font-semibold text-base-content">{name}</p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Button label="Validate" size="sm" />
          <Button label="Save" size="sm" />
          <Button label="Run Workflow" size="sm" variant="primary" />
        </div>
      </div>

      <div className="grid flex-1 grid-cols-1 lg:min-h-0 lg:grid-cols-[200px_minmax(0,1fr)_240px] xl:grid-cols-[240px_minmax(0,1fr)_280px]">
        <aside
          aria-label="Skill library"
          className="border-b border-base-content/10 bg-base-200 p-4 lg:overflow-y-auto lg:border-r lg:border-b-0"
        >
          <SkillLibrary groups={skillGroups} />
        </aside>

        {/* Dot grid from D.2; the canvas itself lands in WB-3. */}
        <section
          aria-label="Canvas"
          className="min-h-[400px] bg-base-300 bg-size-[20px_20px] lg:min-h-0"
          style={{ backgroundImage: CANVAS_DOTS }}
        />

        <aside
          aria-label="Node inspector"
          className="flex flex-col gap-4 border-t border-base-content/10 bg-base-200 p-4 lg:overflow-y-auto lg:border-t-0 lg:border-l"
        >
          <SectionLabel variant="panel">Node Inspector</SectionLabel>
        </aside>
      </div>
    </div>
  );
}
