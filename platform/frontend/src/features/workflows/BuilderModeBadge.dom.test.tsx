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
import { BuilderModeBadge } from "./BuilderModeBadge.tsx";

const badge = () => screen.getByRole("button", { name: /Changing:/ });

test("the badge names the mode and opens a menu of both, with the current one checked", async () => {
  const user = userEvent.setup();
  render(<BuilderModeBadge mode="run" workflowName="Comprehensive Material Analysis" />);

  expect(badge()).toHaveTextContent("Changing:this run");
  expect(badge()).toHaveAttribute("aria-expanded", "false");
  await user.click(badge());

  expect(screen.getByRole("menu", { name: "Builder mode" })).toBeInTheDocument();
  expect(screen.getByRole("menuitemradio", { name: /Change this run/ })).toHaveAttribute("aria-checked", "true");
  expect(screen.getByRole("menuitemradio", { name: /Edit the template/ })).toHaveAccessibleDescription(
    "Change Comprehensive Material Analysis for everyone (new version).",
  );
  expect(screen.getByRole("menuitemradio", { name: /Change this run/ })).toHaveFocus();
});

test("picking the other mode switches to it and closes the menu; picking the current one doesn't", async () => {
  const onChange = vi.fn();
  const user = userEvent.setup();
  render(<BuilderModeBadge mode="template" workflowName="CMA" onChange={onChange} />);

  await user.click(badge());
  await user.click(screen.getByRole("menuitemradio", { name: /Edit the template/ }));
  expect(onChange).not.toHaveBeenCalled();

  await user.click(badge());
  await user.click(screen.getByRole("menuitemradio", { name: /Change this run/ }));
  expect(onChange).toHaveBeenCalledExactlyOnceWith("run");
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(badge()).toHaveFocus();
});

test("the keyboard opens the menu, moves through it, picks one, and Escape closes it", async () => {
  const onChange = vi.fn();
  const user = userEvent.setup();
  render(<BuilderModeBadge mode="run" workflowName="CMA" onChange={onChange} />);

  badge().focus();
  await user.keyboard("{ArrowDown}");
  expect(screen.getByRole("menuitemradio", { name: /Change this run/ })).toHaveFocus();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(badge()).toHaveFocus();

  await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");
  expect(onChange).toHaveBeenCalledExactlyOnceWith("template");
});

test("a click outside closes the menu without switching", async () => {
  const onChange = vi.fn();
  const user = userEvent.setup();
  render(<BuilderModeBadge mode="run" workflowName="CMA" onChange={onChange} />);

  await user.click(badge());
  await user.click(document.body);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(onChange).not.toHaveBeenCalled();
});
