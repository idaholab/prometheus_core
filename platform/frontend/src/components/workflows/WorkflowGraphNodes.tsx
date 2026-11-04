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

import type { ComponentProps } from "react";
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { StatusPill } from "../ui/StatusPill";
import { SKILL_TONE_DOT_CLASSES, type SkillTone } from "./skillTone";

export type WorkflowStepStatus = "done" | "queued" | "blocked";

const STATUS_PILL: Record<WorkflowStepStatus, ComponentProps<typeof StatusPill>> = {
  done: { label: "Done", tone: "success" },
  queued: { label: "Queued", tone: "warning" },
  blocked: { label: "Blocked", tone: "neutral" },
};

export interface AgentNodeData extends Record<string, unknown> {
  name: string;
  status: WorkflowStepStatus;
  input: string;
  output: string;
  /** Display string, e.g. "40s". */
  est: string;
  /** Node width in px; D.1 sizes nodes to their content. */
  width: number;
}

export interface CheckpointNodeData extends Record<string, unknown> {
  name: string;
}

export interface SkillNodeData extends Record<string, unknown> {
  name: string;
  /** Colour of the dot beside the name, e.g. green for every node in D.2. */
  tone: SkillTone;
  input: string;
  /** Colour of the input's port dot, by the kind of value, e.g. cyan for material data. */
  inputTone: SkillTone;
  output: string;
  /** Colour of the output's port dot, by the kind of value, e.g. green for an analysis result. */
  outputTone: SkillTone;
  /** Node width in px. */
  width: number;
  /** Drawn as the ghost of a skill being dragged onto the canvas (D.4). */
  ghost?: boolean;
}

export interface ConnectEndpointData extends Record<string, unknown> {
  /** Hint beside the endpoint, e.g. "drop to connect →". */
  label: string;
}

export type AgentNode = Node<AgentNodeData, "agent">;
export type CheckpointNode = Node<CheckpointNodeData, "checkpoint">;
export type SkillNode = Node<SkillNodeData, "skill">;
export type ConnectEndpointNode = Node<ConnectEndpointData, "connect">;

/** Wires attach at the top and bottom centre. The handles are only anchors, so they're hidden. */
const HANDLE_CLASS = "!size-px !min-h-0 !min-w-0 !border-0 !bg-transparent";

/**
 * A label and its value, e.g. "IN material_id". Labels share a fixed width so
 * the values line up. Sizes go on each span: the base layer sets span
 * font-size, so it isn't inherited.
 */
function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-w-0 items-center gap-1.5 font-mono">
      <span className="w-4.5 shrink-0 text-[8.5px] leading-3 text-base-content/50">{label}</span>
      <span className="min-w-0 flex-1 truncate text-[9px] leading-3 text-base-content/70">{value}</span>
    </div>
  );
}

/** One agent step (Figma D.1): name and status, input and output ports, and estimated time. */
export function WorkflowAgentNode({ data }: NodeProps<AgentNode>) {
  return (
    <div
      className="flex flex-col gap-2 rounded-lg border border-base-content/15 bg-base-100 px-3 py-2.5"
      style={{ width: data.width }}
    >
      <Handle type="target" position={Position.Top} isConnectable={false} className={HANDLE_CLASS} />
      <div className="flex min-w-0 items-center justify-between gap-1.5">
        <span className="min-w-0 truncate text-xs font-semibold leading-4 text-base-content" title={data.name}>
          {data.name}
        </span>
        <StatusPill {...STATUS_PILL[data.status]} />
      </div>
      <DetailRow label="IN" value={data.input} />
      <DetailRow label="OUT" value={data.output} />
      <DetailRow label="EST" value={data.est} />
      <Handle type="source" position={Position.Bottom} isConnectable={false} className={HANDLE_CLASS} />
    </div>
  );
}

/**
 * A review checkpoint (Figma D.1): a diamond, with its name to the right.
 * The box is sized so the diamond's rounded tips touch its top and bottom
 * edges, where the wires attach: a 32px square turned 45° with 4px corners
 * reaches 21px from its centre.
 */
export function WorkflowCheckpointNode({ data }: NodeProps<CheckpointNode>) {
  return (
    <div className="relative flex size-10.5 items-center justify-center">
      <Handle type="target" position={Position.Top} isConnectable={false} className={HANDLE_CLASS} />
      <span aria-hidden="true" className="size-8 shrink-0 rotate-45 rounded border-[1.5px] border-primary bg-primary/20" />
      <div className="absolute left-full top-1/2 ml-2 flex -translate-y-1/2 flex-col whitespace-nowrap font-mono uppercase">
        <span className="text-[9px] font-medium leading-3 tracking-[0.03em] text-base-content">{data.name}</span>
        <span className="text-[7.5px] leading-3 tracking-[0.04em] text-base-content/50">Checkpoint</span>
      </div>
      <Handle type="source" position={Position.Bottom} isConnectable={false} className={HANDLE_CLASS} />
    </div>
  );
}

/** A port dot on a skill node, coloured by the kind of value. Decorative: the row's text carries the meaning. */
function PortDot({ tone }: { tone: SkillTone }) {
  return <span aria-hidden="true" className={`size-1 shrink-0 rounded-full ${SKILL_TONE_DOT_CLASSES[tone]}`} />;
}

/** Border and fill for each look a skill node can have. */
function skillNodeClasses(ghost: boolean, selected: boolean): string {
  if (ghost) return "border-dashed border-primary bg-base-100/60";
  if (selected) return "border-primary bg-base-100 ring-1 ring-primary";
  return "border-base-content/15 bg-base-100";
}

/**
 * One skill step on the Builder canvas (Figma D.2): name and status dot, then
 * its input and output, each led by a port dot. `selected` (set by the graph)
 * gives it D.2's selected style: a primary border and ring.
 *
 * With `ghost`, it's the skill being dragged onto the canvas (D.4): a dashed
 * primary outline, dimmed contents, and its input port shown as a ringed dot
 * at its bottom-left corner, ready to connect.
 */
export function WorkflowSkillNode({ data, selected }: NodeProps<SkillNode>) {
  const ghost = data.ghost ?? false;
  return (
    <div
      className={`relative flex flex-col gap-2 rounded-lg border px-3 py-2.5 ${skillNodeClasses(ghost, selected)}`}
      style={{ width: data.width }}
    >
      <Handle type="target" position={Position.Top} isConnectable={false} className={HANDLE_CLASS} />
      <div className={`flex flex-col gap-2 ${ghost ? "opacity-70" : ""}`}>
        <div className="flex min-w-0 items-center justify-between gap-1.5">
          <span className="min-w-0 truncate text-xs font-semibold leading-4 text-base-content" title={data.name}>
            {data.name}
          </span>
          <span aria-hidden="true" className={`size-1.5 shrink-0 rounded-full ${SKILL_TONE_DOT_CLASSES[data.tone]}`} />
        </div>
        <div className="flex items-center gap-1.5">
          <PortDot tone={data.inputTone} />
          <div className="min-w-0 flex-1">
            <DetailRow label="IN" value={data.input} />
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <PortDot tone={data.outputTone} />
          <div className="min-w-0 flex-1">
            <DetailRow label="OUT" value={data.output} />
          </div>
        </div>
      </div>
      {ghost && (
        <span
          aria-hidden="true"
          className="absolute bottom-0 left-0 size-2.5 -translate-x-1/2 translate-y-1/2 rounded-full border-[1.5px] border-primary bg-base-content/80"
        />
      )}
      <Handle type="source" position={Position.Bottom} isConnectable={false} className={HANDLE_CLASS} />
    </div>
  );
}

/**
 * Loose end of a wire being drawn (Figma D.2): a ringed dot, with a hint to
 * its right. The wire attaches at the dot's centre.
 */
export function WorkflowConnectEndpoint({ data }: NodeProps<ConnectEndpointNode>) {
  return (
    <div className="relative flex size-2.5 items-center justify-center">
      <Handle type="target" position={Position.Top} isConnectable={false} className={`${HANDLE_CLASS} top-1/2!`} />
      <span aria-hidden="true" className="size-2.5 rounded-full border-[1.5px] border-primary bg-base-content/80" />
      <span className="absolute left-full top-1/2 ml-2.5 -translate-y-1/2 whitespace-nowrap font-mono text-[9px] leading-3 tracking-[0.04em] text-base-content/50">
        {data.label}
      </span>
    </div>
  );
}
