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
import { Button } from "../ui/Button";
import { SectionLabel } from "../ui/SectionLabel";
import { SKILL_TONE_DOT_CLASSES, type SkillTone } from "./skillTone";

export interface InspectorField {
  /** Port name, e.g. "material_id". Uppercased with CSS. */
  name: string;
  /** Where the value comes from, e.g. "from input.material_id". Omit for an unset optional input. */
  value?: string;
}

export interface InspectedNode {
  name: string;
  /** Colour of the dot beside the name, as on the node's canvas card. */
  tone: SkillTone;
  /** e.g. "analyze_radiation_damage". */
  skillId: string;
  inputs: InspectorField[];
  outputs: InspectorField[];
}

/** One input or output: a small mono label over a mono text field. */
function Field({ field }: { field: InspectorField }) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="font-mono text-[9px] uppercase tracking-[0.04em] text-base-content/50">
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

function FieldGroup({ label, fields }: { label: string; fields: InspectorField[] }) {
  return (
    <section className="flex flex-col gap-3">
      <SectionLabel variant="panel" as="h3" className="text-base-content/70">
        {label}
      </SectionLabel>
      {fields.map((field) => (
        <Field key={field.name} field={field} />
      ))}
    </section>
  );
}

/**
 * Node Inspector column of the Builder. With a `node`, the selected state
 * (Figma D.2): the node's name and skill id, a field for each input and
 * output, and Remove Node. Without one, the empty state (D.3).
 *
 * Display only: the fields can be typed in but the edits go nowhere, and
 * Remove Node has no handler yet.
 */
export function NodeInspector({ node }: { node: InspectedNode | null }) {
  return (
    <div className="flex flex-col gap-4">
      <SectionLabel variant="panel">Node Inspector</SectionLabel>
      {node ? (
        <>
          <div className="flex flex-col gap-1">
            <div className="flex min-w-0 items-center gap-2">
              <span aria-hidden="true" className={`size-2 shrink-0 rounded-full ${SKILL_TONE_DOT_CLASSES[node.tone]}`} />
              <p className="m-0 min-w-0 truncate text-[15px] font-semibold text-base-content" title={node.name}>
                {node.name}
              </p>
            </div>
            <p className="m-0 break-all font-mono text-[9px] text-base-content/50">skill_id: {node.skillId}</p>
          </div>
          <FieldGroup label="Inputs" fields={node.inputs} />
          <FieldGroup label={node.outputs.length === 1 ? "Output" : "Outputs"} fields={node.outputs} />
          <Button label="Remove Node" variant="error" outline wide size="sm" className="mt-1" />
        </>
      ) : (
        // Sizes go on each p: the base layer sets p font-size, so it isn't inherited.
        <div className="flex flex-col gap-1 font-mono text-base-content/50">
          <p className="m-0 text-[10px]">No node selected.</p>
          <p className="m-0 text-[10px]">Click a node to edit its inputs.</p>
        </div>
      )}
    </div>
  );
}
