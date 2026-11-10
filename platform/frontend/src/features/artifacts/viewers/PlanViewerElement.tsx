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

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { ViewerProps } from "@/features/artifacts/elements";

interface PlanStepObject {
  name?: string;
  agent?: string;
  description?: string;
  prompt?: string;
}

type PlanStep = string | PlanStepObject;

interface Plan {
  steps?: PlanStep[];
  workflow_type?: string;
  estimated_duration_seconds?: number;
  intent?: string;
  skills?: string[];
  selection_source?: string;
  workflow_id?: string;
}

interface PlanViewerProps {
  plan?: Plan;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.round(seconds / 60);
  return `${minutes}m`;
}

function stepLabel(step: PlanStep): { title: string; subtitle?: string } {
  if (typeof step === "string") return { title: step };
  const title = step.name ?? step.agent ?? step.description ?? step.prompt ?? "Step";
  const subtitle =
    step.name && step.description
      ? step.description
      : step.agent && step.name
        ? step.agent
        : undefined;
  return { title, subtitle };
}

export function PlanViewerElement({ element }: ViewerProps) {
  const props = ((element as { props?: PlanViewerProps }).props) ?? {};
  const plan = props.plan ?? {};
  const steps = plan.steps ?? [];
  const workflowType = plan.workflow_type ?? "sequential";
  const estimatedDuration = plan.estimated_duration_seconds;
  const intent = plan.intent ?? "";
  const skills = plan.skills ?? [];
  const selectionSource = plan.selection_source;
  const workflowId = plan.workflow_id;

  const [detailsOpen, setDetailsOpen] = useState(false);
  const hasDetails = Boolean(workflowId || selectionSource || skills.length);

  return (
    <div className="border border-base-300 rounded-lg p-4 my-2 bg-base-200/40 space-y-3 max-w-2xl">
      <div className="flex items-center gap-2 flex-wrap">
        <h3 className="text-base font-semibold">Execution Plan</h3>
        <span className="badge badge-sm badge-ghost">{workflowType}</span>
        {estimatedDuration != null && (
          <span className="badge badge-sm badge-ghost">~{formatDuration(estimatedDuration)}</span>
        )}
      </div>

      {intent && (
        <p className="text-sm text-base-content/60 italic">{intent}</p>
      )}

      <ol className="space-y-2">
        {steps.map((step, i) => {
          const { title, subtitle } = stepLabel(step);
          return (
            <li key={i} className="flex items-start gap-2.5">
              <span className="text-sm text-base-content/50 w-5 shrink-0 tabular-nums">{i + 1}.</span>
              <div className="flex-1 min-w-0">
                <span className="text-sm text-base-content block">{title}</span>
                {subtitle && (
                  <p className="text-xs text-base-content/50 mt-0.5">{subtitle}</p>
                )}
              </div>
            </li>
          );
        })}
      </ol>

      {hasDetails && (
        <div className="pt-1">
          <button
            className="flex items-center gap-1 text-xs text-base-content/60 hover:text-base-content"
            onClick={() => setDetailsOpen((v) => !v)}
          >
            {detailsOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            {detailsOpen ? "Hide details" : "Show details"}
          </button>
          {detailsOpen && (
            <div className="mt-2 space-y-1 text-xs text-base-content/60">
              {workflowId && <p>Workflow ID: <code className="text-base-content/80">{workflowId}</code></p>}
              {selectionSource && <p>Selection source: {selectionSource}</p>}
              {skills.length > 0 && <p>Skills: {skills.join(" → ")}</p>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
