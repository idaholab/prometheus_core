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

/* The Mermaid viewer draws with the app theme and draws again when the theme
 * switches; mermaid itself is replaced by a stub, since jsdom has no SVG layout. */
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

const mermaid = vi.hoisted(() => ({
  initialize: vi.fn(),
  render: vi.fn(async () => ({ svg: "<svg><text>drawn</text></svg>", bindFunctions: undefined })),
}));
vi.mock("mermaid", () => ({ default: mermaid }));

// jsdom has no matchMedia; useTheme reads it when data-theme is unset.
vi.stubGlobal("matchMedia", (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} }));

import { MermaidElement } from "./MermaidElement.tsx";

const renderDiagram = () =>
  render(
    <MermaidElement
      element={{ type: "custom", name: "MermaidViewer", props: { diagram: "graph TD\n  A-->B", title: "flow" } }}
    />,
  );

const themesInitialized = () => mermaid.initialize.mock.calls.map(([config]) => config.theme);

beforeEach(() => {
  mermaid.initialize.mockClear();
  mermaid.render.mockClear();
});

afterEach(() => {
  document.documentElement.removeAttribute("data-theme");
});

test("the diagram is drawn with the dark mermaid theme under the dark app theme", async () => {
  document.documentElement.setAttribute("data-theme", "dark");
  renderDiagram();
  await screen.findByText("drawn");
  expect(themesInitialized()).toEqual(["dark"]);
});

test("the diagram is drawn with the default mermaid theme under the light app theme", async () => {
  document.documentElement.setAttribute("data-theme", "light");
  renderDiagram();
  await screen.findByText("drawn");
  expect(themesInitialized()).toEqual(["default"]);
});

test("a switch of the app theme draws the diagram again in the new theme", async () => {
  document.documentElement.setAttribute("data-theme", "dark");
  renderDiagram();
  await screen.findByText("drawn");

  await act(async () => {
    document.documentElement.setAttribute("data-theme", "light");
  });

  await waitFor(() => expect(themesInitialized()).toEqual(["dark", "default"]));
  expect(mermaid.render).toHaveBeenCalledTimes(2);
});
