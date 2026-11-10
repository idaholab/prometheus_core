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

import { formatBytes, storagePercent, type DataManagementState, type SourceStatus } from "@/lib/store/dataManagement";
import { Database } from "lucide-react";
import { EmptyState } from "@/components/ui/EmptyState";
import { SectionLabel } from "@/components/ui/SectionLabel";
import { Button } from "@/components/ui/Button";
import type { StatusPillTone } from "@/components/ui/StatusPill";
import { SourceCard } from "./SourceCard";
import { StoragePanel } from "./StoragePanel";

const STATUS_TONE: Record<SourceStatus, StatusPillTone> = {
  connected: "success",
  syncing: "progress",
  disconnected: "error",
};

/**
 * Data Management = the connected data sources on the left and the artifact
 * storage panel on the right (Figma G.1), stacked below `lg:`. Display only;
 * PageDataManagement supplies the data. Passes display strings to the parts.
 */
export function DataManagement({ status, sources, storage, artifacts }: DataManagementState) {

  if (status === "loading") {
    return <div className="flex-1 min-w-0 p-4 text-sm text-base-content/50">Loading...</div>;
  }
  if (status === "error") {
    return (
      <div className="flex-1 min-w-0 p-4">
        <div role="alert" className="alert alert-error text-xs">
          Data could not be loaded.
        </div>
      </div>
    );
  }
  if (status === "empty") {
    return (
      <EmptyState
        icon={<Database size={24} />}
        title="No data sources are connected"
        hint="Connected sources and generated artifacts will display here"
      />
    );
  }

  return (
    <div className="flex-1 min-w-0 overflow-y-auto p-4">
      <div className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
        <section className="flex min-w-0 flex-col gap-3">
          <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
            <SectionLabel className="min-w-0">Connected Data Sources</SectionLabel>
            <Button variant="primary" size="sm" label="Add Source" />
          </div>
          {sources.map((source) => (
            <SourceCard
              key={source.id}
              connectorClass={source.connector_class}
              name={source.name}
              statusTone={STATUS_TONE[source.status]}
              statusLabel={source.status}
              enabled={source.enabled}
              lastSync={source.last_sync}
              volume={formatBytes(source.volume_bytes)}
            />
          ))}
        </section>
        <section className="min-w-0">
          <StoragePanel
            usedLabel={formatBytes(storage.used_bytes)}
            totalLabel={formatBytes(storage.total_bytes)}
            percent={storagePercent(storage)}
            artifacts={artifacts.map((artifact) => ({
              id: artifact.id,
              name: artifact.name,
              agent: artifact.agent,
              runId: artifact.run_id,
              size: formatBytes(artifact.size_bytes),
              created: artifact.created,
            }))}
          />
        </section>
      </div>
    </div>
  );
}
