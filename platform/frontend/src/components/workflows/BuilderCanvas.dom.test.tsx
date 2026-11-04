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
import { expect, test } from "vitest";
import { BuilderCanvas } from "./BuilderCanvas.tsx";

test("an empty canvas shows the drop area, the or divider and Start from template", async () => {
  const user = userEvent.setup();
  render(<BuilderCanvas nodes={[]} wires={[]} />);

  expect(screen.getByText("Drag a skill here to begin")).toBeInTheDocument();
  expect(screen.getByText("or")).toBeInTheDocument();
  expect(screen.getByRole("group", { name: "Zoom" })).toBeInTheDocument();

  // Display only: clicking it changes nothing.
  await user.click(screen.getByRole("button", { name: "Start from template" }));
  expect(screen.getByText("Drag a skill here to begin")).toBeInTheDocument();
});
