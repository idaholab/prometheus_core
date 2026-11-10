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
 * src/features/artifacts/viewers/mesh/MeshViewerElement.tsx
 *
 * Renders the `MeshViewer` Chainlit custom element via vtk.js — source-agnostic
 * across Exodus and STL, since both emit the same manifest.json + meta.json
 * wire contract (see components/mesh_view.py / exodus_integration.py /
 * stl_integration.py). With multiple timesteps it shows playback controls;
 * with field variables it shows a variable selector and colorbar; with
 * neither (an STL) it just renders geometry.
 *
 * Known pipeline limitations (not fixable from the frontend):
 *   - `representation: "surface" | "volume"` is accepted by the backend's
 *     ConvertRequest but never read — everything is surface geometry.
 *   - Per-block visibility toggling isn't possible; the VTP output has no
 *     per-cell block ID, and block selection only happens at conversion time.
 *
 * TODO: useTheme() below does its own dark-mode MutationObserver instead of
 * using the app's real theme source — same TODO as the IFC viewer had before
 * it was ported; swap once confirmed (Recoil atom / DaisyUI data-theme).
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { Maximize2, Minimize2, RotateCcw } from "lucide-react";
import "./mesh.css";
import MeshViewer, { MeshViewerHandles } from "./MeshViewer";
import MeshViewerControls, { VariableOption } from "./MeshViewerControls";
import type { ColorPreset, PickResult } from "./MeshViewerEngine";
import type { ViewerProps } from "@/features/artifacts/elements";

type MeshProps = {
  datasetId?: string;
  baseUrl?: string;
  metadata?: {
    num_timesteps?: number;
    time_values?: number[];
  };
  manifest?: {
    files?: { index: number; timestep_index: number; time_value: number; filename: string }[];
    variables?: { point?: string[]; cell?: string[] };
    array_ranges?: Record<string, [number, number]>;
  };
  height?: string;
  title?: string;
  showControls?: boolean;
  allowPicking?: boolean;
  initialTimestep?: number;
  initialVariable?: string | null;
  initialColorPreset?: ColorPreset;
};

function useTheme() {
  const [isDark, setIsDark] = useState(() => {
    if (typeof document === "undefined") return true;
    const html = document.documentElement;
    if (html.classList.contains("dark")) return true;
    if (html.getAttribute("data-theme") === "dark") return true;
    return !!window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  });

  useEffect(() => {
    const observer = new MutationObserver(() => {
      const html = document.documentElement;
      setIsDark(html.classList.contains("dark") || html.getAttribute("data-theme") === "dark");
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "data-theme"] });
    return () => observer.disconnect();
  }, []);

  return isDark;
}

export function MeshViewerElement({ element }: ViewerProps) {
  const props = ((element as { props?: MeshProps }).props) ?? {};
  const datasetId = props.datasetId ?? "mesh";
  const baseUrl = props.baseUrl ?? "";
  const metadata = props.metadata ?? {};
  const manifest = props.manifest ?? {};
  const height = props.height ?? "450px";
  const title = props.title ?? "Mesh Viewer";
  const showControls = props.showControls ?? true;
  const allowPicking = props.allowPicking ?? true;

  const isDark = useTheme();
  const meshRef = useRef<MeshViewerHandles>(null);
  const viewerContainerRef = useRef<HTMLDivElement>(null);

  const numTimesteps = metadata.num_timesteps || 1;
  const timeValues = metadata.time_values || [];
  const files = manifest.files || [];
  const pointVariables = manifest.variables?.point || [];
  const cellVariables = manifest.variables?.cell || [];
  const arrayRanges = manifest.array_ranges || {};

  const [currentTimestep, setCurrentTimestep] = useState(props.initialTimestep ?? 0);
  const [currentVariable, setCurrentVariable] = useState<string | null>(props.initialVariable ?? null);
  const [colorPreset, setColorPreset] = useState<ColorPreset>(props.initialColorPreset ?? "coolToWarm");
  const [scalarRange, setScalarRange] = useState<[number, number]>([0, 1]);
  const [isPlaying, setIsPlaying] = useState(false);
  const [pickedInfo, setPickedInfo] = useState<PickResult | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Theme → engine background/edge color
  useEffect(() => {
    meshRef.current?.setBackground(isDark ? [0.08, 0.08, 0.12] : [0.91, 0.91, 0.94]);
    meshRef.current?.setEdgeColor(isDark ? [0.72, 0.76, 0.84] : [0.08, 0.1, 0.14]);
  }, [isDark]);

  // Fullscreen
  const toggleFullscreen = useCallback(() => {
    if (!viewerContainerRef.current) return;
    if (!document.fullscreenElement) {
      viewerContainerRef.current.requestFullscreen().catch((err) => console.error("Fullscreen failed:", err));
    } else {
      document.exitFullscreen();
    }
  }, []);

  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", handler);
    return () => document.removeEventListener("fullscreenchange", handler);
  }, []);

  // Load the current timestep whenever it (or the dataset) changes.
  useEffect(() => {
    const fileInfo = files.find((f) => f.timestep_index === currentTimestep) || files[currentTimestep];
    if (!fileInfo || !baseUrl) return;

    setError(null);
    meshRef.current
      ?.loadTimestep(`${baseUrl}/${fileInfo.filename}`)
      .then(() => {
        if (currentVariable) {
          const range = arrayRanges[currentVariable];
          const applied = meshRef.current?.applyVariableColoring(currentVariable, range);
          if (applied) setScalarRange(applied);
        }
      })
      .catch((err) => {
        console.error(`Failed to load timestep ${currentTimestep}:`, err);
        setError(`Failed to load timestep: ${err.message}`);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentTimestep, baseUrl, datasetId]);

  // Re-apply coloring when the variable selection changes.
  useEffect(() => {
    if (!currentVariable) {
      meshRef.current?.clearVariableColoring();
      return;
    }
    const range = arrayRanges[currentVariable];
    const applied = meshRef.current?.applyVariableColoring(currentVariable, range);
    if (applied) setScalarRange(applied);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentVariable]);

  useEffect(() => {
    meshRef.current?.setColorPreset(colorPreset);
  }, [colorPreset]);

  useEffect(() => {
    meshRef.current?.setScalarRange(scalarRange);
  }, [scalarRange]);

  // Playback
  useEffect(() => {
    if (!isPlaying || numTimesteps <= 1) return;
    const interval = setInterval(() => {
      setCurrentTimestep((prev) => (prev + 1) % numTimesteps);
    }, 200);
    return () => clearInterval(interval);
  }, [isPlaying, numTimesteps]);

  const variableOptions: VariableOption[] = [
    ...pointVariables.map((v) => ({ value: v, label: v, group: "point" as const })),
    ...cellVariables.map((v) => ({ value: v, label: v, group: "cell" as const })),
  ];

  const formatTime = (t: number | undefined) => {
    if (t === undefined) return undefined;
    return t < 0.001 || t > 1000 ? t.toExponential(2) : t.toFixed(3);
  };

  return (
    <div
      ref={viewerContainerRef}
      className="mesh-viewer-root relative my-2 w-full max-w-full rounded-lg overflow-hidden border border-base-300 bg-base-200/40 flex flex-col"
      style={isFullscreen ? undefined : undefined}
    >
      <div className="flex items-center justify-between px-4 py-2 border-b border-base-300 bg-base-200/40">
        <div className="flex items-center gap-2 text-sm font-medium text-base-content">
          <span>{title}</span>
          <span className="badge badge-sm badge-primary badge-outline">{datasetId}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            className="btn btn-ghost btn-xs btn-square bg-base-300"
            onClick={() => meshRef.current?.resetCamera()}
            title="Reset camera"
            aria-label="Reset camera"
          >
            <RotateCcw size={14} />
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-xs btn-square bg-base-300"
            onClick={toggleFullscreen}
            title={isFullscreen ? "Exit fullscreen" : "Fullscreen"}
            aria-label={isFullscreen ? "Exit fullscreen" : "Fullscreen"}
          >
            {isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
        </div>
      </div>

      {error ? (
        <div className="p-4">
          <div className="text-sm text-error/80 bg-error/10 border border-error/30 rounded px-3 py-2">
            {error}
          </div>
        </div>
      ) : (
        <div className="relative w-full bg-base-300/40" style={{ height: isFullscreen ? undefined : height, flex: isFullscreen ? 1 : undefined }}>
          <MeshViewer
            ref={meshRef}
            allowPicking={allowPicking}
            onPick={setPickedInfo}
          />

          {showControls && (
            <MeshViewerControls
              numTimesteps={numTimesteps}
              currentTimestep={currentTimestep}
              onTimestepChange={(i) => { setIsPlaying(false); setCurrentTimestep(i); }}
              isPlaying={isPlaying}
              onTogglePlay={() => setIsPlaying((p) => !p)}
              timeLabel={formatTime(timeValues[currentTimestep])}
              variableOptions={variableOptions}
              currentVariable={currentVariable}
              onVariableChange={setCurrentVariable}
              colorPreset={colorPreset}
              onColorPresetChange={setColorPreset}
              scalarRange={scalarRange}
              onScalarRangeChange={setScalarRange}
            />
          )}

          {pickedInfo && (
            <div className="absolute bottom-3 left-3 flex items-center gap-3 bg-base-100/90 backdrop-blur border border-base-300 rounded-lg px-3 py-2 text-xs">
              <span><span className="text-base-content/50 mr-1">Cell</span><span className="font-mono text-primary">{pickedInfo.cellId}</span></span>
              <span>
                <span className="text-base-content/50 mr-1">Pos</span>
                <span className="font-mono text-primary">({pickedInfo.position.map((p) => p.toFixed(2)).join(", ")})</span>
              </span>
              {pickedInfo.value !== null && (
                <span><span className="text-base-content/50 mr-1">Val</span><span className="font-mono text-primary">{pickedInfo.value.toExponential(3)}</span></span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default MeshViewerElement;
