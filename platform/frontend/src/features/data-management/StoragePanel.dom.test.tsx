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

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ALL } from "@/lib/listFilter";
import { StoragePanel } from "./StoragePanel.tsx";

const BASE = { usedLabel: "1.2 GB", totalLabel: "10 GB", percent: 12 };

test("storage_panel_wires_chips_and_no_match: the selected chip is pressed and a click reports its type", async () => {
  const user = userEvent.setup();
  const onSelectType = vi.fn();
  render(<StoragePanel {...BASE} artifacts={[]} selectedType="mesh" onSelectType={onSelectType} noMatches={false} />);

  expect(screen.getByRole("button", { name: "Meshes" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "false");

  await user.click(screen.getByRole("button", { name: "Reports" }));
  expect(onSelectType).toHaveBeenLastCalledWith("report");

  await user.click(screen.getByRole("button", { name: "All" }));
  expect(onSelectType).toHaveBeenLastCalledWith(ALL);
});

test("storage_panel_wires_chips_and_no_match: noMatches shows No matching artifacts. instead of the default", () => {
  const { rerender } = render(
    <StoragePanel {...BASE} artifacts={[]} selectedType="report" onSelectType={() => {}} noMatches />,
  );

  expect(screen.getByText("No matching artifacts.")).toBeInTheDocument();
  expect(screen.queryByText("No rows yet.")).not.toBeInTheDocument();

  rerender(<StoragePanel {...BASE} artifacts={[]} selectedType={ALL} onSelectType={() => {}} noMatches={false} />);

  expect(screen.getByText("No rows yet.")).toBeInTheDocument();
  expect(screen.queryByText("No matching artifacts.")).not.toBeInTheDocument();
});
