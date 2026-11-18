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
import { WorkflowHistory } from "./WorkflowHistory.tsx";
import type { WorkflowVersion } from "./VersionItem.tsx";

const VERSIONS: WorkflowVersion[] = [
  { id: "v1.2.0", version: "v1.2.0", summary: "+ QA Gate after analyses", date: "2 days ago", author: "V. Kerimov", latest: true },
  { id: "v1.1.0", version: "v1.1.0", summary: "Swapped Thermal agent v1.8→v2.0", date: "Oct 1", author: "Dr. Halsey" },
  { id: "v1.0.0", version: "v1.0.0", summary: "Initial template", date: "Sep 12", author: "platform-team" },
];

test("the list shows every version, newest first, with its summary, date and author", () => {
  render(<WorkflowHistory versions={VERSIONS} selectedId="v1.2.0" />);

  const list = screen.getByRole("region", { name: "Version history" });
  expect(within(list).getByRole("heading", { name: "Version history" })).toBeInTheDocument();
  const items = within(list).getAllByRole("article");
  expect(items.map((item) => item.getAttribute("aria-label"))).toEqual(["v1.2.0", "v1.1.0", "v1.0.0"]);
  expect(within(items[1]).getByText("Swapped Thermal agent v1.8→v2.0")).toBeInTheDocument();
  expect(within(items[1]).getByText("Oct 1 · by Dr. Halsey")).toBeInTheDocument();
});

test("only the latest version has the Latest badge, and only the selected one is current", () => {
  render(<WorkflowHistory versions={VERSIONS} selectedId="v1.2.0" />);

  const [latest, ...older] = screen.getAllByRole("article");
  expect(within(latest).getByText("Latest")).toBeInTheDocument();
  expect(latest).toHaveAttribute("aria-current", "true");
  for (const item of older) {
    expect(within(item).queryByText("Latest")).not.toBeInTheDocument();
    expect(item).not.toHaveAttribute("aria-current");
  }
});

test("clicking a version changes nothing and logs no errors", async () => {
  const error = vi.spyOn(console, "error").mockImplementation(() => {});
  const user = userEvent.setup();
  render(<WorkflowHistory versions={VERSIONS} selectedId="v1.2.0" />);

  await user.click(screen.getByRole("article", { name: "v1.0.0" }));

  expect(screen.getByRole("article", { name: "v1.2.0" })).toHaveAttribute("aria-current", "true");
  expect(screen.getByRole("article", { name: "v1.0.0" })).not.toHaveAttribute("aria-current");
  expect(error).not.toHaveBeenCalled();
  error.mockRestore();
});
