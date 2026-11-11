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

import React, { useState } from "react";
import {
  ChevronDown, ChevronRight, Play, Pause, SkipBack, SkipForward,
  SlidersHorizontal, Minimize2,
} from "lucide-react";
import { COLOR_PRESETS, PRESET_LABELS, type ColorPreset } from "./MeshViewerEngine";

function getColorbarGradient(preset: ColorPreset): string {
  const stops = COLOR_PRESETS[preset] ?? COLOR_PRESETS.coolToWarm;
  const css = stops.map(([pos, r, g, b]) => {
    const color = `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`;
    return `${color} ${pos * 100}%`;
  });
  return `linear-gradient(to right, ${css.join(", ")})`;
}

function formatValue(val: number | undefined): string {
  if (val === undefined || val === null) return "0";
  if (Math.abs(val) < 0.001 || Math.abs(val) > 10000) return val.toExponential(2);
  return val.toFixed(3);
}

export function Colorbar({
  preset, min, max, variable,
}: { preset: ColorPreset; min: number; max: number; variable: string }) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-base-content">{variable}</span>
        <span className="text-[10px] text-base-content/50">{PRESET_LABELS[preset]}</span>
      </div>
      <div
        className="h-2.5 rounded-full border border-base-300"
        style={{ background: getColorbarGradient(preset) }}
      />
      <div className="flex justify-between text-[9px] font-mono text-base-content/50">
        <span>{formatValue(min)}</span>
        <span>{formatValue((min + max) / 2)}</span>
        <span>{formatValue(max)}</span>
      </div>
    </div>
  );
}

export type VariableOption = { value: string; label: string; group: "point" | "cell" };

type Props = {
  numTimesteps: number;
  currentTimestep: number;
  onTimestepChange: (index: number) => void;
  isPlaying: boolean;
  onTogglePlay: () => void;
  timeLabel?: string;

  variableOptions: VariableOption[];
  currentVariable: string | null;
  onVariableChange: (varName: string | null) => void;

  colorPreset: ColorPreset;
  onColorPresetChange: (preset: ColorPreset) => void;

  scalarRange: [number, number];
  onScalarRangeChange: (range: [number, number]) => void;

  disabled?: boolean;
};

const MeshViewerControls: React.FC<Props> = ({
  numTimesteps, currentTimestep, onTimestepChange, isPlaying, onTogglePlay, timeLabel,
  variableOptions, currentVariable, onVariableChange,
  colorPreset, onColorPresetChange,
  scalarRange, onScalarRangeChange,
  disabled = false,
}) => {
  const [open, setOpen] = useState(true);
  const [playbackOpen, setPlaybackOpen] = useState(true);
  const [appearanceOpen, setAppearanceOpen] = useState(true);

  const hasPlayback = numTimesteps > 1;
  const hasVariables = variableOptions.length > 0;

  if (!hasPlayback && !hasVariables) {
    return null;
  }

  if (!open) {
    return (
      <button
        type="button"
        aria-label="Open viewer controls"
        className="absolute top-2 right-2 z-20 flex items-center justify-center w-9 h-9 bg-base-100/95 backdrop-blur rounded-md shadow-lg border border-base-300 hover:bg-base-200 transition-colors"
        onClick={() => setOpen(true)}
      >
        <SlidersHorizontal size={14} />
      </button>
    );
  }

  return (
    <div className="absolute top-2 right-2 z-20 w-72 max-h-[calc(100%-1rem)] flex flex-col bg-base-100/95 backdrop-blur rounded-md shadow-lg border border-base-300 overflow-hidden">
      <button
        type="button"
        aria-label="Collapse controls panel"
        className="w-full flex items-center justify-between px-3 py-2 bg-base-200 border-b border-base-300 hover:bg-base-300 transition-colors"
        onClick={() => setOpen(false)}
      >
        <div className="flex items-center gap-2 text-sm font-semibold">
          <SlidersHorizontal size={14} />
          Controls
        </div>
        <Minimize2 size={14} />
      </button>

      <div className="flex-1 overflow-y-auto">
        {hasPlayback && (
          <div className="border-b border-base-300">
            <button
              type="button"
              className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold uppercase tracking-wide text-base-content/70 hover:bg-base-200"
              onClick={() => setPlaybackOpen((v) => !v)}
            >
              <span>Playback</span>
              {playbackOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            </button>
            {playbackOpen && (
              <div className="p-3 flex flex-col gap-2">
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    aria-label={isPlaying ? "Pause" : "Play"}
                    className="btn btn-ghost btn-xs btn-square bg-base-300"
                    onClick={onTogglePlay}
                    disabled={disabled}
                  >
                    {isPlaying ? <Pause size={13} /> : <Play size={13} />}
                  </button>
                  <button
                    type="button"
                    aria-label="First timestep"
                    className="btn btn-ghost btn-xs btn-square bg-base-300"
                    onClick={() => onTimestepChange(0)}
                    disabled={disabled}
                  >
                    <SkipBack size={13} />
                  </button>
                  <input
                    type="range"
                    min={0}
                    max={numTimesteps - 1}
                    value={currentTimestep}
                    onChange={(e) => onTimestepChange(parseInt(e.target.value, 10))}
                    className="range range-xs range-primary flex-1"
                    disabled={disabled}
                  />
                  <button
                    type="button"
                    aria-label="Last timestep"
                    className="btn btn-ghost btn-xs btn-square bg-base-300"
                    onClick={() => onTimestepChange(numTimesteps - 1)}
                    disabled={disabled}
                  >
                    <SkipForward size={13} />
                  </button>
                </div>
                <div className="flex items-center justify-between text-[11px] font-mono text-base-content/60">
                  <span>{currentTimestep + 1} / {numTimesteps}</span>
                  {timeLabel && <span>t = {timeLabel}</span>}
                </div>
              </div>
            )}
          </div>
        )}

        {hasVariables && (
        <div className="border-b border-base-300 last:border-b-0">
          <button
            type="button"
            className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold uppercase tracking-wide text-base-content/70 hover:bg-base-200"
            onClick={() => setAppearanceOpen((v) => !v)}
          >
            <span>Variable &amp; Color</span>
            {appearanceOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          </button>
          {appearanceOpen && (
            <div className="p-3 flex flex-col gap-3">
              <label className="flex flex-col gap-1">
                <span className="text-[10px] uppercase tracking-wide text-base-content/50 font-semibold">
                  Variable
                </span>
                <select
                  className="select select-xs select-bordered w-full"
                  value={currentVariable ?? ""}
                  onChange={(e) => onVariableChange(e.target.value || null)}
                  disabled={disabled}
                >
                  <option value="">None</option>
                  {variableOptions.some((v) => v.group === "point") && (
                    <optgroup label="Point">
                      {variableOptions.filter((v) => v.group === "point").map((v) => (
                        <option key={v.value} value={v.value}>{v.label}</option>
                      ))}
                    </optgroup>
                  )}
                  {variableOptions.some((v) => v.group === "cell") && (
                    <optgroup label="Cell">
                      {variableOptions.filter((v) => v.group === "cell").map((v) => (
                        <option key={v.value} value={v.value}>{v.label}</option>
                      ))}
                    </optgroup>
                  )}
                </select>
              </label>

              <label className="flex flex-col gap-1">
                <span className="text-[10px] uppercase tracking-wide text-base-content/50 font-semibold">
                  Colors
                </span>
                <select
                  className="select select-xs select-bordered w-full"
                  value={colorPreset}
                  onChange={(e) => onColorPresetChange(e.target.value as ColorPreset)}
                  disabled={disabled}
                >
                  {Object.entries(PRESET_LABELS).map(([key, label]) => (
                    <option key={key} value={key}>{label}</option>
                  ))}
                </select>
              </label>

              {currentVariable && (
                <>
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] uppercase tracking-wide text-base-content/50 font-semibold">
                      Range
                    </span>
                    <input
                      type="number"
                      className="input input-xs input-bordered w-20 font-mono"
                      value={scalarRange[0]}
                      step="any"
                      onChange={(e) => {
                        const v = parseFloat(e.target.value);
                        if (!isNaN(v)) onScalarRangeChange([v, scalarRange[1]]);
                      }}
                      disabled={disabled}
                    />
                    <span className="text-base-content/40 text-xs">to</span>
                    <input
                      type="number"
                      className="input input-xs input-bordered w-20 font-mono"
                      value={scalarRange[1]}
                      step="any"
                      onChange={(e) => {
                        const v = parseFloat(e.target.value);
                        if (!isNaN(v)) onScalarRangeChange([scalarRange[0], v]);
                      }}
                      disabled={disabled}
                    />
                  </div>
                  <Colorbar
                    preset={colorPreset}
                    min={scalarRange[0]}
                    max={scalarRange[1]}
                    variable={currentVariable}
                  />
                </>
              )}
            </div>
          )}
        </div>
        )}
      </div>
    </div>
  );
};

export default MeshViewerControls;
