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

import React, {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
} from "react";
import IFCViewerEngine, { EquipmentItem, PipeRunItem } from "./IFCViewerEngine";
import type { TreeGroup } from "./treeGrouping";

type Props = {
  modelUrl: string;
  wasmCdnPath?: string;
  className?: string;
  style?: React.CSSProperties;
  onLoad?: () => void;
};

export type IFCViewerHandles = {
  resetCamera: () => void;
  setBackground: (rgb: [number, number, number]) => void;
  fitToFrame: () => void;
  setTopView: () => void;
  setFrontView: () => void;
  setSideView: () => void;
  setIsometricView: () => void;
  setCategoryVisible: (category: string, visible: boolean) => void;
  resetVisibility: () => void;
  setPanMode: (active: boolean) => void;
  toggleProjection: () => Promise<void>;
  getProjectionMode: () => "Perspective" | "Orthographic";
  enumerateCategories: (categories: string[]) => Promise<string[]>;
  enumerateEquipment: () => Promise<EquipmentItem[]>;
  setEquipmentVisible: (key: string, visible: boolean) => Promise<void>;
  enumeratePipeRuns: () => Promise<PipeRunItem[]>;
  setPipeRunVisible: (key: string, visible: boolean) => Promise<void>;
  setPipeMemberVisible: (key: string, visible: boolean) => Promise<void>;
  enumerateWallGroups: () => Promise<TreeGroup[]>;
  enumerateRoofGroups: () => Promise<TreeGroup[]>;
  enumerateColumnGroups: () => Promise<TreeGroup[]>;
  setTreeGroupVisible: (key: string, visible: boolean) => void;
  setTreeMemberVisible: (key: string, visible: boolean) => void;
  getEngine: () => IFCViewerEngine | null;
};

const IfcViewer = forwardRef<IFCViewerHandles, Props>(
  ({ modelUrl, wasmCdnPath, className = "", style, onLoad }, ref) => {
    const hostRef = useRef<HTMLDivElement | null>(null);
    const engineRef = useRef<IFCViewerEngine | null>(null);

    const onLoadRef = useRef(onLoad);
    useEffect(() => {
      onLoadRef.current = onLoad;
    });

    useImperativeHandle(ref, () => ({
      resetCamera: () => engineRef.current?.resetCamera(),
      setBackground: (rgb) => engineRef.current?.setBackground(rgb),
      fitToFrame: () => engineRef.current?.fitToFrame(),
      setTopView: () => engineRef.current?.setTopView(),
      setFrontView: () => engineRef.current?.setFrontView(),
      setSideView: () => engineRef.current?.setSideView(),
      setIsometricView: () => engineRef.current?.setIsometricView(),
      setCategoryVisible: (category, visible) => {
        engineRef.current?.setCategoryVisible(category, visible);
      },
      resetVisibility: () => {
        engineRef.current?.resetVisibility();
      },
      setPanMode: (active) => {
        engineRef.current?.setPanMode(active);
      },
      toggleProjection: () =>
        engineRef.current?.toggleProjection() ?? Promise.resolve(),
      getProjectionMode: () =>
        engineRef.current?.getProjectionMode() ?? "Perspective",
      enumerateCategories: (categories) =>
        engineRef.current?.enumerateCategories(categories) ??
        Promise.resolve([]),
      enumerateEquipment: () =>
        engineRef.current?.enumerateEquipment() ?? Promise.resolve([]),
      setEquipmentVisible: (key, visible) =>
        engineRef.current?.setEquipmentVisible(key, visible) ??
        Promise.resolve(),
      enumeratePipeRuns: () =>
        engineRef.current?.enumeratePipeRuns() ?? Promise.resolve([]),
      setPipeRunVisible: (key, visible) =>
        engineRef.current?.setPipeRunVisible(key, visible) ?? Promise.resolve(),
      setPipeMemberVisible: (key, visible) =>
        engineRef.current?.setPipeMemberVisible(key, visible) ??
        Promise.resolve(),
      enumerateWallGroups: () =>
        engineRef.current?.enumerateWallGroups() ?? Promise.resolve([]),
      enumerateRoofGroups: () =>
        engineRef.current?.enumerateRoofGroups() ?? Promise.resolve([]),
      enumerateColumnGroups: () =>
        engineRef.current?.enumerateColumnGroups() ?? Promise.resolve([]),
      setTreeGroupVisible: (key, visible) => {
        engineRef.current?.setTreeGroupVisible(key, visible);
      },
      setTreeMemberVisible: (key, visible) => {
        engineRef.current?.setTreeMemberVisible(key, visible);
      },
      getEngine: () => engineRef.current,
    }));

    useEffect(() => {
      const el = hostRef.current;
      if (!el) return;

      const engine = new IFCViewerEngine({ container: el, wasmCdnPath });
      engineRef.current = engine;

      const handleResize = () => engine.resize();
      window.addEventListener("resize", handleResize);
      handleResize();

      const ac = new AbortController();
      const { signal } = ac;

      (async () => {
        try {
          await engine.init();
          if (signal.aborted) return;

          await engine.loadIfcFromUrl(modelUrl);
          if (signal.aborted) return;

          onLoadRef.current?.();
        } catch (e) {
          if (!signal.aborted) {
            console.error("[IfcViewer] error:", e);
          }
        }
      })();

      return () => {
        ac.abort();
        window.removeEventListener("resize", handleResize);
        engine.dispose();
        engineRef.current = null;
      };
    }, [modelUrl, wasmCdnPath]);

    return (
      <div
        ref={hostRef}
        className={`w-full h-full ${className}`}
        style={style}
      />
    );
  },
);

IfcViewer.displayName = "IfcViewer";

export default IfcViewer;
