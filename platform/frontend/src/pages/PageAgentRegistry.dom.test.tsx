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
import { expect, test } from "vitest";
import { PageAgentRegistry } from "./PageAgentRegistry.tsx";

const NO_MATCH_TEXT = "No matching agents";

function cardNames(): string[] {
  return screen.queryAllByRole("article").map((card) => within(card).getByRole("heading", { level: 3 }).textContent ?? "");
}

test("agent registry: search and domain chip filter the cards, no match shows the empty state, All restores 8", async () => {
  const user = userEvent.setup();
  render(<PageAgentRegistry />);

  expect(screen.getAllByRole("article")).toHaveLength(8);
  expect(screen.queryByText(NO_MATCH_TEXT)).not.toBeInTheDocument();

  const search = screen.getByRole("searchbox", { name: "Search agents" });
  await user.type(search, "THERM");
  expect(cardNames()).toEqual(["Thermal-Hydraulic Modeler", "Material Properties Lookup"]);

  await user.click(screen.getByRole("button", { name: "Core & Fuel" }));
  expect(screen.getByRole("button", { name: "Core & Fuel" })).toHaveAttribute("aria-pressed", "true");
  expect(cardNames()).toEqual(["Thermal-Hydraulic Modeler"]);
  expect(screen.queryByText(NO_MATCH_TEXT)).not.toBeInTheDocument();

  await user.clear(search);
  await user.type(search, "zzz");
  expect(screen.queryAllByRole("article")).toHaveLength(0);
  expect(screen.getByText(NO_MATCH_TEXT)).toBeInTheDocument();
  expect(screen.getByRole("searchbox", { name: "Search agents" })).toBeInTheDocument();

  await user.clear(search);
  await user.click(screen.getByRole("button", { name: "All" }));
  expect(screen.getAllByRole("article")).toHaveLength(8);
  expect(screen.queryByText(NO_MATCH_TEXT)).not.toBeInTheDocument();
});
