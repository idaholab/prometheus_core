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

import { Cpu } from "lucide-react";
import { EmptyState } from "@/components/ui/EmptyState";
import type { AgentsState } from "./store/agents";
import { AgentCard } from "./AgentCard";
import { RegistryToolbar } from "./RegistryToolbar";

/**
 * Agent Registry layout (Figma C.1): the toolbar, then the agent grid or the
 * load state. Display only; PageAgentRegistry supplies the data.
 */
export function AgentRegistry({ agents, status }: AgentsState) {
  return (
    <div className="flex flex-1 flex-col gap-6 overflow-y-auto p-6">
      {status === "loading" && <p className="m-0 text-sm text-base-content/60">Loading agents...</p>}
      {status === "error" && (
        <div role="alert" className="alert alert-error">
          The agent registry is unavailable.
        </div>
      )}
      {(status === "ready" || status === "empty") && <RegistryToolbar selected="all" />}
      {status === "empty" && (
        <EmptyState icon={<Cpu size={24} />} title="No agents are registered" hint="Registered agents will display here" />
      )}
      {status === "ready" && (
        <section aria-labelledby="agent-registry-agents">
          {/* The header holds the page h1; this h2 keeps the card h3 in order. */}
          <h2 id="agent-registry-agents" className="sr-only">
            Agents
          </h2>
          <div className="grid gap-6 grid-cols-[repeat(auto-fill,minmax(min(16rem,100%),1fr))]">
            {agents.map((agent) => (
              <AgentCard key={agent.id} agent={agent} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
