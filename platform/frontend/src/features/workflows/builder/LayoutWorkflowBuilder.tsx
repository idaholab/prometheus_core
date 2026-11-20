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

import { useId, useState } from "react";
import { Button } from "@/components/ui/Button";
import { SectionLabel } from "@/components/ui/SectionLabel";
import { Tabs, type Tab } from "@/components/ui/Tabs";
import { BuilderCanvas } from "./BuilderCanvas";
import { BuilderModeBadge } from "./BuilderModeBadge";
import { BUILDER_MODES, type BuilderMode } from "@/features/workflows/builderMode";
import { NodeInspector, type InspectedNode } from "./NodeInspector";
import { SkillLibrary, type SkillGroup } from "./SkillLibrary";
import { SwitchToRunDialog } from "./SwitchToRunDialog";
import { TweakStepInspector, type TweakedStep } from "./TweakStepInspector";
import type { WorkflowVersionDetail } from "@/features/workflows/history/VersionDetail";
import type { WorkflowVersion } from "@/features/workflows/history/VersionItem";
import type { WorkflowGraphNode, WorkflowGraphWire } from "@/features/workflows/graph/WorkflowGraph";
import { WorkflowHistory } from "@/features/workflows/history/WorkflowHistory";

interface WorkflowBuilderProps {
  /** Workflow being edited, e.g. "Comprehensive Material Analysis". */
  name: string;
  /** Changing this run only, or the template itself. */
  mode: BuilderMode;
  /** Picked from the mode badge's menu. */
  onModeChange?: (mode: BuilderMode) => void;
  /** The template's current version, e.g. "v1.2.0": the toolbar's version link, and named in the "this run" strip. */
  version: string;
  /** The version saving the template creates, e.g. "v1.3.0", named in the template strip. */
  nextVersion: string;
  /** Skills offered in the library column, in display order. */
  skillGroups: SkillGroup[];
  /** The template's versions, newest first, listed on the History tab. */
  versions: WorkflowVersion[];
  /** Details for the versions that have them, shown for the selected one. */
  versionDetails: WorkflowVersionDetail[];
  /** The workflow's graph, drawn on the canvas. */
  nodes: WorkflowGraphNode[];
  wires: WorkflowGraphWire[];
  /** The node shown in the inspector when changing the template, or null for its empty state. */
  inspected: InspectedNode | null;
  /** The step shown in the inspector when changing this run, or null for its empty state. */
  tweaked?: TweakedStep | null;
  /**
   * Unsaved structural changes to the template, summed up, e.g. "1 node
   * added, 2 wires changed". Switching to this run then asks first (D.2d).
   */
  unsavedChanges?: string;
  /** An error shown as a toast on the canvas, e.g. an invalid connection (D.6). */
  canvasError?: string;
}

type BuilderTab = "canvas" | "history";

const BUILDER_TABS: Tab<BuilderTab>[] = [
  { id: "canvas", label: "Canvas" },
  { id: "history", label: "History" },
];

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
 * Workflow Builder shell (Figma D.2, with the PPLT-409 modes and tabs from
 * D.2a to D.2c): a toolbar with the workflow's name, the mode badge, the
 * version link, the Canvas and History tabs and the mode's commit buttons.
 * The Canvas tab, the default, has a strip saying what the mode changes, then
 * three columns: Skill Library, Canvas and Node Inspector. The History tab
 * (D.2c, formerly the D.8 screen) has the version list instead, and hides the
 * strip and the commit buttons. The version link opens the History tab.
 *
 * - From lg (1024px) the columns sit side by side, at D.2's widths from xl.
 * - Below lg they stack, library first, and the page scrolls vertically.
 *
 * Changing this run can't change the workflow's structure (D.2a): the Skill
 * Library is locked, the canvas drops its wiring affordances, and the
 * inspector is the Tweak Step panel, with no Remove Node. Switching there
 * from the template with `unsavedChanges` asks first (D.2d); "Save template
 * first" and "Discard and switch" both switch, since saving isn't built yet.
 *
 * The commit buttons have no handlers yet.
 */
export function LayoutWorkflowBuilder({
  name,
  mode,
  onModeChange,
  version,
  nextVersion,
  skillGroups,
  versions,
  versionDetails,
  nodes,
  wires,
  inspected,
  tweaked = null,
  unsavedChanges,
  canvasError,
}: WorkflowBuilderProps) {
  const [confirming, setConfirming] = useState(false);
  const [tab, setTab] = useState<BuilderTab>("canvas");
  const panelId = useId();
  const { tone } = BUILDER_MODES[mode];
  const actions = COMMIT_ACTIONS[mode];
  const locked = mode === "run";
  // Picking a version isn't built yet, so the latest stays selected.
  const selectedVersionId = versions.find((v) => v.latest)?.id;

  const changeMode = (next: BuilderMode) => {
    if (next === "run" && unsavedChanges) setConfirming(true);
    else onModeChange?.(next);
  };
  const switchToRun = () => {
    setConfirming(false);
    onModeChange?.("run");
  };

  return (
    <div className="flex flex-1 flex-col overflow-y-auto lg:overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 border-b border-base-content/10 bg-base-200 px-6 py-3">
        <div className="flex min-w-0 flex-wrap items-center gap-x-6 gap-y-3">
          <div className="flex min-w-0 flex-col gap-1">
            <SectionLabel variant="panel">Workflow name</SectionLabel>
            <p className="m-0 text-sm font-semibold text-base-content">{name}</p>
          </div>
          <div aria-hidden="true" className="hidden h-7 w-px bg-base-content/10 sm:block" />
          <BuilderModeBadge mode={mode} workflowName={name} onChange={changeMode} />
          {/* The version link and tabs wrap together, so their divider never ends a row. */}
          <div className="flex min-w-0 flex-wrap items-center gap-x-6 gap-y-3">
            <button
              type="button"
              className="cursor-pointer whitespace-nowrap rounded font-mono text-xs text-primary hover:underline"
              onClick={() => setTab("history")}
            >
              {version}
              {/* Sizes go on each span: the base layer sets span font-size, so it isn't inherited. */}
              {locked && (
                <>
                  {" "}
                  <span className="ml-1 font-mono text-xs text-base-content/60">+ this run</span>
                </>
              )}
            </button>
            <div aria-hidden="true" className="hidden h-7 w-px bg-base-content/10 sm:block" />
            <Tabs tabs={BUILDER_TABS} selected={tab} onChange={setTab} label="Builder view" panelId={panelId} variant="pill" />
          </div>
        </div>
        {tab === "canvas" && (
          <div role="group" aria-label="Workflow actions" className="flex flex-wrap gap-3">
            {actions.map((label, i) => (
              <Button key={label} label={label} size="sm" variant={i === actions.length - 1 ? "primary" : undefined} />
            ))}
          </div>
        )}
      </div>

      {tab === "history" ? (
        <div id={panelId} role="tabpanel" aria-label="History" className="flex flex-1 flex-col lg:min-h-0">
          <WorkflowHistory
            versions={versions}
            selectedId={selectedVersionId}
            detail={versionDetails.find((d) => d.id === selectedVersionId)}
          />
        </div>
      ) : (
        <div id={panelId} role="tabpanel" aria-label="Canvas" className="flex flex-1 flex-col lg:min-h-0">
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
              <SkillLibrary groups={skillGroups} locked={locked} />
            </aside>

            <section aria-label="Canvas" className="min-w-0 lg:min-h-0">
              <BuilderCanvas nodes={nodes} wires={wires} error={canvasError} locked={locked} />
            </section>

            <aside
              aria-label="Node inspector"
              className="border-t border-base-content/10 bg-base-200 p-4 lg:overflow-y-auto lg:border-t-0 lg:border-l"
            >
              {locked ? <TweakStepInspector step={tweaked} /> : <NodeInspector node={inspected} />}
            </aside>
          </div>
        </div>
      )}

      {unsavedChanges && (
        <SwitchToRunDialog
          open={confirming}
          changes={unsavedChanges}
          onCancel={() => setConfirming(false)}
          onSaveFirst={switchToRun}
          onDiscard={switchToRun}
        />
      )}
    </div>
  );
}
