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

import { countMembersByRole, type ProjectManagementState } from "./store/projectManagementModel";
import { Users } from "lucide-react";
import { EmptyState } from "@/components/ui/EmptyState";
import { RbacSection } from "./RbacSection";
import { TeamMembersRegistry } from "./TeamMembersRegistry";

type ProjectManagementProps = ProjectManagementState;

/**
 * Project Management layout (Access Control & Team Hub): the team members
 * registry and the role-based access control schema. Display only;
 * PageProjectManagement supplies the data and the header title.
 */
export function ProjectManagement({ status, members, roles }: ProjectManagementProps) {
  return <div className="flex min-w-0 flex-1 flex-col overflow-y-auto">{renderBody(status, members, roles)}</div>;
}

function renderBody(
  status: ProjectManagementState["status"],
  members: ProjectManagementState["members"],
  roles: ProjectManagementState["roles"],
) {
  if (status === "loading") {
    return <p className="m-0 px-6 py-6 text-sm text-base-content/60">Loading team...</p>;
  }
  if (status === "error") {
    return (
      <div className="px-6 py-6">
        <div role="alert" className="alert alert-error">
          <span>The team could not be loaded.</span>
        </div>
      </div>
    );
  }
  if (status === "empty") {
    return <EmptyState icon={<Users size={24} />} title="No team members yet" hint="Invited users will display here" />;
  }
  return (
    <div className="flex flex-col gap-8 px-6 py-6">
      <TeamMembersRegistry members={members} roles={roles} />
      <RbacSection roles={roles} counts={countMembersByRole(members, roles)} />
    </div>
  );
}
