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
import { Bot, Cpu, FolderOpen, PanelRight } from "lucide-react";
import { EmptyState } from "@/components/ui/EmptyState";
import { api } from "@/lib/api/client";
import { useChatState } from "@/lib/store/chat";
import type { ArtifactMeta } from "@/lib/api/types";
import { LiveAgentPanel } from "../LiveAgentPanel";
import { ActiveJobsPanel } from "./ActiveJobsPanel";

type StatusTab = "agents" | "jobs" | "artifacts";

/** Every artifact in the open conversation's transcript, newest last, deduped
 * by id. A resumed conversation gives each assistant turn the artifacts it
 * produced (see `itemsFromTranscript` in `lib/store/chat.ts`), so this matches
 * the live session. */
function useConversationArtifacts(): ArtifactMeta[] {
  const { items } = useChatState();
  const byId = new Map<string, ArtifactMeta>();
  for (const item of items) {
    if (item.kind !== "assistant") continue;
    for (const artifact of item.artifacts) byId.set(artifact.artifact_id, artifact);
  }
  return [...byId.values()];
}

/** A `uq` artifact is a UQ notebook: open its baked HTML report (notebook-render,
 * same-origin `/notebook`, same URL the inline UQ viewer uses) rather than
 * downloading the raw `.ipynb` bytes from the content proxy. */
function artifactHref(artifact: ArtifactMeta): string {
  if (artifact.render_hint === "uq") return `/notebook/render/${artifact.artifact_id}`;
  return api.artifactContentUrl(artifact.artifact_id);
}

function ArtifactCard({ artifact }: { artifact: ArtifactMeta }) {
  return (
    <a
      href={artifactHref(artifact)}
      target="_blank"
      rel="noreferrer"
      className="card border border-base-300 bg-base-200 transition-colors hover:border-primary/40 hover:bg-base-300"
    >
      <div className="card-body gap-1.5 p-3">
        <div className="flex items-start justify-between gap-2">
          <span className="min-w-0 truncate text-sm font-semibold text-base-content">
            {artifact.name}
          </span>
          <span className="badge badge-outline badge-sm shrink-0 border-base-300 font-mono text-[10px] text-primary">
            {artifact.render_hint}
          </span>
        </div>
        {artifact.description && (
          <p className="m-0 line-clamp-2 text-xs leading-snug text-base-content/60">
            {artifact.description}
          </p>
        )}
      </div>
    </a>
  );
}

/** A single square button in the collapsed icon rail. */
function RailButton({
  active,
  label,
  size = 40,
  onClick,
  children,
}: {
  active?: boolean;
  label: string;
  size?: 32 | 40;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      className={`flex shrink-0 items-center justify-center rounded-lg transition-colors ${
        size === 32 ? "size-8" : "size-10"
      } ${
        active
          ? "bg-primary/15 text-primary"
          : "text-base-content/60 hover:bg-base-300 hover:text-base-content"
      }`}
    >
      {children}
    </button>
  );
}

interface StatusPanelProps {
  /** When true, render the 64px icon rail instead of the full panel. */
  collapsed: boolean;
  /** Collapse the panel to the icon rail. */
  onCollapse: () => void;
  /** Expand the panel back to its full width. */
  onExpand: () => void;
}

/**
 * Right-hand status rail for Home: a DaisyUI tab bar switching between the Live
 * Agents Arena (default), Active Jobs and Artifacts. Agents and Artifacts are live
 * off the conversation transcript; Active Jobs polls the backend's Task Graph.
 *
 * Collapses to a 64px icon rail (Figma `status-rail-collapsed`), symmetric with
 * the left sidebar: a PanelRight toggle on top, then one icon per tab. Clicking
 * a tab icon expands the rail straight to that tab. The open/closed width lives
 * on Home's `<aside>`; `tab` stays here so it survives a collapse/expand.
 */
export function StatusPanel({ collapsed, onCollapse, onExpand }: StatusPanelProps) {
  const [tab, setTab] = useState<StatusTab>("agents");
  const artifacts = useConversationArtifacts();

  if (collapsed) {
    const openTo = (next: StatusTab) => {
      setTab(next);
      onExpand();
    };
    return (
      <div className="flex h-full min-h-0 w-full flex-col items-center gap-2.5 bg-base-200 pt-5">
        <RailButton size={32} label="Expand status panel" onClick={onExpand}>
          <PanelRight size={16} />
        </RailButton>
        <div className="h-2" aria-hidden />
        <RailButton active={tab === "agents"} label="Live Agents Arena" onClick={() => openTo("agents")}>
          <Bot size={20} />
        </RailButton>
        <RailButton active={tab === "jobs"} label="Active Jobs" onClick={() => openTo("jobs")}>
          <Cpu size={20} />
        </RailButton>
        <RailButton
          active={tab === "artifacts"}
          label={artifacts.length > 0 ? `Artifacts (${artifacts.length})` : "Artifacts"}
          onClick={() => openTo("artifacts")}
        >
          <FolderOpen size={20} />
        </RailButton>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center justify-between px-6 pt-6">
        <div role="tablist" className="tabs tabs-border">
          <button
            role="tab"
            className={`tab text-xs font-bold uppercase tracking-wide ${tab === "agents" ? "tab-active" : ""}`}
            onClick={() => setTab("agents")}
          >
            Live Agents Arena
          </button>
          <button
            role="tab"
            className={`tab text-xs font-bold uppercase tracking-wide ${tab === "jobs" ? "tab-active" : ""}`}
            onClick={() => setTab("jobs")}
          >
            Active Jobs
          </button>
          <button
            role="tab"
            className={`tab text-xs font-bold uppercase tracking-wide ${tab === "artifacts" ? "tab-active" : ""}`}
            onClick={() => setTab("artifacts")}
          >
            Artifacts{artifacts.length > 0 && ` (${artifacts.length})`}
          </button>
        </div>
        <RailButton size={32} label="Collapse status panel" onClick={onCollapse}>
          <PanelRight size={18} />
        </RailButton>
      </div>

      {tab === "agents" ? (
        <LiveAgentPanel />
      ) : tab === "jobs" ? (
        <ActiveJobsPanel />
      ) : artifacts.length === 0 ? (
        <EmptyState
          icon={<FolderOpen size={32} />}
          title="No Artifacts Yet"
          hint="Generated artifacts will display here"
        />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-6 py-4">
          {artifacts.map((artifact) => (
            <ArtifactCard key={artifact.artifact_id} artifact={artifact} />
          ))}
        </div>
      )}
    </div>
  );
}
