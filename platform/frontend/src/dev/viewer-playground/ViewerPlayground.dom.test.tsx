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

/* The playground page shows its developer banner, one section per case, an empty
 * state with no cases, and a theme button. The viewers are replaced by a stub that
 * names the element it gets, since the real ones need WebGL and WASM. */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import type { ViewerCase } from "./viewerCase";

// jsdom has no matchMedia; useTheme reads it when data-theme is unset.
vi.stubGlobal("matchMedia", (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} }));

vi.mock("@/features/artifacts", () => ({
  artifactsToElements: (artifacts: { name: string }[]) => artifacts.map((a) => ({ type: "custom", name: a.name })),
  ElementList: ({ elements }: { elements: { name: string }[] }) => <div>viewer for {elements[0].name}</div>,
}));

import { ViewerPlayground } from "./ViewerPlayground";

const CASE: ViewerCase = {
  title: "IFC model",
  note: "A generated building.",
  viewer: "IFCViewer",
  artifact: { artifact_id: "sample-ifc", name: "model.ifc", description: "", tags: [], render_hint: "ifc" },
  files: {},
};

afterEach(() => {
  document.documentElement.removeAttribute("data-theme");
});

test("the page shows the developer banner and one section per case with its viewer", () => {
  render(<ViewerPlayground cases={[CASE]} />);
  expect(screen.getByRole("heading", { level: 1, name: "Viewer playground" })).toBeInTheDocument();
  expect(screen.getByText("Developer page. Not part of the Prometheus app.")).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 2, name: "IFC model" })).toBeInTheDocument();
  expect(screen.getByText("A generated building.")).toBeInTheDocument();
  expect(screen.getByText("viewer for model.ifc")).toBeInTheDocument();
});

test("the page with no cases says where to add one", () => {
  render(<ViewerPlayground cases={[]} />);
  expect(screen.getByText("No viewer cases found.")).toBeInTheDocument();
  expect(screen.getByText("Add a file to src/dev/viewer-playground/cases/.")).toBeInTheDocument();
});

test("the theme button switches the app theme", async () => {
  const user = userEvent.setup();
  document.documentElement.setAttribute("data-theme", "dark");
  render(<ViewerPlayground cases={[CASE]} />);

  await user.click(screen.getByRole("button", { name: "Light theme" }));

  expect(document.documentElement).toHaveAttribute("data-theme", "light");
  expect(screen.getByRole("button", { name: "Dark theme" })).toBeInTheDocument();
});
