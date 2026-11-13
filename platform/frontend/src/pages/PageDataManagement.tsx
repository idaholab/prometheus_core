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

import { ARTIFACT_FILTER, toggleSource, useDataManagement } from "@/features/data-management";
import { usePageHeader } from "@/features/shell";
import { DataManagement } from "@/features/data-management";
import { useListFilter } from "@/lib/listFilter";

/**
 * Data Management section page: owns the page's data, header and artifact filter
 * state. Layout lives in DataManagement. Route params will land here with the router.
 */
export function PageDataManagement() {
  usePageHeader({ title: "Data Sources & Artifact Persistence" });
  const { status, sources, storage, artifacts } = useDataManagement();

  const { facet, setFacet, visible, noMatches } = useListFilter(artifacts, ARTIFACT_FILTER);

  return (
    <DataManagement
      status={status}
      sources={sources}
      storage={storage}
      artifacts={visible}
      artifactType={facet}
      onArtifactTypeChange={setFacet}
      noMatchingArtifacts={noMatches}
      onToggleSource={toggleSource}
    />
  );
}
