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
import { NodeInspector, type InspectedNode } from "./NodeInspector.tsx";

const NODE: InspectedNode = {
  name: "Radiation Damage",
  tone: "analysis",
  skillId: "analyze_radiation_damage",
  inputs: [
    { name: "material_id", value: "from input.material_id" },
    { name: "neutron_flux" },
    { name: "temperature_c", value: "from input.context" },
  ],
  outputs: [{ name: "to_context", value: "radiation" }],
};

test("a node shows its name, skill id, a field per input and output, and Remove Node", () => {
  render(<NodeInspector node={NODE} />);

  expect(screen.getByText("Radiation Damage")).toBeInTheDocument();
  expect(screen.getByText("skill_id: analyze_radiation_damage")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Inputs" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Output" })).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "material_id" })).toHaveValue("from input.material_id");
  expect(screen.getByRole("textbox", { name: "neutron_flux" })).toHaveValue("");
  expect(screen.getByRole("textbox", { name: "neutron_flux" })).toHaveAttribute("placeholder", "— optional —");
  expect(screen.getByRole("textbox", { name: "temperature_c" })).toHaveValue("from input.context");
  expect(screen.getByRole("textbox", { name: "to_context" })).toHaveValue("radiation");
  expect(screen.getByRole("button", { name: "Remove Node" })).toBeInTheDocument();
  expect(screen.queryByText("No node selected.")).not.toBeInTheDocument();
});

test("no node shows the empty state and no fields", () => {
  render(<NodeInspector node={null} />);

  expect(screen.getByText("No node selected.")).toBeInTheDocument();
  expect(screen.getByText("Click a node to edit its inputs.")).toBeInTheDocument();
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Remove Node" })).not.toBeInTheDocument();
});

test("typing in a field and clicking Remove Node leave the node in place", async () => {
  const user = userEvent.setup();
  render(<NodeInspector node={NODE} />);

  await user.type(screen.getByRole("textbox", { name: "to_context" }), "_v2");
  await user.click(screen.getByRole("button", { name: "Remove Node" }));

  expect(screen.getByText("Radiation Damage")).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "material_id" })).toHaveValue("from input.material_id");
});
