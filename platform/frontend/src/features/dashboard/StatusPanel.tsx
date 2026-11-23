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

import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, Cpu, Download, FolderOpen, PanelRight } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { ElementList, artifactToElement, isPanelOnly } from "@/features/artifacts";
import { EmptyState } from "@/components/ui/EmptyState";
import { Tag } from "@/components/ui/Tag";
import { api } from "@/lib/api/client";
import { useChatState, type ChatState } from "@/features/chat";
import type { ArtifactMeta } from "@/lib/api/types";

type StatusTab = "jobs" | "artifacts";

/** Every artifact in the open conversation's transcript, newest last, deduped
 * by id. A resumed conversation gives each assistant turn the artifacts it
 * produced (see `itemsFromTranscript` in `features/chat/store/chat.ts`), so this matches
 * the live session. */
function useConversationArtifacts(items: ChatState["items"]): ArtifactMeta[] {
  const byId = new Map<string, ArtifactMeta>();
  for (const item of items) {
    if (item.kind !== "assistant") continue;
    for (const artifact of item.artifacts) byId.set(artifact.artifact_id, artifact);
  }
  return [...byId.values()];
}

/** Render hints with an in-panel viewer; others open the raw file in a tab. */
const PANEL_VIEWABLE = new Set(["code", "report", "json", "table", "image", "pdf"]);

function canOpenInPanel(artifact: ArtifactMeta): boolean {
  return PANEL_VIEWABLE.has(artifact.render_hint);
}

/**
 * Calls `onArrive` with the newest panel-only artifact that arrives live, so
 * the panel can open it. Artifacts that come with a conversation's transcript
 * (a sidebar switch, or recovering the open conversation after a reload) are
 * not new: everything seen while a resume is in flight, or in the first render,
 * is only recorded.
 */
function usePanelArrivals(
  artifacts: ArtifactMeta[],
  resuming: boolean,
  onArrive: (artifact: ArtifactMeta) => void,
): void {
  const seen = useRef<Set<string> | null>(null);
  useEffect(() => {
    const first = seen.current === null;
    const known = (seen.current ??= new Set());
    const unseen = artifacts.filter((a) => !known.has(a.artifact_id));
    for (const a of unseen) known.add(a.artifact_id);
    if (first || resuming) return;
    const newest = [...unseen].reverse().find((a) => isPanelOnly(a) && canOpenInPanel(a));
    if (newest) onArrive(newest);
  }, [artifacts, resuming, onArrive]);
}

function ArtifactViewer({ artifact, onBack }: { artifact: ArtifactMeta; onBack: () => void }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-base-300 px-4 py-2">
        <Button
          variant="ghost"
          size="xs"
          icon={<ChevronLeft />}
          ariaLabel="Back to artifacts"
          onClick={onBack}
        />
        <span className="min-w-0 flex-1 truncate text-sm font-semibold">{artifact.name}</span>
        <a
          href={api.artifactContentUrl(artifact.artifact_id)}
          target="_blank"
          rel="noreferrer"
          className="inline-flex size-6 items-center justify-center rounded text-base-content/60 hover:bg-base-300 hover:text-base-content"
          aria-label={`Open ${artifact.name} in a new tab`}
          title="Open raw file"
        >
          <Download size={14} />
        </a>
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-4 py-3">
        <ElementList elements={[artifactToElement(artifact)]} />
      </div>
    </div>
  );
}

function ArtifactCard({ artifact, onOpen }: { artifact: ArtifactMeta; onOpen: () => void }) {
  const viewable = canOpenInPanel(artifact);
  return (
    <a
      href={api.artifactContentUrl(artifact.artifact_id)}
      target="_blank"
      rel="noreferrer"
      onClick={(event) => {
        if (!viewable) return;
        event.preventDefault();
        onOpen();
      }}
      className="card border border-base-300 bg-base-200 transition-colors hover:border-primary/40 hover:bg-base-300"
    >
      <div className="card-body gap-1.5 p-3">
        <div className="flex items-start justify-between gap-2">
          <span className="min-w-0 truncate text-sm font-semibold text-base-content">{artifact.name}</span>
          <Tag mono label={artifact.render_hint} />
        </div>
        {artifact.description && (
          <p className="m-0 line-clamp-2 text-xs leading-snug text-base-content/60">{artifact.description}</p>
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
 * Right-hand status rail for Home: a DaisyUI tab bar switching between Active
 * Jobs and Artifacts. Artifacts are live off the conversation transcript; job
 * cards get wired in as that data source lands.
 *
 * Collapses to a 64px icon rail (Figma `status-rail-collapsed`), symmetric with
 * the left sidebar: a PanelRight toggle on top, then one icon per tab. Clicking
 * a tab icon expands the rail straight to that tab. The open/closed width lives
 * on LayoutHome's `<aside>`; `tab` stays here so it survives a collapse/expand.
 */
export function StatusPanel({ collapsed, onCollapse, onExpand }: StatusPanelProps) {
  const [tab, setTab] = useState<StatusTab>("jobs");
  const { items, resumingConversationId } = useChatState();
  const artifacts = useConversationArtifacts(items);
  const resuming = resumingConversationId !== null;
  const [openId, setOpenId] = useState<string | null>(null);
  const opened = artifacts.find((a) => a.artifact_id === openId) ?? null;

  // A new panel-only artifact (e.g. a generated MOOSE input) opens itself,
  // since the message no longer shows it inline.
  const openArrival = useCallback(
    (artifact: ArtifactMeta) => {
      setTab("artifacts");
      setOpenId(artifact.artifact_id);
      if (collapsed) onExpand();
    },
    [collapsed, onExpand],
  );
  usePanelArrivals(artifacts, resuming, openArrival);

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

      {tab === "jobs" ? (
        <EmptyState
          icon={<Cpu size={32} />}
          title="No Active Jobs"
          hint="Assigned solver pipelines will display here"
        />
      ) : artifacts.length === 0 ? (
        <EmptyState
          icon={<FolderOpen size={32} />}
          title="No Artifacts Yet"
          hint="Generated artifacts will display here"
        />
      ) : opened ? (
        <ArtifactViewer artifact={opened} onBack={() => setOpenId(null)} />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-6 py-4">
          {artifacts.map((artifact) => (
            <ArtifactCard
              key={artifact.artifact_id}
              artifact={artifact}
              onOpen={() => setOpenId(artifact.artifact_id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
