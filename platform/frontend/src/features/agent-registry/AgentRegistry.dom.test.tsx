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
import { AgentRegistry } from "./AgentRegistry.tsx";

test("agent registry with no agents keeps the toolbar wired to its props and shows the empty state", async () => {
  const user = userEvent.setup();
  const onQueryChange = vi.fn();
  const onDomainChange = vi.fn();
  render(
    <AgentRegistry
      agents={[]}
      status="empty"
      query="x"
      onQueryChange={onQueryChange}
      domain={ALL}
      onDomainChange={onDomainChange}
      noMatches={false}
    />,
  );

  const search = screen.getByRole("searchbox", { name: "Search agents" });
  expect(search).toHaveValue("x");

  await user.type(search, "y");
  expect(onQueryChange).toHaveBeenLastCalledWith("xy");

  await user.click(screen.getByRole("button", { name: "Core & Fuel" }));
  expect(onDomainChange).toHaveBeenCalledWith("Core & Fuel");

  expect(screen.getByText("No agents are registered")).toBeInTheDocument();
  expect(screen.queryByText("No matching agents")).not.toBeInTheDocument();
});
