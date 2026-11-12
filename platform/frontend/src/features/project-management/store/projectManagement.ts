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
 * Holds the Project Management page state: the team members and the role
 * catalogue. Same useSyncExternalStore pattern as store/session.ts.
 *
 * The state is placeholder data until PPLT-244 adds the load; there is no
 * setter yet.
 */
import { useSyncExternalStore } from "react";
import type { ProjectManagementState, Role, TeamMember } from "./projectManagementModel";

// placeholder: replace with API (see PPLT-244)
export const TEAM_MEMBERS: TeamMember[] = [
  {
    id: "member-1",
    name: "Dr. Elizabeth Halsey",
    email: "e.halsey@prometheus.gov",
    role: "platform-admin",
    department: "Reactor Design",
    status: "active",
    lastActive: "Just now",
  },
  {
    id: "member-2",
    name: "Viktor Kerimov",
    email: "v.kerimov@prometheus.gov",
    role: "design-engineer",
    department: "Safety Analysis",
    status: "active",
    lastActive: "12m ago",
  },
  {
    id: "member-3",
    name: "Sarah Chen",
    email: "s.chen@prometheus.gov",
    role: "sme-reviewer",
    department: "Neutronics",
    status: "active",
    lastActive: "2h ago",
  },
  {
    id: "member-4",
    name: "Dr. Marcus Vance",
    email: "m.vance@prometheus.gov",
    role: "platform-admin",
    department: "Thermal-Hydraulics",
    status: "active",
    lastActive: "Just now",
  },
  {
    id: "member-5",
    name: "Elena Rostova",
    email: "e.rostova@prometheus.gov",
    role: "agent-developer",
    department: "Reactor Design",
    status: "invited",
    lastActive: "Pending",
  },
  {
    id: "member-6",
    name: "Aris Thorne",
    email: "a.thorne@prometheus.gov",
    role: "licensing-analyst",
    department: "Safety Analysis",
    status: "suspended",
    lastActive: "3 days ago",
  },
];

// placeholder: replace with API (see PPLT-244)
export const ROLES: Role[] = [
  {
    id: "platform-admin",
    name: "Platform Admin",
    permissions: [
      "Manage agents, data access, classification",
      "Agent card review and approval",
      "Template-level checkpoint authoring",
      "Org-wide activity visibility, raw telemetry",
    ],
  },
  {
    id: "design-engineer",
    name: "Design Engineer",
    permissions: [
      "Run agentic workflows (free-form & templated)",
      "Direct agent invocation from registry",
      "Insert ad-hoc checkpoints in own tasks",
      "Artifact search and review (project-scoped)",
    ],
  },
  {
    id: "sme-reviewer",
    name: "SME Reviewer",
    permissions: [
      "Approve/reject agent outputs at checkpoints",
      "Review inputs, confidence, & requirements",
      "Artifact review with full provenance",
      "Evidence package assembly support",
    ],
  },
  {
    id: "licensing-analyst",
    name: "Licensing Analyst",
    permissions: [
      "Search artifacts by safety claim or requirement",
      "View full provenance and approval chain",
      "Workflow visualization (read-only)",
      "Regulatory submission assembly from traced evidence",
    ],
  },
  {
    id: "program-manager",
    name: "Program Manager",
    permissions: [
      "Program-level status, cost and risk tracking",
      "Aggregate agent telemetry",
      "Cross-user activity visibility",
    ],
  },
  {
    id: "agent-developer",
    name: "Agent Developer",
    permissions: [
      "Agent card authoring and versioning",
      "Interface contract maintenance",
      "Aggregate telemetry for own agents",
    ],
  },
];

const state: ProjectManagementState = { status: "ready", members: TEAM_MEMBERS, roles: ROLES };
const listeners = new Set<() => void>();

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}
function getSnapshot(): ProjectManagementState {
  return state;
}

/** Subscribe a component to the Project Management page state. */
export function useProjectManagement(): ProjectManagementState {
  return useSyncExternalStore(subscribe, getSnapshot);
}
