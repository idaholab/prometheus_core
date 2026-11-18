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

import { Plus, Search } from "lucide-react";
import { SectionLabel } from "@/components/ui/SectionLabel";
import type { MemberStatus, Role, TeamMember } from "./store/projectManagementModel";
import { DataTable, type DataTableColumn } from "@/components/ui/DataTable";
import { SearchInput } from "@/components/ui/SearchInput";
import { EmptyState } from "@/components/ui/EmptyState";
import { Button } from "@/components/ui/Button";
import { StatusPill, type StatusPillTone } from "@/components/ui/StatusPill";
import { Tag } from "@/components/ui/Tag";
import { ALL } from "@/lib/listFilter";

const STATUS_TONE: Record<MemberStatus, StatusPillTone> = {
  active: "success",
  invited: "info",
  suspended: "error",
};

interface Props {
  members: TeamMember[];
  roles: Role[];
  query: string;
  onQueryChange: (query: string) => void;
  role: string;
  onRoleChange: (role: string) => void;
  /** Members exist but none matches the search and role. */
  noMatches: boolean;
}

/**
 * Team members registry: search bar, role filter, invite button and the
 * member table. The row actions are not wired yet (PM-4).
 */
export function TeamMembersRegistry({ members, roles, query, onQueryChange, role, onRoleChange, noMatches }: Props) {
  const roleNames = new Map(roles.map((r) => [r.id, r.name]));

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
        <SearchInput placeholder="Search team..." label="Search team" value={query} onChange={onQueryChange} />
        <select
          className="select select-bordered select-sm w-auto"
          value={role}
          onChange={(e) => onRoleChange(e.target.value)}
          aria-label="Filter by role"
        >
          <option value={ALL}>All Roles</option>
          {roles.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name}
            </option>
          ))}
        </select>
        <Button variant="primary" outline size="sm" icon={<Plus />} label="Invite User" />
      </div>
      {noMatches ? (
        <EmptyState icon={<Search size={24} />} title="No matching team members" hint="Try another search or role" />
      ) : (
        <DataTable data={members} columns={columns} rowId={(m) => m.id} label="Team members" />
      )}
    </section>
  );
}
