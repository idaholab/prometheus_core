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

import React, { useEffect, useRef, useImperativeHandle, forwardRef } from "react";
import MeshViewerEngine, { ColorPreset, PickResult, RGB } from "./MeshViewerEngine";

type Props = {
  background?: RGB;
  edgeColor?: RGB;
  allowPicking?: boolean;
  onPick?: (result: PickResult | null) => void;
  className?: string;
  style?: React.CSSProperties;
};

export type MeshViewerHandles = {
  loadTimestep: (url: string) => Promise<void>;
  applyVariableColoring: (varName: string, range?: [number, number]) => [number, number];
  clearVariableColoring: () => void;
  setColorPreset: (name: ColorPreset) => void;
  setScalarRange: (range: [number, number]) => void;
  resetCamera: () => void;
  setBackground: (rgb: RGB) => void;
  setEdgeColor: (rgb: RGB) => void;
  getEngine: () => MeshViewerEngine | null;
};

const MeshViewer = forwardRef<MeshViewerHandles, Props>(({
  background,
  edgeColor,
  allowPicking = true,
  onPick,
  className = "",
  style,
}, ref) => {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const engineRef = useRef<MeshViewerEngine | null>(null);

  const onPickRef = useRef(onPick);
  useEffect(() => { onPickRef.current = onPick; });

  useImperativeHandle(ref, () => ({
    loadTimestep: (url) => engineRef.current?.loadTimestep(url) ?? Promise.resolve(),
    applyVariableColoring: (varName, range) =>
      engineRef.current?.applyVariableColoring(varName, range) ?? [0, 1],
    clearVariableColoring: () => engineRef.current?.clearVariableColoring(),
    setColorPreset: (name) => engineRef.current?.setColorPreset(name),
    setScalarRange: (range) => engineRef.current?.setScalarRange(range),
    resetCamera: () => engineRef.current?.resetCamera(),
    setBackground: (rgb) => engineRef.current?.setBackground(rgb),
    setEdgeColor: (rgb) => engineRef.current?.setEdgeColor(rgb),
    getEngine: () => engineRef.current,
  }));

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;

    const engine = new MeshViewerEngine({
      container: el,
      background,
      edgeColor,
      allowPicking,
      onPick: (result) => onPickRef.current?.(result),
    });
    engineRef.current = engine;

    const handleResize = () => engine.resize();
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      engine.dispose();
      engineRef.current = null;
    };
    // Intentionally omitting background/edgeColor/allowPicking — these are
    // applied via the imperative setBackground/setEdgeColor handles when they
    // change (e.g. on theme switch), not by tearing down and rebuilding the
    // whole vtk.js render window.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <div ref={hostRef} className={`w-full h-full ${className}`} style={style} />;
});

MeshViewer.displayName = "MeshViewer";

export default MeshViewer;
