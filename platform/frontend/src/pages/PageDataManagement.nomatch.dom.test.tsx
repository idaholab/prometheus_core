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

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { PageDataManagement } from "./PageDataManagement.tsx";

/* The real store with every mesh artifact removed, so the Meshes chip matches nothing.
 * The sources stay, so the page status stays "ready". The barrel and DataManagement
 * import this same module, so the mock reaches the page. */
vi.mock("@/features/data-management/store/dataManagement", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/features/data-management/store/dataManagement")>();
  type State = ReturnType<typeof real.useDataManagement>;
  const cache = new WeakMap<State, State>();
  return {
    ...real,
    useDataManagement: () => {
      const state = real.useDataManagement();
      let noMeshes = cache.get(state);
      if (!noMeshes) {
        noMeshes = { ...state, artifacts: state.artifacts.filter((a) => a.type !== "mesh") };
        cache.set(state, noMeshes);
      }
      return noMeshes;
    },
  };
});

const CHIP_NAMES = ["All", "Reports", "Meshes", "Results"];

function bodyRows(): HTMLElement[] {
  return within(screen.getByRole("table", { name: "Generated artifacts" })).getAllByRole("row").slice(1);
}

function chips(): HTMLElement {
  return screen.getByRole("group", { name: "Artifact types" });
}

// Test plan: data_management_page_shows_no_match.
test("data management: a type chip with no artifact shows No matching artifacts. and keeps the chips; All restores the rows", async () => {
  const user = userEvent.setup();
  render(<PageDataManagement />);

  expect(bodyRows()).toHaveLength(5);
  expect(screen.queryByText("No matching artifacts.")).not.toBeInTheDocument();

  await user.click(within(chips()).getByRole("button", { name: "Meshes" }));
  expect(bodyRows()).toHaveLength(0);
  expect(screen.getByText("No matching artifacts.")).toBeInTheDocument();
  expect(screen.queryByText("No rows yet.")).not.toBeInTheDocument();
  expect(within(chips()).getAllByRole("button").map((b) => b.textContent)).toEqual(CHIP_NAMES);
  expect(within(chips()).getByRole("button", { name: "Meshes" })).toHaveAttribute("aria-pressed", "true");

  await user.click(within(chips()).getByRole("button", { name: "All" }));
  expect(bodyRows()).toHaveLength(5);
  expect(screen.queryByText("No matching artifacts.")).not.toBeInTheDocument();
});
