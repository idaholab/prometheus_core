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
 * src/viewers/mesh/MeshViewerEngine.ts
 *
 * Owns the vtk.js render lifecycle for VTP mesh datasets (Exodus, STL, …) —
 * mirrors IFCViewerEngine.ts's shape: a plain class with no React, holding the
 * renderer/mapper/actor/picker and exposing imperative methods. The React
 * wrapper (MeshViewer.tsx) just mounts a host div and forwards a ref.
 */

// Registers the OpenGL rendering backend for core vtk.js classes (Actor,
// Mapper, Renderer, RenderWindow, etc). vtk.js separates "what a class is"
// from "how to draw it with WebGL" — nothing wires the second part up
// automatically, it only happens as a side effect of importing a Profile
// module once, anywhere in the app. Without this, vtkFullScreenRenderWindow
// constructs a renderer with no registered OpenGL view node factory, and
// internal factory lookups return undefined instead of throwing a clear error.
import "@kitware/vtk.js/Rendering/Profiles/Geometry";

import vtkFullScreenRenderWindow from "@kitware/vtk.js/Rendering/Misc/FullScreenRenderWindow";
import vtkColorTransferFunction from "@kitware/vtk.js/Rendering/Core/ColorTransferFunction";
import vtkMapper from "@kitware/vtk.js/Rendering/Core/Mapper";
import vtkActor from "@kitware/vtk.js/Rendering/Core/Actor";
import vtkCellPicker from "@kitware/vtk.js/Rendering/Core/CellPicker";
import vtkXMLPolyDataReader from "@kitware/vtk.js/IO/XML/XMLPolyDataReader";

import type { vtkFullScreenRenderWindow as IFullScreenRenderWindow } from "@kitware/vtk.js/Rendering/Misc/FullScreenRenderWindow";
import type { vtkRenderer as IRenderer } from "@kitware/vtk.js/Rendering/Core/Renderer";
import type { vtkRenderWindow as IRenderWindow } from "@kitware/vtk.js/Rendering/Core/RenderWindow";
import type { vtkColorTransferFunction as IColorTransferFunction } from "@kitware/vtk.js/Rendering/Core/ColorTransferFunction";
import type { vtkMapper as IMapper } from "@kitware/vtk.js/Rendering/Core/Mapper";
import type { vtkActor as IActor } from "@kitware/vtk.js/Rendering/Core/Actor";
import type { vtkCellPicker as ICellPicker } from "@kitware/vtk.js/Rendering/Core/CellPicker";
import type { vtkPolyData as IPolyData } from "@kitware/vtk.js/Common/DataModel/PolyData";

export type RGB = [number, number, number];

export type PickResult = {
  cellId: number;
  position: [number, number, number];
  value: number | null;
};

export type ViewerOptions = {
  container: HTMLElement;
  background?: RGB;
  edgeColor?: RGB;
  allowPicking?: boolean;
  onPick?: (result: PickResult | null) => void;
};

export const COLOR_PRESETS = {
  coolToWarm: [
    [0, 0.231, 0.298, 0.753],
    [0.5, 0.865, 0.865, 0.865],
    [1, 0.706, 0.016, 0.149],
  ],
  viridis: [
    [0, 0.267, 0.004, 0.329],
    [0.25, 0.282, 0.141, 0.458],
    [0.5, 0.127, 0.566, 0.551],
    [0.75, 0.369, 0.788, 0.384],
    [1, 0.993, 0.906, 0.144],
  ],
  plasma: [
    [0, 0.05, 0.03, 0.528],
    [0.25, 0.416, 0.09, 0.633],
    [0.5, 0.797, 0.21, 0.471],
    [0.75, 0.973, 0.58, 0.254],
    [1, 0.94, 0.975, 0.131],
  ],
  rainbow: [
    [0, 0, 0, 1],
    [0.25, 0, 1, 1],
    [0.5, 0, 1, 0],
    [0.75, 1, 1, 0],
    [1, 1, 0, 0],
  ],
  grayscale: [
    [0, 0, 0, 0],
    [1, 1, 1, 1],
  ],
} as const;

export type ColorPreset = keyof typeof COLOR_PRESETS;

export const PRESET_LABELS: Record<ColorPreset, string> = {
  coolToWarm: "Cool to Warm",
  viridis: "Viridis",
  plasma: "Plasma",
  rainbow: "Rainbow",
  grayscale: "Grayscale",
};

export default class MeshViewerEngine {
  private renderer!: IRenderer;
  private renderWindow!: IRenderWindow;
  private fullScreenRenderWindow!: IFullScreenRenderWindow;
  private mapper!: IMapper;
  private actor!: IActor;
  private lookupTable!: IColorTransferFunction;
  private picker!: ICellPicker;

  private currentPolyData: IPolyData | null = null;
  private currentArrayName: string | null = null;
  private cameraInitialized = false;
  private loadToken = 0;
  private disposed = false;
  private cleanupPicking: (() => void) | null = null;

  constructor(private opts: ViewerOptions) {
    this.fullScreenRenderWindow = vtkFullScreenRenderWindow.newInstance({
      container: opts.container,
      containerStyle: { width: "100%", height: "100%" },
      background: opts.background ?? [0.08, 0.08, 0.12],
    });

    this.renderer = this.fullScreenRenderWindow.getRenderer();
    this.renderWindow = this.fullScreenRenderWindow.getRenderWindow();

    this.lookupTable = vtkColorTransferFunction.newInstance();
    this.applyColorPreset("coolToWarm");

    this.mapper = vtkMapper.newInstance({
      interpolateScalarsBeforeMapping: true,
      useLookupTableScalarRange: true,
    });
    this.mapper.setLookupTable(this.lookupTable);

    this.actor = vtkActor.newInstance();
    this.actor.setMapper(this.mapper);
    const actorProperty = this.actor.getProperty();
    actorProperty.setEdgeVisibility(true);
    if (actorProperty.setEdgeColor) {
      actorProperty.setEdgeColor(...(opts.edgeColor ?? [0.72, 0.76, 0.84]));
    }
    if (actorProperty.setLineWidth) actorProperty.setLineWidth(1);
    actorProperty.setLighting(true);
    if (actorProperty.setInterpolationToFlat) actorProperty.setInterpolationToFlat();

    this.picker = vtkCellPicker.newInstance();
    this.picker.setPickFromList(true);
    this.picker.initializePickList();
    this.picker.addPickList(this.actor);

    this.renderer.addActor(this.actor);

    if (opts.allowPicking) this.setupPicking();
  }

  // ── Picking ───────────────────────────────────────────────────────────────

  private setupPicking(): void {
    const container = this.fullScreenRenderWindow.getContainer();
    const handleClick = (event: MouseEvent) => {
      const rect = container.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      const displayCoord: [number, number, number] = [x, rect.height - y, 0];

      this.picker.pick(displayCoord, this.renderer);
      const cellId = this.picker.getCellId();

      if (cellId < 0) {
        this.opts.onPick?.(null);
        return;
      }

      const pickPos = this.picker.getPickPosition();
      let value: number | null = null;

      if (this.currentPolyData && this.currentArrayName) {
        const cellArray = this.currentPolyData.getCellData().getArrayByName(this.currentArrayName);
        if (cellArray) {
          const data = cellArray.getData();
          if (cellId < data.length) value = data[cellId];
        }
      }

      this.opts.onPick?.({ cellId, position: pickPos, value });
    };

    container.addEventListener("click", handleClick);
    this.cleanupPicking = () => container.removeEventListener("click", handleClick);
  }

  // ── Theme ─────────────────────────────────────────────────────────────────

  setBackground(rgb: RGB): void {
    this.renderer.setBackground(rgb);
    if (this.currentPolyData) this.renderWindow.render();
  }

  setEdgeColor(rgb: RGB): void {
    const actorProperty = this.actor.getProperty();
    if (actorProperty.setEdgeColor) actorProperty.setEdgeColor(...rgb);
    if (this.currentPolyData) this.renderWindow.render();
  }

  // ── Data loading ──────────────────────────────────────────────────────────

  /**
   * Fetch and load a single VTP timestep file. Cancellation-safe: if a newer
   * loadTimestep() call starts before this one resolves, this one's result is
   * discarded instead of overwriting the mapper with stale geometry.
   */
  async loadTimestep(url: string): Promise<void> {
    const token = ++this.loadToken;

    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const buffer = await response.arrayBuffer();

    if (token !== this.loadToken || this.disposed) return; // superseded or disposed mid-fetch

    const reader = vtkXMLPolyDataReader.newInstance();
    reader.parseAsArrayBuffer(buffer);
    const polyData = reader.getOutputData(0);

    this.mapper.setInputData(polyData);
    this.currentPolyData = polyData;

    if (!this.cameraInitialized) {
      this.renderer.resetCamera();
      this.cameraInitialized = true;
    }

    if (this.currentArrayName) {
      // Re-apply coloring to the newly loaded polydata using the range already
      // active on the lookup table (not the mapper — vtkMapper doesn't track
      // scalar range itself, the color transfer function does).
      const activeRange = this.lookupTable.getMappingRange() as [number, number];
      this.applyVariableColoringInternal(this.currentArrayName, activeRange);
    }

    this.renderWindow.render();
  }

  // ── Variable coloring ─────────────────────────────────────────────────────

  private applyVariableColoringInternal(varName: string, range?: [number, number]): void {
    if (!this.currentPolyData) return;

    // isPointData is re-derived by whichever data array actually has the name;
    // callers that know point-vs-cell membership use applyVariableColoring().
    const pointArray = this.currentPolyData.getPointData().getArrayByName(varName);
    const cellArray = this.currentPolyData.getCellData().getArrayByName(varName);
    const dataArray = pointArray ?? cellArray;
    if (!dataArray) return;

    if (pointArray) this.mapper.setScalarModeToUsePointFieldData();
    else this.mapper.setScalarModeToUseCellFieldData();

    this.mapper.setColorByArrayName(varName);
    this.mapper.setScalarVisibility(true);

    const resolvedRange = range ?? dataArray.getRange();
    this.lookupTable.setMappingRange(resolvedRange[0], resolvedRange[1]);
    this.lookupTable.updateRange();

    this.currentArrayName = varName;
  }

  /** Apply variable coloring, given a known point/cell range (e.g. from manifest.array_ranges). */
  applyVariableColoring(varName: string, range?: [number, number]): [number, number] {
    this.applyVariableColoringInternal(varName, range);
    this.renderWindow.render();
    return (this.lookupTable.getMappingRange() as [number, number]) ?? range ?? [0, 1];
  }

  clearVariableColoring(): void {
    this.mapper.setScalarVisibility(false);
    this.currentArrayName = null;
    if (this.currentPolyData) this.renderWindow.render();
  }

  setColorPreset(name: ColorPreset): void {
    this.applyColorPreset(name);
    if (this.currentPolyData) this.renderWindow.render();
  }

  private applyColorPreset(name: ColorPreset): void {
    const preset = COLOR_PRESETS[name] ?? COLOR_PRESETS.coolToWarm;
    this.lookupTable.removeAllPoints();
    for (const [x, r, g, b] of preset) {
      this.lookupTable.addRGBPoint(x, r, g, b);
    }
  }

  setScalarRange(range: [number, number]): void {
    this.lookupTable.setMappingRange(range[0], range[1]);
    this.lookupTable.updateRange();
    if (this.currentPolyData) this.renderWindow.render();
  }

  // ── Camera ────────────────────────────────────────────────────────────────

  resetCamera(): void {
    this.renderer.resetCamera();
    this.renderWindow.render();
  }

  // ── Lifecycle ─────────────────────────────────────────────────────────────

  resize(): void {
    this.renderWindow.render();
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.cleanupPicking?.();
    try {
      this.fullScreenRenderWindow.delete();
    } catch (e) {
      console.error("[MeshViewerEngine] dispose error:", e);
    }
  }
}
