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

import {
  Box,
  ChevronDown,
  ChevronRight,
  Download,
  Eye,
  EyeOff,
  Hand,
  Minimize2,
  Minus,
  SlidersHorizontal,
  Video,
} from "lucide-react";
import React, { useEffect, useRef, useState } from "react";
import type { TreeGroup } from "./treeGrouping";

type Item = { key: string; label: string };

export type SectionData = {
  items: readonly Item[];
  visibility: Record<string, boolean>;
  onToggle: (key: string) => void;
};

// A tree section: a titled list of parent groups, each with nested members
// (pipe runs → segments, wall panels → layers, columns → base-plate pieces).
export type GroupSectionData = {
  key: string;
  title: string;
  groups: readonly TreeGroup[];
  memberVisibility: Record<string, boolean>;
  onToggleGroup: (groupKey: string) => void;
  onToggleMember: (memberKey: string) => void;
};

// Back-compat alias: pipe runs are just a group section titled "Pipe Runs".
export type PipeSectionData = Omit<GroupSectionData, "key" | "title">;

export type DownloadItem =
  | {
      key: string;
      label: string;
      disabled?: boolean;
      href: string;
      downloadName?: string;
      onClick?: undefined;
    }
  | {
      key: string;
      label: string;
      disabled?: boolean;
      onClick: () => void;
      href?: undefined;
      downloadName?: undefined;
    };

type Props = {
  elementItems: readonly Item[];
  elementVisibility: Record<string, boolean>;
  onToggleElement: (key: string) => void;
  equipment?: SectionData;
  pipes?: PipeSectionData;
  // Walls / roof / columns trees — rendered only for the categories that have
  // sub-pieces in this model; the rest stay flat toggles in elementItems.
  elementGroups?: GroupSectionData[];

  onReset: () => void;
  onTop: () => void;
  onFront: () => void;
  onSide: () => void;

  panMode: boolean;
  onTogglePan: () => void;

  projectionMode: "Perspective" | "Orthographic";
  onToggleProjection: () => void;

  downloads?: DownloadItem[];

  disabled?: boolean;
  // Below this width the two panels merge into one. Same UI, just laid out
  // differently for the space available — a full-screen app gets room for
  // two independent panels; a narrow embedded/chat view doesn't.
  breakpoint?: number;
};

const ViewerOverlayPanels: React.FC<Props> = ({
  elementItems,
  elementVisibility,
  onToggleElement,
  equipment,
  pipes,
  elementGroups,
  onReset,
  onTop,
  onFront,
  onSide,
  panMode,
  onTogglePan,
  projectionMode,
  onToggleProjection,
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
    elements: true,
    equipment: true,
    pipes: true,
    camera: true,
    download: true,
  });
  const toggleSection = (id: string) =>
    setSections((prev) => ({ ...prev, [id]: !prev[id] }));

  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});
  const toggleGroupOpen = (groupKey: string) =>
    setOpenGroups((prev) => ({ ...prev, [groupKey]: !prev[groupKey] }));

  const [visOpen, setVisOpen] = useState(true);
  const [ctrlOpen, setCtrlOpen] = useState(true);

  const hasElements = elementItems.length > 0;
  const hasEquipment = !!equipment && equipment.items.length > 0;
  const groupSections: GroupSectionData[] = [
    ...(elementGroups ?? []),
    ...(pipes && pipes.groups.length > 0
      ? [{ key: "pipes", title: "Pipe Runs", ...pipes }]
      : []),
  ].filter((s) => s.groups.length > 0);
  const hasDownloads = !!downloads && downloads.length > 0;

  const visibilitySections = (
    <>
      {hasElements && (
        <ListSection
          title="Building Elements"
          items={elementItems}
          visibility={elementVisibility}
          isOpen={sections.elements ?? true}
          onToggleOpen={() => toggleSection("elements")}
          onToggleItem={onToggleElement}
          disabled={disabled}
        />
      )}
      {groupSections.map((section) => (
        <GroupedTreeSection
          key={section.key}
          title={section.title}
          groups={section.groups}
          memberVisibility={section.memberVisibility}
          onToggleGroup={section.onToggleGroup}
          onToggleMember={section.onToggleMember}
          isOpen={sections[section.key] ?? true}
          onToggleOpen={() => toggleSection(section.key)}
          openGroups={openGroups}
          onToggleGroupOpen={toggleGroupOpen}
          disabled={disabled}
        />
      ))}
      {hasEquipment && equipment && (
        <ListSection
          title="Equipment"
          items={equipment.items}
          visibility={equipment.visibility}
          isOpen={sections.equipment ?? true}
          onToggleOpen={() => toggleSection("equipment")}
          onToggleItem={equipment.onToggle}
          disabled={disabled}
        />
      )}
    </>
  );

  const controlSections = (
    <>
      <Section
        title="Camera"
        icon={<Video size={12} />}
        isOpen={sections.camera}
        onToggleOpen={() => toggleSection("camera")}
      >
        <div className="grid grid-cols-2 gap-1 p-2">
          <button
            type="button"
            className="btn btn-ghost btn-xs col-span-2 bg-base-300"
            aria-label="Reset view"
            onClick={onReset}
            disabled={disabled}
          >
            Reset View
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-xs bg-base-300"
            aria-label="Top view"
            onClick={onTop}
            disabled={disabled}
          >
            Top
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-xs bg-base-300"
            aria-label="Front view"
            onClick={onFront}
            disabled={disabled}
          >
            Front
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-xs col-span-2 bg-base-300"
            aria-label="Side view"
            onClick={onSide}
            disabled={disabled}
          >
            Side
          </button>
          <button
            type="button"
            className={`btn btn-ghost btn-xs col-span-2 gap-1.5 ${panMode ? "bg-primary text-primary-content hover:bg-primary" : "bg-base-300"}`}
            aria-label={
              panMode
                ? "Pan mode on, click to use left-drag to rotate"
                : "Pan mode off, click to use left-drag to pan"
            }
            aria-pressed={panMode}
            onClick={onTogglePan}
            disabled={disabled}
          >
            <Hand size={13} />
            Pan {panMode ? "On" : "Off"}
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-xs col-span-2 gap-1.5 bg-base-300"
            aria-label={`Switch to ${projectionMode === "Perspective" ? "Orthographic" : "Perspective"} view`}
            onClick={onToggleProjection}
            disabled={disabled}
          >
            <Box size={13} />
            {projectionMode}
          </button>
        </div>
      </Section>
      {hasDownloads && (
        <Section
          title="Download"
          icon={<Download size={12} />}
          isOpen={sections.download}
          onToggleOpen={() => toggleSection("download")}
        >
          <div className="flex flex-col gap-1 p-2">
            {downloads!.map((item) => (
              <DownloadButton key={item.key} item={item} />
            ))}
          </div>
        </Section>
      )}
    </>
  );

  const controlsLegend = (
    <div className="absolute bottom-2 left-1/2 -translate-x-1/2 z-10 px-3 py-1 rounded-full bg-base-100/80 backdrop-blur text-xs text-base-content/60 whitespace-nowrap">
      Left-drag: Rotate &middot; Right-drag: Pan &middot; Scroll: Zoom
    </div>
  );

  const overlayShell = (children: React.ReactNode) => (
    <div ref={overlayRef} className="absolute inset-0 pointer-events-none">
      {children}
      {controlsLegend}
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
      </>,
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
    </div>,
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

const FloatingPanel: React.FC<FloatingPanelProps> = ({
  title,
  icon,
  side,
  open,
  onToggleOpen,
  children,
}) => {
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
    <div
      className={`absolute top-2 ${posClass} z-20 w-64 max-h-[calc(100%-1rem)] flex flex-col bg-base-100/95 backdrop-blur rounded-md shadow-lg border border-base-300 overflow-hidden`}
    >
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

const Section: React.FC<SectionProps> = ({
  title,
  icon,
  isOpen,
  onToggleOpen,
  children,
}) => (
  <div className="border-b border-base-300 last:border-b-0">
    <button
      type="button"
      className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold uppercase tracking-wide text-base-content/70 hover:bg-base-200"
      onClick={onToggleOpen}
    >
      <span className="flex items-center gap-1.5">
        {icon}
        {title}
      </span>
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
  title,
  items,
  visibility,
  isOpen,
  onToggleOpen,
  onToggleItem,
  disabled,
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
              {on ? (
                <Eye size={14} className="text-primary shrink-0" />
              ) : (
                <EyeOff size={14} className="text-base-content/40 shrink-0" />
              )}
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

type GroupedTreeSectionProps = {
  title: string;
  groups: readonly TreeGroup[];
  memberVisibility: Record<string, boolean>;
  onToggleGroup: (groupKey: string) => void;
  onToggleMember: (memberKey: string) => void;
  isOpen: boolean;
  onToggleOpen: () => void;
  openGroups: Record<string, boolean>;
  onToggleGroupOpen: (groupKey: string) => void;
  disabled?: boolean;
};

type GroupState = "all" | "none" | "mixed";

function getGroupState(
  group: TreeGroup,
  memberVisibility: Record<string, boolean>,
): GroupState {
  if (group.members.length === 0) return "none";
  const onCount = group.members.filter((m) => memberVisibility[m.key]).length;
  if (onCount === 0) return "none";
  if (onCount === group.members.length) return "all";
  return "mixed";
}

const GroupEyeIcon: React.FC<{ state: GroupState }> = ({ state }) => {
  if (state === "all")
    return <Eye size={14} className="text-primary shrink-0" />;
  if (state === "none")
    return <EyeOff size={14} className="text-base-content/40 shrink-0" />;
  return <Minus size={14} className="text-warning shrink-0" />;
};

// Shared 2-level tree: pipe runs → segments, wall/roof panels → layers, columns
// → base-plate pieces. The parent eye is tri-state (all / none / mixed).
const GroupedTreeSection: React.FC<GroupedTreeSectionProps> = ({
  title,
  groups,
  memberVisibility,
  onToggleGroup,
  onToggleMember,
  isOpen,
  onToggleOpen,
  openGroups,
  onToggleGroupOpen,
  disabled,
}) => (
  <div className="border-b border-base-300 last:border-b-0">
    <button
      type="button"
      className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold uppercase tracking-wide text-base-content/70 hover:bg-base-200"
      onClick={onToggleOpen}
    >
      <span>{title}</span>
      {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
    </button>
    {isOpen && (
      <ul className="py-1">
        {groups.map((group) => {
          const groupState = getGroupState(group, memberVisibility);
          const groupOpen = !!openGroups[group.key];
          return (
            <li key={group.key}>
              <div className="flex items-center hover:bg-base-200">
                <button
                  type="button"
                  aria-label={groupOpen ? "Collapse group" : "Expand group"}
                  className="px-2 py-1.5 shrink-0 disabled:opacity-50 disabled:cursor-not-allowed"
                  onClick={() => onToggleGroupOpen(group.key)}
                  disabled={disabled}
                >
                  {groupOpen ? (
                    <ChevronDown size={12} />
                  ) : (
                    <ChevronRight size={12} />
                  )}
                </button>
                <button
                  type="button"
                  disabled={disabled}
                  className="flex-1 flex items-center gap-2 py-1.5 pr-3 text-sm text-left disabled:opacity-50 disabled:cursor-not-allowed"
                  onClick={() => onToggleGroup(group.key)}
                >
                  <GroupEyeIcon state={groupState} />
                  <span
                    className={
                      groupState === "none"
                        ? "text-base-content/40 line-through"
                        : ""
                    }
                  >
                    {group.label}
                  </span>
                </button>
              </div>
              {groupOpen && (
                <ul className="py-1">
                  {group.members.map((member) => {
                    const on = memberVisibility[member.key];
                    return (
                      <li key={member.key}>
                        <button
                          type="button"
                          disabled={disabled}
                          className="w-full flex items-center gap-2 pl-9 pr-3 py-1.5 text-sm hover:bg-base-200 text-left disabled:opacity-50 disabled:cursor-not-allowed"
                          onClick={() => onToggleMember(member.key)}
                        >
                          {on ? (
                            <Eye size={13} className="text-primary shrink-0" />
                          ) : (
                            <EyeOff
                              size={13}
                              className="text-base-content/40 shrink-0"
                            />
                          )}
                          <span
                            className={
                              on ? "" : "text-base-content/40 line-through"
                            }
                          >
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
    <button
      type="button"
      aria-label={`Download ${item.label}`}
      className={cls}
      onClick={item.onClick}
      disabled={item.disabled}
    >
      <Download size={13} />
      {item.label}
    </button>
  );
};

export default ViewerOverlayPanels;
