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

import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import { toggleSource } from "@/features/data-management";
import { PageDataManagement } from "./PageDataManagement.tsx";

const SOURCE_ID = "mcnp-input-decks";
const SWITCH_NAME = "Enable MCNP Input Deck Repository";

/** The artifact name in each body row of the artifacts table, top to bottom. */
function artifactNames(): string[] {
  return within(screen.getByRole("table", { name: "Generated artifacts" }))
    .getAllByRole("row")
    .slice(1)
    .map((row) => within(row).getAllByRole("cell")[0].textContent ?? "");
}

function chip(name: string): HTMLElement {
  return within(screen.getByRole("group", { name: "Artifact types" })).getByRole("button", { name });
}

// Test plan: data_management_page_toggles_and_filters.
test("data management: type chips filter the artifacts, a source switch flips and keeps its state across a remount", async () => {
  const user = userEvent.setup();
  try {
    const { unmount } = render(<PageDataManagement />);

    expect(artifactNames()).toHaveLength(6);
    expect(chip("All")).toHaveAttribute("aria-pressed", "true");

    await user.click(chip("Meshes"));
    expect(chip("Meshes")).toHaveAttribute("aria-pressed", "true");
    expect(artifactNames()).toEqual(["core_mesh_v3.exo"]);

    await user.click(chip("Reports"));
    expect(artifactNames()).toEqual(["thermal_hydraulic_summary.pdf", "neutronics_report.pdf"]);

    await user.click(chip("Results"));
    expect(artifactNames()).toEqual(["dose_rate_map.csv", "cfd_flow_field.vtu", "keff_tally_results.csv"]);

    await user.click(chip("All"));
    expect(artifactNames()).toHaveLength(6);

    await user.click(chip("Meshes"));
    expect(screen.getByRole("checkbox", { name: SWITCH_NAME })).toBeChecked();
    await user.click(screen.getByRole("checkbox", { name: SWITCH_NAME }));
    expect(screen.getByRole("checkbox", { name: SWITCH_NAME })).not.toBeChecked();

    unmount();
    render(<PageDataManagement />);
    expect(screen.getByRole("checkbox", { name: SWITCH_NAME })).not.toBeChecked();
    expect(chip("All")).toHaveAttribute("aria-pressed", "true");
    expect(artifactNames()).toHaveLength(6);
  } finally {
    // The store is a module singleton: leave the placeholder state for the other tests.
    const box = screen.queryByRole<HTMLInputElement>("checkbox", { name: SWITCH_NAME });
    if (box && !box.checked) act(() => toggleSource(SOURCE_ID));
  }
});
