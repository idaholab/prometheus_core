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

import { Plus } from "lucide-react";
import { SectionLabel } from "@/components/ui/SectionLabel";
import type { MemberStatus, Role, TeamMember } from "./store/projectManagementModel";
import { DataTable, type DataTableColumn } from "@/components/ui/DataTable";
import { SearchInput } from "@/components/ui/SearchInput";
import { Button } from "@/components/ui/Button";
import { StatusPill, type StatusPillTone } from "@/components/ui/StatusPill";
import { Tag } from "@/components/ui/Tag";

const STATUS_TONE: Record<MemberStatus, StatusPillTone> = {
  active: "success",
  invited: "info",
  suspended: "error",
};

interface Props {
  members: TeamMember[];
  roles: Role[];
}

/**
 * Team members registry: search bar, role filter, invite button and the
 * member table. Search, filter and the row actions are not wired yet (PM-4).
 */
export function TeamMembersRegistry({ members, roles }: Props) {
  const roleNames = new Map(roles.map((role) => [role.id, role.name]));

  const columns: DataTableColumn<TeamMember>[] = [
    { id: "name", header: "Name", value: (m) => m.name, className: "font-semibold text-base-content" },
    { id: "email", header: "Email Address", value: (m) => m.email, className: "text-base-content/60" },
    {
      id: "role",
      header: "Role",
      value: (m) => roleNames.get(m.role) ?? m.role,
      cell: (m) => <Tag label={roleNames.get(m.role) ?? m.role} />,
    },
    { id: "department", header: "Department", value: (m) => m.department },
    {
      id: "status",
      header: "Status",
      value: (m) => m.status,
      cell: (m) => <StatusPill label={m.status} tone={STATUS_TONE[m.status]} />,
    },
    { id: "lastActive", header: "Last Active", value: (m) => m.lastActive, className: "text-base-content/60" },
    {
      id: "actions",
      header: "Actions",
      cell: (m) => (
        <div className="flex gap-1">
          <button type="button" className="btn btn-outline btn-xs" aria-label={`Edit ${m.name}`}>
            Edit
          </button>
          <button type="button" className="btn btn-outline btn-error btn-xs" aria-label={`Revoke ${m.name}`}>
            Revoke
          </button>
        </div>
      ),
    },
  ];

  return (
    <section className="flex flex-col gap-3">
      <SectionLabel>Team Members Registry</SectionLabel>
      <div className="flex flex-wrap items-center gap-2">
        <SearchInput placeholder="Search team..." label="Search team" />
        <select className="select select-bordered select-sm w-auto" defaultValue="" aria-label="Filter by role">
          <option value="">All Roles</option>
          {roles.map((role) => (
            <option key={role.id} value={role.id}>
              {role.name}
            </option>
          ))}
        </select>
        <Button variant="primary" outline size="sm" icon={<Plus />} label="Invite User" />
      </div>
      <DataTable data={members} columns={columns} rowId={(m) => m.id} label="Team members" />
    </section>
  );
}
