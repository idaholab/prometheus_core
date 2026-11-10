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

/* The example for component tests: render into jsdom, find elements by role and
 * accessible name, and act through user-event the way a person would. */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { expect, test } from "vitest";
import { FilterChips } from "./FilterChips.tsx";

const CHIPS = [
  { id: "all", label: "All" },
  { id: "csv", label: "CSV" },
  { id: "pdf", label: "PDF" },
];

/** FilterChips with its selection held in state, as a page would hold it. */
function Harness() {
  const [selected, setSelected] = useState("all");
  return <FilterChips chips={CHIPS} selected={selected} label="File type" onSelect={setSelected} />;
}

test("clicking a chip presses it and releases the one before", async () => {
  const user = userEvent.setup();
  render(<Harness />);

  expect(screen.getByRole("group", { name: "File type" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");

  await user.click(screen.getByRole("button", { name: "CSV" }));

  expect(screen.getByRole("button", { name: "CSV" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "false");
});
