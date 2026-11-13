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

import { useMemo } from "react";
import { usePageHeader } from "@/features/shell";
import { TEAM_FILTER, useProjectManagement } from "@/features/project-management";
import { ProjectManagement } from "@/features/project-management";
import { useListFilter } from "@/lib/listFilter";

/**
 * Project Management section page: owns the page's data, header and filter state.
 * Layout lives in ProjectManagement. Route params will land here with the router.
 */
export function PageProjectManagement() {
  usePageHeader({ title: "Access Control & Team Hub" });
  const { status, members, roles } = useProjectManagement();
  const { query, setQuery, facet, setFacet, visible, noMatches } = useListFilter(members, TEAM_FILTER);
  // DataTable takes a mutable array; copy the readonly filter result once per change.
  const visibleMembers = useMemo(() => [...visible], [visible]);

  return (
    <ProjectManagement
      status={status}
      members={members}
      roles={roles}
      visibleMembers={visibleMembers}
      query={query}
      onQueryChange={setQuery}
      role={facet}
      onRoleChange={setFacet}
      noMatches={noMatches}
    />
  );
}
