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

import { useAgents } from "@/features/agent-registry";
import { usePageHeader } from "@/features/shell";
import { AgentRegistry } from "@/features/agent-registry";

/**
 * Agent Registry section page: owns the page's data and header. Layout lives in
 * AgentRegistry. Route params and filters will land here with the router.
 */
export function PageAgentRegistry() {
  usePageHeader({ title: "Agent Registry" });
  const { agents, status } = useAgents();

  return <AgentRegistry agents={agents} status={status} />;
}
