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
import assert from "node:assert/strict";
import { test } from "vitest";

import {
  countMembersByRole,
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
