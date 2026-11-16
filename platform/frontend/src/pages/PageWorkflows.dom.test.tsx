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
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { PageWorkflows } from "./PageWorkflows.tsx";

// React Flow measures its container and watches it for resizes; jsdom has neither.
beforeEach(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});
afterEach(() => vi.unstubAllGlobals());

const commitButtons = () =>
  within(screen.getByRole("group", { name: "Workflow actions" }))
    .getAllByRole("button")
    .map((b) => b.textContent);

test("Modify Plan's main click opens the Builder changing this run", async () => {
  const user = userEvent.setup();
  render(<PageWorkflows />);

  await user.click(screen.getByRole("button", { name: "Modify Plan" }));

  expect(screen.getByRole("button", { name: /Changing:/ })).toHaveTextContent("this run");
  expect(screen.getByText(/Changes apply to this run only\. The template \(v1\.2\.0\) is untouched\./)).toBeInTheDocument();
  expect(commitButtons()).toEqual(["Save as variant", "Propose new version", "Run once"]);
  expect(screen.getByRole("region", { name: "Canvas" })).not.toHaveTextContent("Drag a skill here to begin");
});

test("Edit the template opens the Builder changing the template, and the badge switches modes", async () => {
  const user = userEvent.setup();
  render(<PageWorkflows />);

  await user.click(screen.getByRole("button", { name: "More Modify Plan options" }));
  expect(screen.getByRole("menuitem", { name: /Change this run/ })).toHaveAccessibleDescription(
    "Default. Tweak steps for this run only; the template is untouched.",
  );
  await user.click(screen.getByRole("menuitem", { name: /Edit the template/ }));

  expect(screen.getByRole("button", { name: /Changing:/ })).toHaveTextContent("the template");
  expect(
    screen.getByText("Editing the template. Saving creates v1.3.0 for everyone who uses Comprehensive Material Analysis."),
  ).toBeInTheDocument();
  expect(commitButtons()).toEqual(["Validate", "Save", "Run Workflow"]);

  await user.click(screen.getByRole("button", { name: /Changing:/ }));
  await user.click(screen.getByRole("menuitemradio", { name: /Change this run/ }));
  expect(commitButtons()).toEqual(["Save as variant", "Propose new version", "Run once"]);
});

test("New Workflow opens the Builder changing the template, on an empty canvas", async () => {
  const user = userEvent.setup();
  render(<PageWorkflows />);

  await user.click(screen.getByRole("button", { name: "New Workflow" }));

  expect(screen.getByRole("button", { name: /Changing:/ })).toHaveTextContent("the template");
  expect(screen.getByText("Drag a skill here to begin")).toBeInTheDocument();
  expect(screen.getByText("No node selected.")).toBeInTheDocument();
});

test("the commit buttons do nothing yet and log no errors", async () => {
  const error = vi.spyOn(console, "error").mockImplementation(() => {});
  const user = userEvent.setup();
  render(<PageWorkflows />);

  await user.click(screen.getByRole("button", { name: "Modify Plan" }));
  for (const name of ["Save as variant", "Propose new version", "Run once"]) {
    await user.click(screen.getByRole("button", { name }));
  }
  await user.click(screen.getByRole("button", { name: /Changing:/ }));
  await user.click(screen.getByRole("menuitemradio", { name: /Edit the template/ }));
  for (const name of ["Validate", "Save", "Run Workflow"]) {
    await user.click(screen.getByRole("button", { name }));
  }

  expect(commitButtons()).toEqual(["Validate", "Save", "Run Workflow"]);
  expect(error).not.toHaveBeenCalled();
  error.mockRestore();
});
