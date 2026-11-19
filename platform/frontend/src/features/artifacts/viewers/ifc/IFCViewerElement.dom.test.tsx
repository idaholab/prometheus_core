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

/* The IFC viewer gives its WebGL canvas the app theme's background, and changes it
 * when the theme switches. The engine is replaced by a stub, since jsdom has no WebGL. */
import { act, render, waitFor } from "@testing-library/react";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

const setBackground = vi.hoisted(() => vi.fn());

// jsdom has no matchMedia (useTheme reads it when data-theme is unset) and no
// ResizeObserver (the overlay panels use it).
vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
vi.stubGlobal("matchMedia", (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} }));

vi.mock("./IFCViewer", () => ({
  default: forwardRef<object, { onLoad?: () => void }>(function StubViewer({ onLoad }, ref) {
    useImperativeHandle(ref, () => ({
      setBackground,
      enumerateCategories: async () => [],
      enumerateEquipment: async () => [],
      enumeratePipeRuns: async () => [],
      enumerateWallGroups: async () => [],
      enumerateRoofGroups: async () => [],
      enumerateColumnGroups: async () => [],
    }));
    // Load once, as the real engine does: the element passes a new handler each render.
    const onLoadRef = useRef(onLoad);
    useEffect(() => {
      onLoadRef.current?.();
    }, []);
    return <div />;
  }),
}));

import { IFCViewerElement } from "./IFCViewerElement.tsx";

const DARK = [0.08, 0.08, 0.12];
const LIGHT = [0.91, 0.91, 0.94];

const renderModel = () =>
  render(<IFCViewerElement element={{ type: "custom", name: "IFCViewer", props: { fileUrl: "/model.ifc" } }} />);

const lastBackground = () => setBackground.mock.calls.at(-1)?.[0];

beforeEach(() => setBackground.mockClear());

afterEach(() => {
  document.documentElement.removeAttribute("data-theme");
});

test("the canvas gets the light background under the light app theme", async () => {
  document.documentElement.setAttribute("data-theme", "light");
  renderModel();
  await waitFor(() => expect(lastBackground()).toEqual(LIGHT));
});

test("a switch of the app theme changes the canvas background", async () => {
  document.documentElement.setAttribute("data-theme", "dark");
  renderModel();
  await waitFor(() => expect(lastBackground()).toEqual(DARK));

  await act(async () => {
    document.documentElement.setAttribute("data-theme", "light");
  });

  await waitFor(() => expect(lastBackground()).toEqual(LIGHT));
});
