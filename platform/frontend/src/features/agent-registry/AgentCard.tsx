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

import type { ComponentProps } from "react";
import { ArrowUp } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { StatusPill } from "@/components/ui/StatusPill";
import type { Agent, AgentStatus } from "./store/agents";
import { AGENT_ICONS } from "./agentIcons";
import { formatLatency, formatRunTime, formatUptime, formatVersion } from "./format";

const STATUS_PILL: Record<AgentStatus, ComponentProps<typeof StatusPill>> = {
  healthy: { label: "ONLINE", tone: "success" },
  offline: { label: "OFFLINE", tone: "neutral" },
  degraded: { label: "DEGRADED", tone: "warning" },
  escalating: { label: "ESCALATING", tone: "error" },
};

/**
 * One agent of the registry grid: icon, status, name, description, version,
 * average run time, uptime and latency. Props only, and not clickable;
 * Direct Invoke has no handler yet.
 */
export function AgentCard({ agent }: { agent: Agent }) {
  const Icon = AGENT_ICONS[agent.icon];
  return (
    <article className="card h-full border border-base-300 bg-base-200">
      <div className="card-body gap-3 p-4">
        <div className="flex items-center justify-between gap-2">
          <span className="rounded-md border border-base-300 bg-base-300/40 p-2 text-primary">
            <Icon size={18} aria-hidden="true" />
          </span>
          <StatusPill {...STATUS_PILL[agent.status]} />
        </div>
        <div className="min-w-0">
          <h3 className="m-0 truncate font-semibold text-base-content" title={agent.name}>
            {agent.name}
          </h3>
          <p className="m-0 mt-1 min-h-[2lh] line-clamp-2 text-sm text-base-content/60">{agent.description}</p>
        </div>
        <div className="divider my-0" />
        <div className="flex items-center justify-between gap-2">
          <span className="font-mono text-xs text-base-content/50">{formatVersion(agent.version)}</span>
          <span className="text-xs text-primary">AVG: {formatRunTime(agent.avgRunSeconds)}</span>
        </div>
        <div className="flex items-center justify-between rounded bg-base-300/50 px-3 py-1.5 text-xs">
          <span className="flex items-center gap-1 text-success">
            <ArrowUp size={12} aria-hidden="true" />
            {formatUptime(agent.uptimePercent)}
          </span>
          <span className="text-base-content/60">{formatLatency(agent.latencyMs)}</span>
        </div>
        <Button variant="primary" soft wide size="sm" label="Direct Invoke" />
      </div>
    </article>
  );
}
