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

import { Button } from "@/components/ui/Button";
import { SectionLabel } from "@/components/ui/SectionLabel";
import { BuilderCanvas } from "./BuilderCanvas";
import { BuilderModeBadge } from "./BuilderModeBadge";
import { BUILDER_MODES, type BuilderMode } from "./builderMode";
import { NodeInspector, type InspectedNode } from "./NodeInspector";
import { SkillLibrary, type SkillGroup } from "./SkillLibrary";
import type { WorkflowGraphNode, WorkflowGraphWire } from "./WorkflowGraph";

interface WorkflowBuilderProps {
  /** Workflow being edited, e.g. "Comprehensive Material Analysis". */
  name: string;
  /** Changing this run only, or the template itself. */
  mode: BuilderMode;
  /** Picked from the mode badge's menu. */
  onModeChange?: (mode: BuilderMode) => void;
  /** The template's current version, e.g. "v1.2.0", named in the "this run" strip. */
  version: string;
  /** The version saving the template creates, e.g. "v1.3.0", named in the template strip. */
  nextVersion: string;
  /** Skills offered in the library column, in display order. */
  skillGroups: SkillGroup[];
  /** The workflow's graph, drawn on the canvas. */
  nodes: WorkflowGraphNode[];
  wires: WorkflowGraphWire[];
  /** The node shown in the inspector, or null for its empty state. */
  inspected: InspectedNode | null;
  /** An error shown as a toast on the canvas, e.g. an invalid connection (D.6). */
  canvasError?: string;
}

/** The commit buttons for each mode, last one primary (Figma PPLT-409 D.2a, D.2b). */
const COMMIT_ACTIONS: Record<BuilderMode, string[]> = {
  run: ["Save as variant", "Propose new version", "Run once"],
  template: ["Validate", "Save", "Run Workflow"],
};

/** The mode strip's tone, matching the badge. */
const STRIP_CLASSES = {
  info: { strip: "border-info/40 bg-info/10", dot: "bg-info" },
  warning: { strip: "border-warning/40 bg-warning/10", dot: "bg-warning" },
} as const;

function modeMessage(mode: BuilderMode, name: string, version: string, nextVersion: string): string {
  return mode === "run"
    ? `Changes apply to this run only. The template (${version}) is untouched. To keep them, save as a variant or propose a new version.`
    : `Editing the template. Saving creates ${nextVersion} for everyone who uses ${name}.`;
}

/**
 * Workflow Builder shell (Figma D.2, with the PPLT-409 modes from D.2a and
 * D.2b): a toolbar with the workflow's name, the mode badge and the mode's
 * commit buttons; a strip saying what the mode changes; then three columns:
 * Skill Library, Canvas and Node Inspector.
 *
 * - From lg (1024px) the columns sit side by side, at D.2's widths from xl.
 * - Below lg they stack, library first, and the page scrolls vertically.
 *
 * The commit buttons have no handlers yet.
 */
export function WorkflowBuilder({
  name,
  mode,
  onModeChange,
  version,
  nextVersion,
  skillGroups,
  nodes,
  wires,
  inspected,
  canvasError,
}: WorkflowBuilderProps) {
  const { tone } = BUILDER_MODES[mode];
  const actions = COMMIT_ACTIONS[mode];

  return (
    <div className="flex flex-1 flex-col overflow-y-auto lg:overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 border-b border-base-content/10 bg-base-200 px-6 py-3">
        <div className="flex min-w-0 flex-wrap items-center gap-x-6 gap-y-3">
          <div className="flex min-w-0 flex-col gap-1">
            <SectionLabel variant="panel">Workflow name</SectionLabel>
            <p className="m-0 text-sm font-semibold text-base-content">{name}</p>
          </div>
          <div aria-hidden="true" className="hidden h-7 w-px bg-base-content/10 sm:block" />
          <BuilderModeBadge mode={mode} workflowName={name} onChange={onModeChange} />
        </div>
        <div role="group" aria-label="Workflow actions" className="flex flex-wrap gap-3">
          {actions.map((label, i) => (
            <Button key={label} label={label} size="sm" variant={i === actions.length - 1 ? "primary" : undefined} />
          ))}
        </div>
      </div>

      <p
        className={`m-0 flex items-start gap-2 border-b px-6 py-2 text-xs text-base-content ${STRIP_CLASSES[tone].strip}`}
      >
        <span aria-hidden="true" className={`mt-1.5 size-1.5 shrink-0 rounded-full ${STRIP_CLASSES[tone].dot}`} />
        {modeMessage(mode, name, version, nextVersion)}
      </p>

      <div className="grid flex-1 grid-cols-1 lg:min-h-0 lg:grid-cols-[200px_minmax(0,1fr)_240px] xl:grid-cols-[240px_minmax(0,1fr)_280px]">
        <aside
          aria-label="Skill library"
          className="border-b border-base-content/10 bg-base-200 p-4 lg:overflow-y-auto lg:border-r lg:border-b-0"
        >
          <SkillLibrary groups={skillGroups} />
        </aside>

        <section aria-label="Canvas" className="min-w-0 lg:min-h-0">
          <BuilderCanvas nodes={nodes} wires={wires} error={canvasError} />
        </section>

        <aside
          aria-label="Node inspector"
          className="border-t border-base-content/10 bg-base-200 p-4 lg:overflow-y-auto lg:border-t-0 lg:border-l"
        >
          <NodeInspector node={inspected} />
        </aside>
      </div>
    </div>
  );
}
