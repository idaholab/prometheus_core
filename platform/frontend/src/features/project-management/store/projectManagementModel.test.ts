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

// Test plan: project_management_counts. countMembersByRole() returns the member count of each
// of the six roles, with 0 for a role that has no member, and memberCountLabel() says
// "1 member" for one and "N members" otherwise.
// Test plan: team_filter_matches_name_email_role. filterList() with TEAM_FILTER keeps a member
// only when the trimmed query is a case-insensitive substring of the name or the email and the
// role equals the selected role; a blank query or ALL turns off that half.
import assert from "node:assert/strict";
import { test } from "vitest";

import { ALL, filterList } from "@/lib/listFilter";

import {
  countMembersByRole,
  TEAM_FILTER,
  type Role,
  type RoleId,
  type TeamMember,
} from "./projectManagementModel.ts";

const ROLE_IDS: RoleId[] = [
  "platform-admin",
  "design-engineer",
  "sme-reviewer",
  "licensing-analyst",
  "program-manager",
  "agent-developer",
];

const roles = (): Role[] => ROLE_IDS.map((id) => ({ id, name: id, permissions: [] }));

const member = (id: string, role: RoleId): TeamMember => ({
  id,
  name: `Member ${id}`,
  email: `${id}@example.test`,
  role,
  department: "Reactor Design",
  status: "active",
  lastActive: "Just now",
});

// projectManagement.ts imports React and an `@/` path, so node cannot load its TEAM_MEMBERS;
// this fixture has the same six members by role.
const teamMembersShape = (): TeamMember[] => [
  member("member-1", "platform-admin"),
  member("member-2", "design-engineer"),
  member("member-3", "sme-reviewer"),
  member("member-4", "platform-admin"),
  member("member-5", "agent-developer"),
  member("member-6", "licensing-analyst"),
];

test("countMembersByRole counts each role and gives 0 to a role with no member", () => {
  const members = [member("a", "platform-admin"), member("b", "platform-admin"), member("c", "sme-reviewer")];

  assert.deepEqual(countMembersByRole(members, roles()), {
    "platform-admin": 2,
    "design-engineer": 0,
    "sme-reviewer": 1,
    "licensing-analyst": 0,
    "program-manager": 0,
    "agent-developer": 0,
  });
});

test("countMembersByRole on the TEAM_MEMBERS shape sums to the member count", () => {
  const members = teamMembersShape();
  const counts = countMembersByRole(members, roles());

  assert.deepEqual(counts, {
    "platform-admin": 2,
    "design-engineer": 1,
    "sme-reviewer": 1,
    "licensing-analyst": 1,
    "program-manager": 0,
    "agent-developer": 1,
  });
  const total = Object.values(counts).reduce((sum, n) => sum + n, 0);
  assert.equal(total, members.length);
});

// The name, role, department and status of each TEAM_MEMBERS entry in projectManagement.ts; each
// email keeps its local part on the made-up example.test domain.
const teamMembers = (): TeamMember[] => [
  {
    id: "member-1",
    name: "Dr. Elizabeth Halsey",
    email: "e.halsey@example.test",
    role: "platform-admin",
    department: "Reactor Design",
    status: "active",
    lastActive: "Just now",
  },
  {
    id: "member-2",
    name: "Viktor Kerimov",
    email: "v.kerimov@example.test",
    role: "design-engineer",
    department: "Safety Analysis",
    status: "active",
    lastActive: "12m ago",
  },
  {
    id: "member-3",
    name: "Sarah Chen",
    email: "s.chen@example.test",
    role: "sme-reviewer",
    department: "Neutronics",
    status: "active",
    lastActive: "2h ago",
  },
  {
    id: "member-4",
    name: "Dr. Marcus Vance",
    email: "m.vance@example.test",
    role: "platform-admin",
    department: "Thermal-Hydraulics",
    status: "active",
    lastActive: "Just now",
  },
  {
    id: "member-5",
    name: "Elena Rostova",
    email: "e.rostova@example.test",
    role: "agent-developer",
    department: "Reactor Design",
    status: "invited",
    lastActive: "Pending",
  },
  {
    id: "member-6",
    name: "Aris Thorne",
    email: "a.thorne@example.test",
    role: "licensing-analyst",
    department: "Safety Analysis",
    status: "suspended",
    lastActive: "3 days ago",
  },
];

const visibleNames = (query: string, facet: string): string[] =>
  filterList(teamMembers(), TEAM_FILTER, { query, facet }).map((m) => m.name);

test("TEAM_FILTER search matches the name ignoring case", () => {
  assert.deepEqual(visibleNames("CHEN", ALL), ["Sarah Chen"]);
});

test("TEAM_FILTER search matches the email", () => {
  assert.deepEqual(visibleNames("a.thorne", ALL), ["Aris Thorne"]);
});

test("TEAM_FILTER search does not read the department or the status", () => {
  assert.deepEqual(visibleNames("Neutronics", ALL), []);
  assert.deepEqual(visibleNames("suspended", ALL), []);
});

test("TEAM_FILTER facet keeps the members of the selected role id", () => {
  assert.deepEqual(visibleNames("", "platform-admin"), ["Dr. Elizabeth Halsey", "Dr. Marcus Vance"]);
  assert.deepEqual(visibleNames("", "program-manager"), []);
});

test("TEAM_FILTER search and facet together keep only members that match both", () => {
  assert.deepEqual(visibleNames("vance", "platform-admin"), ["Dr. Marcus Vance"]);
});

test("TEAM_FILTER with a blank query and ALL keeps all six members in order", () => {
  assert.deepEqual(visibleNames("", ALL), [
    "Dr. Elizabeth Halsey",
    "Viktor Kerimov",
    "Sarah Chen",
    "Dr. Marcus Vance",
    "Elena Rostova",
    "Aris Thorne",
  ]);
});
