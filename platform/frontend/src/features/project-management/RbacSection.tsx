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

import type { Role, RoleId } from "./store/projectManagementModel";
import { SectionLabel } from "@/components/ui/SectionLabel";
import { RoleCard } from "./RoleCard";

interface Props {
  roles: Role[];
  counts: Record<RoleId, number>;
}

/** Role-based access control schema: one card per role. */
export function RbacSection({ roles, counts }: Props) {
  return (
    <section className="flex flex-col gap-3">
      <SectionLabel>Role-Based Access Control (RBAC) Schema</SectionLabel>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {roles.map((role) => (
          <RoleCard
            key={role.id}
            name={role.name}
            memberCount={counts[role.id] ?? 0}
            permissions={role.permissions}
          />
        ))}
      </div>
    </section>
  );
}
