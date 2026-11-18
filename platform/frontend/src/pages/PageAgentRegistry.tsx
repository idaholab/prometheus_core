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

import { AGENT_FILTER, useAgents } from "@/features/agent-registry";
import { usePageHeader } from "@/features/shell";
import { AgentRegistry } from "@/features/agent-registry";
import { useListFilter } from "@/lib/listFilter";

/**
 * Agent Registry section page: owns the page's data, header and filter state.
 * Layout lives in AgentRegistry. Route params will land here with the router.
 */
export function PageAgentRegistry() {
  usePageHeader({ title: "Agent Registry" });
  const { agents, status } = useAgents();
  const { query, setQuery, facet, setFacet, visible, noMatches } = useListFilter(agents, AGENT_FILTER);

  return (
    <AgentRegistry
      agents={visible}
      status={status}
      query={query}
      onQueryChange={setQuery}
      domain={facet}
      onDomainChange={setFacet}
      noMatches={noMatches}
    />
  );
}
