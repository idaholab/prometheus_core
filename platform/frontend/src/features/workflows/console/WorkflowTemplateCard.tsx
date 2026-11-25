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

import { Diamond, ShieldCheck, Zap } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Tag } from "@/components/ui/Tag";
import type { WorkflowComplexity } from "@/lib/api/types";

export interface WorkflowTemplate {
  id: string;
  name: string;
  /** Null when the template sets none; the complexity tag is hidden. */
  complexity: WorkflowComplexity | null;
  checkpoints: number;
  agents: number;
  /** Display string, e.g. "1h 30m"; null when the template sets none. */
  runtime: string | null;
  /** Speed-up over the manual baseline, e.g. "4.2x"; null hides the speed-up strip. */
  speedup: string | null;
  /** The chat pauses for the user's approval before the workflow runs. */
  requiresApproval: boolean;
  /** Shown for an agent-card workflow; null hides it. */
  owner: string | null;
}

interface WorkflowTemplateCardProps {
  template: WorkflowTemplate;
  selected?: boolean;
  onSelect?: () => void;
}

/**
 * A workflow template on the Workflow Console (Figma D.1): name, complexity,
 * approval and checkpoint count, owner, agent and runtime figures, the speed-up
 * strip, and a select button. A figure the template doesn't set is left out,
 * never shown as a placeholder. The card itself isn't a click target; only the
 * button is.
 */
export function WorkflowTemplateCard({ template, selected = false, onSelect }: WorkflowTemplateCardProps) {
  const { name, complexity, checkpoints, agents, runtime, speedup, requiresApproval, owner } = template;

  return (
    <article
      className={`card rounded-lg bg-base-200 ${
        selected ? "border-[1.5px] border-primary" : "border border-base-content/10"
      }`}
    >
      <div className="card-body min-w-0 gap-3 p-4">
        <div className="flex min-w-0 flex-col gap-1">
          <h3 className="m-0 truncate text-sm font-bold text-base-content" title={name}>
            {name}
          </h3>
          {/* Sizes go on each span: the base layer sets span font-size, so it isn't inherited. */}
          <div className="flex flex-wrap items-center gap-2">
            {complexity !== null && <Tag label={complexity} />}
            {requiresApproval && <Tag label="Needs approval" icon={ShieldCheck} />}
            <span className="inline-flex items-center gap-1 text-[10px] font-bold uppercase leading-3 text-primary">
              <Diamond aria-hidden="true" size={9} className="fill-current" />
              {checkpoints} {checkpoints === 1 ? "checkpoint" : "checkpoints"}
            </span>
          </div>
        </div>

        <dl className="m-0 flex flex-col gap-1 text-[11px]">
          {owner !== null && (
            <div className="flex justify-between gap-2">
              <dt className="text-base-content/60">Owner</dt>
              <dd className="m-0 min-w-0 truncate text-base-content" title={owner}>
                {owner}
              </dd>
            </div>
          )}
          <div className="flex justify-between gap-2">
            <dt className="text-base-content/60">Agents Assigned</dt>
            <dd className="m-0 text-base-content">
              {agents} {agents === 1 ? "Agent" : "Agents"}
            </dd>
          </div>
          {runtime !== null && (
            <div className="flex justify-between gap-2">
              <dt className="text-base-content/60">Est. Runtime</dt>
              <dd className="m-0 text-base-content">{runtime}</dd>
            </div>
          )}
        </dl>

        {speedup !== null && (
          <div className="flex items-center justify-between gap-2 rounded bg-base-content/5 px-3 py-2">
            <span className="inline-flex items-center gap-1 text-[10px] leading-3 text-info">
              <Zap aria-hidden="true" size={10} className="fill-current text-warning" />
              {speedup} faster
            </span>
            <span className="text-[10px] leading-3 text-base-content/40">vs baseline</span>
          </div>
        )}

        {selected ? (
          <Button label="Selected" variant="primary" size="sm" wide onClick={onSelect} />
        ) : (
          <Button label="Select Template" outline size="sm" wide onClick={onSelect} />
        )}
      </div>
    </article>
  );
}
