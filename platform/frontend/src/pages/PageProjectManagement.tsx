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

import { usePageHeader } from "@/features/shell";
import { useProjectManagement } from "@/features/project-management";
import { ProjectManagement } from "@/features/project-management";

/**
 * Project Management section page: owns the page's data and header. Layout lives
 * in ProjectManagement. Route params and filters will land here with the router.
 */
export function PageProjectManagement() {
  usePageHeader({ title: "Access Control & Team Hub" });
  const { status, members, roles } = useProjectManagement();

  return <ProjectManagement status={status} members={members} roles={roles} />;
}
