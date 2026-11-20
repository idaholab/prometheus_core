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
import { SectionLabel } from "@/components/ui/SectionLabel";
import type { InspectorField } from "./NodeInspector";
import { SKILL_TONE_DOT_CLASSES, type SkillTone } from "@/features/workflows/skillTone";

/** A step as "this run" mode shows it: which agent runs it and the settings a run may change. */
export interface TweakedStep {
  name: string;
  /** Colour of the dot beside the name, as on the node's canvas card. */
  tone: SkillTone;
  /** The agent that runs the step, e.g. "Corrosion Agent v2.1". Listed first in the dropdown. */
  agent: string;
  /** The other agents that can run it, offered in the dropdown. */
  agentOptions: string[];
  settings: InspectorField[];
}

/** Same small mono label as the Node Inspector's fields (D.2). */
const LABEL_CLASSES = "font-mono text-[9px] uppercase tracking-[0.04em] text-base-content/50";

function Setting({ field }: { field: InspectorField }) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className={LABEL_CLASSES}>
        {field.name}
      </label>
      <input
        id={id}
        type="text"
        className="input input-sm w-full font-mono text-xs"
        defaultValue={field.value}
        placeholder={field.value === undefined ? "— optional —" : undefined}
      />
    </div>
  );
}

/**
 * Node Inspector column in "this run" mode (Figma PPLT-409 D.2a, from D.7's
 * Tweak Step): the step's name and dot, its agent, its settings, a toggle to
 * skip it for this run, and a note that structural changes need the template
 * mode. There's no Remove Node: a run can't change the workflow's structure.
 *
 * Display only: the dropdown, fields and toggle change nothing yet (PPLT-230).
 */
export function TweakStepInspector({ step }: { step: TweakedStep | null }) {
  const agentId = useId();
  const skipId = useId();

  return (
    <div className="flex flex-col gap-4">
      <SectionLabel variant="panel">Tweak Step</SectionLabel>
      {step ? (
        <>
          <div className="flex min-w-0 items-center gap-2">
            <span aria-hidden="true" className={`size-2 shrink-0 rounded-full ${SKILL_TONE_DOT_CLASSES[step.tone]}`} />
            <p className="m-0 min-w-0 truncate text-[15px] font-semibold text-base-content" title={step.name}>
              {step.name}
            </p>
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor={agentId} className={LABEL_CLASSES}>
              Agent
            </label>
            <select id={agentId} className="select select-sm w-full font-mono text-xs" defaultValue={step.agent}>
              {[step.agent, ...step.agentOptions.filter((agent) => agent !== step.agent)].map((agent) => (
                <option key={agent}>{agent}</option>
              ))}
            </select>
          </div>
          {step.settings.map((field) => (
            <Setting key={field.name} field={field} />
          ))}
          <div className="flex items-center justify-between gap-3">
            <label htmlFor={skipId} className="text-xs text-base-content">
              Skip this step for this run
            </label>
            <input id={skipId} type="checkbox" className="toggle toggle-sm toggle-primary" />
          </div>
        </>
      ) : (
        // Sizes go on each p: the base layer sets p font-size, so it isn't inherited.
        <div className="flex flex-col gap-1 font-mono text-base-content/50">
          <p className="m-0 text-[10px]">No step selected.</p>
          <p className="m-0 text-[10px]">Click a step to tweak it for this run.</p>
        </div>
      )}
      <p className="m-0 border-t border-base-content/10 pt-4 text-[11px] text-base-content/60">
        To add, wire or remove steps, switch to "the template".
      </p>
    </div>
  );
}
