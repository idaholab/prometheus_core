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

import { useDataManagement } from "@/features/data-management/store/dataManagement";
import { usePageHeader } from "@/features/shell/store/pageHeader";
import { DataManagement } from "@/features/data-management/DataManagement";

/**
 * Data Management section page: owns the page's data and header. Layout lives in
 * DataManagement. Route params and filters will land here with the router.
 */
export function PageDataManagement() {
  usePageHeader({ title: "Data Sources & Artifact Persistence" });
  const { status, sources, storage, artifacts } = useDataManagement();

  return <DataManagement status={status} sources={sources} storage={storage} artifacts={artifacts} />;
}
