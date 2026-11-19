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
import { TweakStepInspector, type TweakedStep } from "./TweakStepInspector.tsx";

const STEP: TweakedStep = {
  name: "Corrosion",
  tone: "analysis",
  agent: "Corrosion Agent v2.1",
  agentOptions: ["Corrosion Agent v2.0", "Corrosion Agent v2.1"],
  settings: [{ name: "temperature_c", value: "from input.context" }],
};

test("a step shows its name, agent, settings, the skip toggle and the template note, with no Remove Node", () => {
  render(<TweakStepInspector step={STEP} />);

  expect(screen.getByText("Tweak Step")).toBeInTheDocument();
  expect(screen.getByText("Corrosion")).toBeInTheDocument();
  const agent = screen.getByRole("combobox", { name: "Agent" });
  expect(agent).toHaveValue("Corrosion Agent v2.1");
  // The current agent is listed once, first.
  expect(Array.from((agent as HTMLSelectElement).options, (o) => o.value)).toEqual([
    "Corrosion Agent v2.1",
    "Corrosion Agent v2.0",
  ]);
  expect(screen.getByRole("textbox", { name: "temperature_c" })).toHaveValue("from input.context");
  expect(screen.getByRole("checkbox", { name: "Skip this step for this run" })).not.toBeChecked();
  expect(screen.getByText('To add, wire or remove steps, switch to "the template".')).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Remove Node" })).not.toBeInTheDocument();
});

test("no step shows the empty state, and still the template note", () => {
  render(<TweakStepInspector step={null} />);

  expect(screen.getByText("No step selected.")).toBeInTheDocument();
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(screen.getByText('To add, wire or remove steps, switch to "the template".')).toBeInTheDocument();
});

test("the dropdown and toggle can be used and log no errors", async () => {
  const error = vi.spyOn(console, "error").mockImplementation(() => {});
  const user = userEvent.setup();
  render(<TweakStepInspector step={STEP} />);

  await user.selectOptions(screen.getByRole("combobox", { name: "Agent" }), "Corrosion Agent v2.0");
  await user.click(screen.getByRole("checkbox", { name: "Skip this step for this run" }));

  expect(error).not.toHaveBeenCalled();
  error.mockRestore();
});
