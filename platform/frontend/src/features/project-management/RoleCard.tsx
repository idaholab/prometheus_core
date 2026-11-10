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

import { Count } from "@/components/ui/Count";

interface Props {
  name: string;
  memberCount: number;
  permissions: string[];
}

/**
 * One role of the RBAC schema: the role name, its member count and its
 * permission summary. Styled as SuggestionCard; grows with its content.
 */
export function RoleCard({ name, memberCount, permissions }: Props) {
  return (
    <div className="card w-full bg-base-200 border border-base-300">
      <div className="card-body gap-3 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="m-0 font-semibold text-base-content">{name}</h3>
          <Count count={memberCount} noun="member" />
        </div>
        <ul className="m-0 list-disc space-y-1 pl-5 text-xs leading-snug text-base-content/70 marker:text-primary">
          {permissions.map((permission) => (
            <li key={permission}>{permission}</li>
          ))}
        </ul>
        <div className="card-actions mt-auto">
          <button
            type="button"
            className="btn btn-link btn-xs px-0 uppercase text-primary no-underline"
            aria-label={`Edit ${name} permissions`}
          >
            Edit permissions <span aria-hidden="true">→</span>
          </button>
        </div>
      </div>
    </div>
  );
}
