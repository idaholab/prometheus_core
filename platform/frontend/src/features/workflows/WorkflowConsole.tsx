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

import { SectionLabel } from "@/components/ui/SectionLabel";
import { WorkflowPlanner, type WorkflowPlan } from "./WorkflowPlanner";
import { WorkflowTemplateCard, type WorkflowTemplate } from "./WorkflowTemplateCard";

interface WorkflowConsoleProps {
  templates: WorkflowTemplate[];
  selectedId?: string;
  /** The selected template's plan. */
  plan: WorkflowPlan;
  /** "Modify Plan" in the planner: opens the Builder. */
  onModifyPlan?: () => void;
}

/**
 * Workflow Console layout (Figma D.1): the template picker, then the execution
 * planner for the selected template. Display only; PageWorkflows supplies the data.
 */
export function WorkflowConsole({ templates, selectedId, plan, onModifyPlan }: WorkflowConsoleProps) {
  return (
    <div className="flex flex-1 flex-col gap-6 overflow-y-auto p-6">
      <section className="flex flex-col gap-3">
        <SectionLabel>Workflow Templates</SectionLabel>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {templates.map((template) => (
            <WorkflowTemplateCard key={template.id} template={template} selected={template.id === selectedId} />
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <SectionLabel>Workflow Execution Planner</SectionLabel>
        <WorkflowPlanner plan={plan} onModifyPlan={onModifyPlan} />
      </section>
    </div>
  );
}
