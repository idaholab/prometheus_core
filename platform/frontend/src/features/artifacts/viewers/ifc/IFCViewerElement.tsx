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

/**
 * Renders the `IFCViewer` Chainlit custom element using the native ThatOpen
 * (@thatopen/components) engine — ported from the Alchemy standalone viewer.
 *
 * The backend (frontend/ Chainlit API) emits this element with props:
 *   { datasetId, fileUrl: "/public/ifc-data/{id}/{file}.ifc", filename, height }
 * (see frontend/components/ifc_integration.py). `fileUrl` is a static path on
 * the API origin; in dev it's proxied via the `/public` rule in vite.config.ts.
 */

import { useEffect, useRef, useState } from "react";
import "./ifc.css";
import IfcViewer, { IFCViewerHandles } from "./IFCViewer";
import ViewerOverlayPanels, { DownloadItem } from "./ViewerOverlayPanels";
import { VISIBILITY_TOGGLES } from "./modelViewerTypes";
import type { VisibilityCategory } from "./modelViewerTypes";
import type { PipeRunItem } from "./IFCViewerEngine";
import type { ViewerProps } from "@/features/artifacts/elements";

type IFCProps = {
  fileUrl?: string;
  filename?: string;
  height?: string;
};

type LabeledItem = { key: string; label: string };

const defaultVisibility = (): Record<VisibilityCategory, boolean> =>
  Object.fromEntries(VISIBILITY_TOGGLES.map((t) => [t.key, true])) as Record<VisibilityCategory, boolean>;

const allCategoryKeys = VISIBILITY_TOGGLES.map((t) => t.key);

export function IFCViewerElement({ element }: ViewerProps) {
  const props    = ((element as { props?: IFCProps }).props) ?? {};
  const fileUrl  = props.fileUrl ?? element.url ?? null;
  const filename = props.filename ?? element.name ?? "model.ifc";
  const height   = props.height ?? "560px";

  const ifcViewerRef = useRef<IFCViewerHandles>(null);

  const [showViewer, setShowViewer] = useState(false);
  const [visibility, setVisibility] = useState<Record<VisibilityCategory, boolean>>(defaultVisibility);
  const [presentCategories, setPresentCategories] = useState<VisibilityCategory[]>(allCategoryKeys);

  const [equipmentItems,      setEquipmentItems]      = useState<LabeledItem[]>([]);
  const [equipmentVisibility, setEquipmentVisibility] = useState<Record<string, boolean>>({});

  const [pipeRuns,         setPipeRuns]         = useState<PipeRunItem[]>([]);
  const [memberVisibility, setMemberVisibility] = useState<Record<string, boolean>>({});

  useEffect(() => {
    setShowViewer(false);
    setVisibility(defaultVisibility());
    setPresentCategories(allCategoryKeys);
    setEquipmentItems([]);
    setEquipmentVisibility({});
    setPipeRuns([]);
    setMemberVisibility({});
  }, [fileUrl]);

  const handleViewerLoad = async () => {
    setShowViewer(true);

    const [present, equipment, runs] = await Promise.all([
      ifcViewerRef.current?.enumerateCategories(allCategoryKeys) ?? Promise.resolve<string[]>([]),
      ifcViewerRef.current?.enumerateEquipment()  ?? Promise.resolve([]),
      ifcViewerRef.current?.enumeratePipeRuns()   ?? Promise.resolve([]),
    ]).catch((e): [string[], LabeledItem[], PipeRunItem[]] => {
      console.error("[IFCViewerElement] enumeration failed", e);
      return [allCategoryKeys, [], []];
    });

    setPresentCategories(present as VisibilityCategory[]);
    setEquipmentItems(equipment);
    setEquipmentVisibility(Object.fromEntries(equipment.map((i) => [i.key, true])));

    setPipeRuns(runs);
    const initialMemberVisibility: Record<string, boolean> = {};
    for (const run of runs) {
      for (const member of run.members) {
        initialMemberVisibility[member.key] = true;
      }
    }
    setMemberVisibility(initialMemberVisibility);
  };

  const handleToggleVisibility = (key: VisibilityCategory) => {
    const next = !visibility[key];
    setVisibility((prev) => ({ ...prev, [key]: next }));
    ifcViewerRef.current?.setCategoryVisible(key, next);
  };

  const handleToggleEquipment = (key: string) => {
    const next = !equipmentVisibility[key];
    setEquipmentVisibility((prev) => ({ ...prev, [key]: next }));
    ifcViewerRef.current?.setEquipmentVisible(key, next);
  };

  const handleTogglePipeRun = (runKey: string) => {
    const run = pipeRuns.find((r) => r.key === runKey);
    if (!run || run.members.length === 0) return;

    const allOn = run.members.every((m) => memberVisibility[m.key]);
    const next = !allOn;

    setMemberVisibility((prev) => {
      const updated = { ...prev };
      for (const member of run.members) updated[member.key] = next;
      return updated;
    });
    ifcViewerRef.current?.setPipeRunVisible(runKey, next);
  };

  const handleTogglePipeMember = (memberKey: string) => {
    const next = !memberVisibility[memberKey];
    setMemberVisibility((prev) => ({ ...prev, [memberKey]: next }));
    ifcViewerRef.current?.setPipeMemberVisible(memberKey, next);
  };

  if (!fileUrl) {
    return (
      <div className="text-sm text-error/70 bg-error/10 rounded px-3 py-2 my-2">
        No IFC file URL was provided to the viewer.
      </div>
    );
  }

  const downloads: DownloadItem[] = [
    { key: "ifc", label: "IFC", href: fileUrl, downloadName: filename },
  ];

  return (
    <div
      className="ifc-viewer-root relative my-2 w-full max-w-full rounded-lg overflow-hidden border border-base-300 bg-base-200/40"
      style={{ height }}
    >
      {showViewer && (
        <ViewerOverlayPanels
          elementItems={VISIBILITY_TOGGLES.filter((t) => presentCategories.includes(t.key))}
          elementVisibility={visibility}
          onToggleElement={(key) => handleToggleVisibility(key as VisibilityCategory)}
          equipment={{
            items: equipmentItems,
            visibility: equipmentVisibility,
            onToggle: handleToggleEquipment,
          }}
          pipes={{
            runs: pipeRuns,
            memberVisibility,
            onToggleRun: handleTogglePipeRun,
            onToggleMember: handleTogglePipeMember,
          }}
          onReset={() => ifcViewerRef.current?.fitToFrame()}
          onTop={()   => ifcViewerRef.current?.setTopView()}
          onFront={() => ifcViewerRef.current?.setFrontView()}
          onSide={()  => ifcViewerRef.current?.setSideView()}
          downloads={downloads}
        />
      )}

      {!showViewer && (
        <div className="absolute inset-2 flex flex-col items-center justify-center gap-4 bg-base-100 rounded-md z-10">
          <span className="loading loading-spinner w-24 h-24 text-primary" />
          <p className="text-lg text-base-content/70">Loading 3D viewer…</p>
        </div>
      )}

      {/* Viewer engine — absolutely positioned so the WebGL canvas never
          contributes intrinsic width to the (min-width:auto) flex message
          body; otherwise the renderer↔layout feedback loop grows it forever.
          The -2 canvas offset compensates for this wrapper's inset-2 so the
          canvas bleeds flush to the rounded edge rather than double-inset. */}
      <div className="absolute inset-2 rounded-md overflow-hidden bg-base-100">
        <IfcViewer
          ref={ifcViewerRef}
          modelUrl={fileUrl}
          onLoad={handleViewerLoad}
          className="[&_canvas]:-ml-2 [&_canvas]:-mt-2"
        />
      </div>
    </div>
  );
}

export default IFCViewerElement;
