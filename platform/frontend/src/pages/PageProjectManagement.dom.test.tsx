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

// Test plan: project_management_filters_team.

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import { PageProjectManagement } from "./PageProjectManagement.tsx";

const NO_MATCH_TEXT = "No matching team members";

/** The name in each body row of the team table, top to bottom. */
function memberNames(): string[] {
  const table = screen.getByRole("table", { name: "Team members" });
  const body = within(table).getAllByRole("rowgroup")[1];
  return within(body)
    .queryAllByRole("row")
    .map((row) => within(row).getAllByRole("cell")[0].textContent ?? "");
}

/** The member count that the RBAC card of the role shows. */
function roleCardCount(roleName: string): string {
  const heading = screen.getByRole("heading", { name: roleName, level: 3 });
  return heading.parentElement?.textContent?.replace(roleName, "").trim() ?? "";
}

test("project management: search and role filter the team table, no match shows the empty state, RBAC counts keep all members", async () => {
  const user = userEvent.setup();
  render(<PageProjectManagement />);

  expect(memberNames()).toHaveLength(6);
  expect(screen.queryByText(NO_MATCH_TEXT)).not.toBeInTheDocument();

  const search = screen.getByRole("searchbox", { name: "Search team" });
  const role = screen.getByRole("combobox", { name: "Filter by role" });

  await user.type(search, "CHEN");
  expect(memberNames()).toEqual(["Sarah Chen"]);
  expect(roleCardCount("Platform Admin")).toBe("2 members");

  await user.clear(search);
  await user.selectOptions(role, "Platform Admin");
  expect(memberNames()).toEqual(["Dr. Elizabeth Halsey", "Dr. Marcus Vance"]);

  await user.type(search, "vance");
  expect(memberNames()).toEqual(["Dr. Marcus Vance"]);

  await user.clear(search);
  await user.type(search, "zzz");
  expect(screen.getByText(NO_MATCH_TEXT)).toBeInTheDocument();
  expect(screen.queryByRole("table", { name: "Team members" })).not.toBeInTheDocument();
  expect(screen.getByRole("searchbox", { name: "Search team" })).toBeInTheDocument();
  expect(roleCardCount("Platform Admin")).toBe("2 members");

  await user.clear(search);
  await user.selectOptions(role, "Program Manager");
  expect(screen.getByText(NO_MATCH_TEXT)).toBeInTheDocument();
  expect(screen.queryByRole("table", { name: "Team members" })).not.toBeInTheDocument();

  await user.selectOptions(role, "All Roles");
  expect(memberNames()).toHaveLength(6);
  expect(screen.queryByText(NO_MATCH_TEXT)).not.toBeInTheDocument();
});
