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

import React, { useEffect, useRef, useState } from "react";
import {
  ChevronDown, ChevronRight, Eye, EyeOff, Minus,
  Video, Download, SlidersHorizontal, Minimize2,
} from "lucide-react";
import type { PipeRunItem } from "./IFCViewerEngine";

type Item = { key: string; label: string };

export type SectionData = {
  items: readonly Item[];
  visibility: Record<string, boolean>;
  onToggle: (key: string) => void;
};

export type PipeSectionData = {
  runs: readonly PipeRunItem[];
  memberVisibility: Record<string, boolean>;
  onToggleRun: (runKey: string) => void;
  onToggleMember: (memberKey: string) => void;
};

export type DownloadItem =
  | { key: string; label: string; disabled?: boolean; href: string; downloadName?: string; onClick?: undefined }
  | { key: string; label: string; disabled?: boolean; onClick: () => void; href?: undefined; downloadName?: undefined };

type Props = {
  elementItems: readonly Item[];
  elementVisibility: Record<string, boolean>;
  onToggleElement: (key: string) => void;
  equipment?: SectionData;
  pipes?: PipeSectionData;

  onReset: () => void;
  onTop:   () => void;
  onFront: () => void;
  onSide:  () => void;

  downloads?: DownloadItem[];

  disabled?: boolean;
  // Below this width the two panels merge into one. Same UI, just laid out
  // differently for the space available — a full-screen app gets room for
  // two independent panels; a narrow embedded/chat view doesn't.
  breakpoint?: number;
};

const ViewerOverlayPanels: React.FC<Props> = ({
  elementItems, elementVisibility, onToggleElement, equipment, pipes,
  onReset, onTop, onFront, onSide,
  downloads,
  disabled = false,
  breakpoint = 900,
}) => {
  const overlayRef = useRef<HTMLDivElement | null>(null);
  const [isWide, setIsWide] = useState(true);

  useEffect(() => {
    const el = overlayRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      setIsWide(entry.contentRect.width >= breakpoint);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [breakpoint]);

  const [sections, setSections] = useState<Record<string, boolean>>({
    elements: true, equipment: true, pipes: true, camera: true, download: true,
  });
  const toggleSection = (id: string) =>
    setSections((prev) => ({ ...prev, [id]: !prev[id] }));

  const [openRuns, setOpenRuns] = useState<Record<string, boolean>>({});
  const toggleRunOpen = (runKey: string) =>
    setOpenRuns((prev) => ({ ...prev, [runKey]: !prev[runKey] }));

  const [visOpen, setVisOpen]   = useState(true);
  const [ctrlOpen, setCtrlOpen] = useState(true);

  const hasElements  = elementItems.length > 0;
  const hasEquipment = !!equipment && equipment.items.length > 0;
  const hasPipes     = !!pipes && pipes.runs.length > 0;
  const hasDownloads = !!downloads && downloads.length > 0;

  const visibilitySections = (
    <>
      {hasElements && (
        <ListSection
          title="Building Elements"
          items={elementItems}
          visibility={elementVisibility}
          isOpen={sections.elements}
          onToggleOpen={() => toggleSection("elements")}
          onToggleItem={onToggleElement}
          disabled={disabled}
        />
      )}
      {hasEquipment && equipment && (
        <ListSection
          title="Equipment"
          items={equipment.items}
          visibility={equipment.visibility}
          isOpen={sections.equipment}
          onToggleOpen={() => toggleSection("equipment")}
          onToggleItem={equipment.onToggle}
          disabled={disabled}
        />
      )}
      {hasPipes && pipes && (
        <PipeRunSection
          runs={pipes.runs}
          memberVisibility={pipes.memberVisibility}
          onToggleRun={pipes.onToggleRun}
          onToggleMember={pipes.onToggleMember}
          isOpen={sections.pipes}
          onToggleOpen={() => toggleSection("pipes")}
          openRuns={openRuns}
          onToggleRunOpen={toggleRunOpen}
          disabled={disabled}
        />
      )}
    </>
  );

  const controlSections = (
    <>
      <Section title="Camera" icon={<Video size={12} />} isOpen={sections.camera} onToggleOpen={() => toggleSection("camera")}>
        <div className="grid grid-cols-2 gap-1 p-2">
          <button type="button" className="btn btn-primary btn-xs col-span-2" aria-label="Reset view" onClick={onReset} disabled={disabled}>Reset View</button>
          <button type="button" className="btn btn-ghost btn-xs bg-base-300" aria-label="Top view" onClick={onTop} disabled={disabled}>Top</button>
          <button type="button" className="btn btn-ghost btn-xs bg-base-300" aria-label="Front view" onClick={onFront} disabled={disabled}>Front</button>
          <button type="button" className="btn btn-ghost btn-xs col-span-2 bg-base-300" aria-label="Side view" onClick={onSide} disabled={disabled}>Side</button>
        </div>
      </Section>
      {hasDownloads && (
        <Section title="Download" icon={<Download size={12} />} isOpen={sections.download} onToggleOpen={() => toggleSection("download")}>
          <div className="flex flex-col gap-1 p-2">
            {downloads!.map((item) => <DownloadButton key={item.key} item={item} />)}
          </div>
        </Section>
      )}
    </>
  );

  const overlayShell = (children: React.ReactNode) => (
    <div ref={overlayRef} className="absolute inset-0 pointer-events-none">
      {children}
    </div>
  );

  if (isWide) {
    return overlayShell(
      <>
        <div className="pointer-events-auto">
          <FloatingPanel
            title="Visibility"
            icon={<SlidersHorizontal size={14} />}
            side="left"
            open={visOpen}
            onToggleOpen={() => setVisOpen((v) => !v)}
          >
            {visibilitySections}
          </FloatingPanel>
        </div>
        <div className="pointer-events-auto">
          <FloatingPanel
            title="Controls"
            icon={<SlidersHorizontal size={14} />}
            side="right"
            open={ctrlOpen}
            onToggleOpen={() => setCtrlOpen((v) => !v)}
          >
            {controlSections}
          </FloatingPanel>
        </div>
      </>
    );
  }

  return overlayShell(
    <div className="pointer-events-auto">
      <FloatingPanel
        title="Viewer"
        icon={<SlidersHorizontal size={14} />}
        side="left"
        open={visOpen}
        onToggleOpen={() => setVisOpen((v) => !v)}
      >
        {visibilitySections}
        {controlSections}
      </FloatingPanel>
    </div>
  );
};

type FloatingPanelProps = {
  title: string;
  icon: React.ReactNode;
  side: "left" | "right";
  open: boolean;
  onToggleOpen: () => void;
  children: React.ReactNode;
};

const FloatingPanel: React.FC<FloatingPanelProps> = ({ title, icon, side, open, onToggleOpen, children }) => {
  const posClass = side === "left" ? "left-2" : "right-2";

  if (!open) {
    return (
      <button
        type="button"
        aria-label={`Open ${title.toLowerCase()} panel`}
        className={`absolute top-2 ${posClass} z-20 flex items-center justify-center w-9 h-9 bg-base-100/95 backdrop-blur rounded-md shadow-lg border border-base-300 hover:bg-base-200 transition-colors`}
        onClick={onToggleOpen}
      >
        {icon}
      </button>
    );
  }

  return (
    <div className={`absolute top-2 ${posClass} z-20 w-64 max-h-[calc(100%-1rem)] flex flex-col bg-base-100/95 backdrop-blur rounded-md shadow-lg border border-base-300 overflow-hidden`}>
      <button
        type="button"
        aria-label={`Collapse ${title.toLowerCase()} panel`}
        className="w-full flex items-center justify-between px-3 py-2 bg-base-200 border-b border-base-300 hover:bg-base-300 transition-colors"
        onClick={onToggleOpen}
      >
        <div className="flex items-center gap-2 text-sm font-semibold">
          {icon}
          {title}
        </div>
        <Minimize2 size={14} />
      </button>
      <div className="flex-1 overflow-y-auto">{children}</div>
    </div>
  );
};

type SectionProps = {
  title: string;
  icon?: React.ReactNode;
  isOpen: boolean;
  onToggleOpen: () => void;
  children: React.ReactNode;
};

const Section: React.FC<SectionProps> = ({ title, icon, isOpen, onToggleOpen, children }) => (
  <div className="border-b border-base-300 last:border-b-0">
    <button
      type="button"
      className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold uppercase tracking-wide text-base-content/70 hover:bg-base-200"
      onClick={onToggleOpen}
    >
      <span className="flex items-center gap-1.5">{icon}{title}</span>
      {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
    </button>
    {isOpen && children}
  </div>
);

type ListSectionProps = {
  title: string;
  items: readonly Item[];
  visibility: Record<string, boolean>;
  isOpen: boolean;
  onToggleOpen: () => void;
  onToggleItem: (key: string) => void;
  disabled?: boolean;
};

const ListSection: React.FC<ListSectionProps> = ({
  title, items, visibility, isOpen, onToggleOpen, onToggleItem, disabled,
}) => (
  <Section title={title} isOpen={isOpen} onToggleOpen={onToggleOpen}>
    <ul className="py-1">
      {items.map((item) => {
        const on = visibility[item.key];
        return (
          <li key={item.key}>
            <button
              type="button"
              disabled={disabled}
              className="w-full flex items-center gap-2 px-3 py-1.5 text-sm hover:bg-base-200 text-left disabled:opacity-50 disabled:cursor-not-allowed"
              onClick={() => onToggleItem(item.key)}
            >
              {on
                ? <Eye size={14} className="text-primary shrink-0" />
                : <EyeOff size={14} className="text-base-content/40 shrink-0" />}
              <span className={on ? "" : "text-base-content/40 line-through"}>
                {item.label}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  </Section>
);

type PipeRunSectionProps = {
  runs: readonly PipeRunItem[];
  memberVisibility: Record<string, boolean>;
  onToggleRun: (runKey: string) => void;
  onToggleMember: (memberKey: string) => void;
  isOpen: boolean;
  onToggleOpen: () => void;
  openRuns: Record<string, boolean>;
  onToggleRunOpen: (runKey: string) => void;
  disabled?: boolean;
};

type RunState = "all" | "none" | "mixed";

function getRunState(run: PipeRunItem, memberVisibility: Record<string, boolean>): RunState {
  if (run.members.length === 0) return "none";
  const onCount = run.members.filter((m) => memberVisibility[m.key]).length;
  if (onCount === 0) return "none";
  if (onCount === run.members.length) return "all";
  return "mixed";
}

const RunEyeIcon: React.FC<{ state: RunState }> = ({ state }) => {
  if (state === "all")  return <Eye size={14} className="text-primary shrink-0" />;
  if (state === "none") return <EyeOff size={14} className="text-base-content/40 shrink-0" />;
  return <Minus size={14} className="text-warning shrink-0" />;
};

const PipeRunSection: React.FC<PipeRunSectionProps> = ({
  runs, memberVisibility, onToggleRun, onToggleMember,
  isOpen, onToggleOpen, openRuns, onToggleRunOpen, disabled,
}) => (
  <div className="border-b border-base-300 last:border-b-0">
    <button
      type="button"
      className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold uppercase tracking-wide text-base-content/70 hover:bg-base-200"
      onClick={onToggleOpen}
    >
      <span>Pipe Runs</span>
      {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
    </button>
    {isOpen && (
      <ul className="py-1">
        {runs.map((run) => {
          const runState = getRunState(run, memberVisibility);
          const runOpen  = !!openRuns[run.key];
          return (
            <li key={run.key}>
              <div className="flex items-center hover:bg-base-200">
                <button
                  type="button"
                  aria-label={runOpen ? "Collapse run" : "Expand run"}
                  className="px-2 py-1.5 shrink-0 disabled:opacity-50 disabled:cursor-not-allowed"
                  onClick={() => onToggleRunOpen(run.key)}
                  disabled={disabled}
                >
                  {runOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                </button>
                <button
                  type="button"
                  disabled={disabled}
                  className="flex-1 flex items-center gap-2 py-1.5 pr-3 text-sm text-left disabled:opacity-50 disabled:cursor-not-allowed"
                  onClick={() => onToggleRun(run.key)}
                >
                  <RunEyeIcon state={runState} />
                  <span className={runState === "none" ? "text-base-content/40 line-through" : ""}>
                    {run.label}
                  </span>
                </button>
              </div>
              {runOpen && (
                <ul className="py-1">
                  {run.members.map((member) => {
                    const on = memberVisibility[member.key];
                    return (
                      <li key={member.key}>
                        <button
                          type="button"
                          disabled={disabled}
                          className="w-full flex items-center gap-2 pl-9 pr-3 py-1.5 text-sm hover:bg-base-200 text-left disabled:opacity-50 disabled:cursor-not-allowed"
                          onClick={() => onToggleMember(member.key)}
                        >
                          {on
                            ? <Eye size={13} className="text-primary shrink-0" />
                            : <EyeOff size={13} className="text-base-content/40 shrink-0" />}
                          <span className={on ? "" : "text-base-content/40 line-through"}>
                            {member.label}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
    )}
  </div>
);

const DownloadButton: React.FC<{ item: DownloadItem }> = ({ item }) => {
  const cls = `btn btn-ghost btn-xs justify-start bg-base-300 w-full ${item.disabled ? "btn-disabled pointer-events-none opacity-50" : ""}`;
  if (item.href !== undefined) {
    return (
      <a
        href={item.disabled ? undefined : item.href}
        download={item.downloadName}
        aria-label={`Download ${item.label}`}
        className={cls}
      >
        <Download size={13} />
        {item.label}
      </a>
    );
  }
  return (
    <button type="button" aria-label={`Download ${item.label}`} className={cls} onClick={item.onClick} disabled={item.disabled}>
      <Download size={13} />
      {item.label}
    </button>
  );
};

export default ViewerOverlayPanels;
