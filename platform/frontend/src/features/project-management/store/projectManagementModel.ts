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

/**
 * Types and pure helpers for the Project Management page.
 *
 * Kept as a leaf module with no imports, so it is unit-testable under
 * `node --test` (`projectManagement.ts` pulls in React and can only run
 * inside Vite).
 */

export type MemberStatus = "active" | "invited" | "suspended";

export type RoleId =
  | "platform-admin"
  | "design-engineer"
  | "sme-reviewer"
  | "licensing-analyst"
  | "program-manager"
  | "agent-developer";

export interface TeamMember {
  id: string;
  name: string;
  email: string;
  role: RoleId;
  department: string;
  status: MemberStatus;
  lastActive: string;
}

export interface Role {
  id: RoleId;
  name: string;
  permissions: string[];
}

export type LoadStatus = "ready" | "empty" | "loading" | "error";

export interface ProjectManagementState {
  status: LoadStatus;
  members: TeamMember[];
  roles: Role[];
}

/** Count the members of each role; a role with no member counts 0. */
export function countMembersByRole(members: TeamMember[], roles: Role[]): Record<RoleId, number> {
  const counts = {} as Record<RoleId, number>;
  for (const role of roles) counts[role.id] = 0;
  for (const member of members) counts[member.role] = (counts[member.role] ?? 0) + 1;
  return counts;
}
