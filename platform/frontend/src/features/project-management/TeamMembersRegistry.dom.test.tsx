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

// Test plan: team_registry_wires_controls.

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { Role, TeamMember } from "./store/projectManagementModel";
import { TeamMembersRegistry } from "./TeamMembersRegistry.tsx";

const ROLES: Role[] = [
  { id: "platform-admin", name: "Platform Admin", permissions: [] },
  { id: "sme-reviewer", name: "SME Reviewer", permissions: [] },
];

const MEMBERS: TeamMember[] = [
  {
    id: "m-1",
    name: "Ada Example",
    email: "ada@example.test",
    role: "platform-admin",
    department: "Ops",
    status: "active",
    lastActive: "today",
  },
  {
    id: "m-2",
    name: "Ben Sample",
    email: "ben@example.test",
    role: "sme-reviewer",
    department: "Review",
    status: "invited",
    lastActive: "yesterday",
  },
];

test("team registry shows query and role in its controls, reports edits, and swaps the table for the no-match state", async () => {
  const user = userEvent.setup();
  const onQueryChange = vi.fn();
  const onRoleChange = vi.fn();
  const props = {
    members: MEMBERS,
    roles: ROLES,
    query: "x",
    onQueryChange,
    role: "sme-reviewer",
    onRoleChange,
  };
  const { rerender } = render(<TeamMembersRegistry {...props} noMatches={false} />);

  const search = screen.getByRole("searchbox", { name: "Search team" });
  expect(search).toHaveValue("x");

  await user.type(search, "y");
  expect(onQueryChange).toHaveBeenLastCalledWith("xy");

  const roleSelect = screen.getByRole("combobox", { name: "Filter by role" });
  expect(roleSelect).toHaveValue("sme-reviewer");

  await user.selectOptions(roleSelect, "All Roles");
  expect(onRoleChange).toHaveBeenLastCalledWith("all");

  const table = screen.getByRole("table", { name: "Team members" });
  const rowNames = within(table)
    .getAllByRole("row")
    .slice(1)
    .map((row) => within(row).getAllByRole("cell")[0].textContent);
  expect(rowNames).toEqual(["Ada Example", "Ben Sample"]);
  expect(screen.queryByText("No matching team members")).not.toBeInTheDocument();

  rerender(<TeamMembersRegistry {...props} noMatches />);

  expect(screen.queryByRole("table", { name: "Team members" })).not.toBeInTheDocument();
  expect(screen.getByText("No matching team members")).toBeInTheDocument();
  expect(screen.getByText("Try another search or role")).toBeInTheDocument();
  expect(screen.getByRole("searchbox", { name: "Search team" })).toBeInTheDocument();
});
