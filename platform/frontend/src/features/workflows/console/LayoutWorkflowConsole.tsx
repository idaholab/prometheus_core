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

import { Plus, Workflow } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { SectionLabel } from "@/components/ui/SectionLabel";
import type { BuilderMode } from "@/features/workflows/builderMode";
import { WorkflowPlanner, type WorkflowPlan } from "./WorkflowPlanner";
import { WorkflowTemplateCard, type WorkflowTemplate } from "./WorkflowTemplateCard";

interface WorkflowConsoleProps {
  /**
   * The template list's load state; "empty" is a loaded list with no templates.
   * "unavailable": the backend answered available:false because the
   * client-agent workflow library is down or off.
   */
  status: "loading" | "unavailable" | "empty" | "error" | "ready";
  templates: WorkflowTemplate[];
  selectedId?: string;
  /** A template card's select button: the template's id. */
  onSelect?: (id: string) => void;
  /** The selected template's plan load state. */
  planStatus: "loading" | "error" | "ready";
  /** The selected template's plan, once loaded. */
  plan: WorkflowPlan | null;
  /** "Modify Plan" in the planner: opens the Builder in the mode picked. */
  onModifyPlan?: (mode: BuilderMode) => void;
  /** "+ New Workflow" beside the templates heading. */
  onNewWorkflow?: () => void;
}

/**
 * Workflow Console layout (Figma D.1): the template picker, then the execution
 * planner for the selected template, or the list's load state. Display only;
 * PageWorkflows supplies the data.
 */
export function LayoutWorkflowConsole({
  status,
  templates,
  selectedId,
  onSelect,
  planStatus,
  plan,
  onModifyPlan,
  onNewWorkflow,
}: WorkflowConsoleProps) {
  return (
    <div className="flex flex-1 flex-col gap-6 overflow-y-auto p-6">
      <section className="flex flex-col gap-3">
        {/* The button is taller than the heading, so the heading row's height
            is fixed at the heading's and the button overflows it upwards,
            into the page padding, rather than pushing the cards down. */}
        <div className="flex h-4.5 items-end justify-between gap-4">
          <SectionLabel>Workflow Templates</SectionLabel>
          <Button label="New Workflow" icon={<Plus />} outline size="sm" onClick={onNewWorkflow} />
        </div>
        {status === "loading" && (
          <p className="m-0 text-sm text-base-content/60">Loading workflow templates...</p>
        )}
        {status === "unavailable" && (
          <div role="alert" className="alert alert-warning">
            The workflow library is unavailable.
          </div>
        )}
        {status === "empty" && (
          <EmptyState
            icon={<Workflow size={24} />}
            title="No workflow templates are available."
            hint="Workflow templates will display here"
          />
        )}
        {status === "error" && (
          <div role="alert" className="alert alert-error">
            The workflow templates are unavailable.
          </div>
        )}
        {status === "ready" && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {templates.map((template) => (
              <WorkflowTemplateCard
                key={template.id}
                template={template}
                selected={template.id === selectedId}
                onSelect={() => onSelect?.(template.id)}
              />
            ))}
          </div>
        )}
      </section>

      {status === "ready" && selectedId !== undefined && (
        <section className="flex flex-col gap-3">
          <SectionLabel>Workflow Execution Planner</SectionLabel>
          {planStatus === "loading" && (
            <p className="m-0 text-sm text-base-content/60">Loading the workflow plan...</p>
          )}
          {planStatus === "error" && (
            <div role="alert" className="alert alert-error">
              The workflow plan is unavailable.
            </div>
          )}
          {planStatus === "ready" && plan && <WorkflowPlanner plan={plan} onModifyPlan={onModifyPlan} />}
        </section>
      )}
    </div>
  );
}
