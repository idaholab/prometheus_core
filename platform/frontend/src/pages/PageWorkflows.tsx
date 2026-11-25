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

import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import type { Workflow } from "@/lib/api/types";
import { usePageHeader } from "@/features/shell";
import { LayoutWorkflowBuilder } from "@/features/workflows";
import { LayoutWorkflowConsole } from "@/features/workflows";
import type { BuilderMode } from "@/features/workflows";
import type { WorkflowPlan } from "@/features/workflows";
import { toPlan, toTemplate } from "@/features/workflows";
import {
  BUILDER_NODES,
  BUILDER_WIRES,
  INSPECTED_NODE,
  RUN_NODES,
  SKILL_GROUPS,
  TWEAKED_STEP,
  UNSAVED_CHANGES,
  VERSION_DETAILS,
  WORKFLOW_VERSIONS,
} from "@/features/workflows";

// Placeholder name of the template the Builder opens, until the Builder loads real templates.
const BUILDER_TEMPLATE_NAME = "Comprehensive Material Analysis";

// Placeholder versions of the selected template, from Figma PPLT-409 D.2a and D.2b.
const TEMPLATE_VERSION = "v1.2.0";
const NEXT_TEMPLATE_VERSION = "v1.3.0";

/** What the Builder opens on: the selected template, or a new workflow's empty canvas (D.3). */
type BuilderStart = { mode: BuilderMode; isNew: boolean };

/**
 * Workflows section page: owns the page's data and header, and which view is
 * showing: the Workflow Console, or the Builder opened from its "Modify Plan"
 * (in either mode) or "+ New Workflow". Layout lives in LayoutWorkflowConsole and
 * LayoutWorkflowBuilder.
 *
 * The Builder is a view here rather than its own route until PPLT-240 gives
 * it a URL. LayoutApp remounts this page on every sidebar click, so clicking
 * Workflows from the Builder returns to the Console.
 */
export function PageWorkflows() {
  const [builder, setBuilder] = useState<BuilderStart | null>(null);

  if (builder) return <BuilderView start={builder} />;
  return (
    <ConsoleView
      onModifyPlan={(mode) => setBuilder({ mode, isNew: false })}
      onNewWorkflow={() => setBuilder({ mode: "template", isNew: true })}
    />
  );
}

type ConsoleStatus = "loading" | "unavailable" | "empty" | "error" | "ready";
type PlanStatus = "loading" | "error" | "ready";

/**
 * Each view sets its own header, so the header switches with the view. The
 * console lists the templates on mount, selects the first, and loads the
 * selected template's plan. When the backend reports the workflow library
 * unavailable, nothing is selected and no plan is loaded.
 */
function ConsoleView({
  onModifyPlan,
  onNewWorkflow,
}: {
  onModifyPlan: (mode: BuilderMode) => void;
  onNewWorkflow: () => void;
}) {
  usePageHeader({ title: "Workflow Console" });
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [status, setStatus] = useState<ConsoleStatus>("loading");
  const [selectedId, setSelectedId] = useState<string>();
  const [planStatus, setPlanStatus] = useState<PlanStatus>("loading");
  const [plan, setPlan] = useState<WorkflowPlan | null>(null);

  useEffect(() => {
    let ignore = false;
    api
      .listWorkflows()
      .then((res) => {
        if (ignore) return;
        if (!res.available) {
          setStatus("unavailable");
          return;
        }
        setWorkflows(res.workflows);
        setStatus(res.workflows.length > 0 ? "ready" : "empty");
        setSelectedId(res.workflows[0]?.workflow_id);
      })
      .catch(() => {
        if (!ignore) setStatus("error");
      });
    return () => {
      ignore = true;
    };
  }, []);

  // Each selection fetches its detail again; a response for a card no longer
  // selected is dropped.
  useEffect(() => {
    if (selectedId === undefined) return;
    let ignore = false;
    setPlanStatus("loading");
    setPlan(null);
    api
      .getWorkflow(selectedId)
      .then((detail) => {
        if (ignore) return;
        setPlan(toPlan(detail));
        setPlanStatus("ready");
      })
      .catch(() => {
        if (!ignore) setPlanStatus("error");
      });
    return () => {
      ignore = true;
    };
  }, [selectedId]);

  return (
    <LayoutWorkflowConsole
      status={status}
      templates={workflows.map(toTemplate)}
      selectedId={selectedId}
      onSelect={setSelectedId}
      planStatus={planStatus}
      plan={plan}
      onModifyPlan={onModifyPlan}
      onNewWorkflow={onNewWorkflow}
    />
  );
}

function BuilderView({ start }: { start: BuilderStart }) {
  usePageHeader({ trail: ["Workflow Builder"] });
  const [mode, setMode] = useState(start.mode);
  // Nothing can change the structure yet, so the template opened from "Edit
  // the template" starts with placeholder unsaved changes, and switching to
  // this run asks first (D.2d). Switching drops or saves them, so it asks once.
  const [unsaved, setUnsaved] = useState(start.mode === "template" && !start.isNew);
  const changeMode = (next: BuilderMode) => {
    setMode(next);
    if (next === "run") setUnsaved(false);
  };
  return (
    <LayoutWorkflowBuilder
      // Placeholder name until naming a new workflow is designed. D.3 keeps the template's.
      name={BUILDER_TEMPLATE_NAME}
      mode={mode}
      onModeChange={changeMode}
      unsavedChanges={unsaved ? UNSAVED_CHANGES : undefined}
      version={TEMPLATE_VERSION}
      nextVersion={NEXT_TEMPLATE_VERSION}
      skillGroups={SKILL_GROUPS}
      versions={WORKFLOW_VERSIONS}
      versionDetails={VERSION_DETAILS}
      // Selection isn't interactive yet, so each mode shows its frame's
      // selected node: Corrosion changing this run (D.2a), Radiation Damage
      // changing the template (D.2b).
      nodes={start.isNew ? [] : mode === "run" ? RUN_NODES : BUILDER_NODES}
      wires={start.isNew ? [] : BUILDER_WIRES}
      inspected={start.isNew ? null : INSPECTED_NODE}
      tweaked={start.isNew ? null : TWEAKED_STEP}
    />
  );
}
