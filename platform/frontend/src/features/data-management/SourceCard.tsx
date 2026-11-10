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

import { StatusPill, type StatusPillTone } from "@/components/ui/StatusPill";
import { Tag } from "@/components/ui/Tag";

interface Props {
  /** Confluence connector_class, shown as the type tag. */
  connectorClass: string;
  name: string;
  statusTone: StatusPillTone;
  statusLabel: string;
  enabled: boolean;
  lastSync: string;
  volume: string;
}

/**
 * One connected data source: the type tag, the name, the status pill and a
 * read-only enable toggle, then the last sync and the volume. Same DaisyUI
 * card shape as SuggestionCard; the toggle does nothing yet (DM-4).
 */
export function SourceCard({ connectorClass, name, statusTone, statusLabel, enabled, lastSync, volume }: Props) {
  return (
    <div className="card w-full min-w-0 bg-base-200 border border-base-300">
      <div className="card-body gap-2.5 p-4">
        <div className="flex min-w-0 flex-wrap items-center gap-2.5">
          <Tag mono label={connectorClass} />
          <span className="min-w-0 flex-1 basis-40 break-words font-semibold text-base-content">{name}</span>
          <div className="flex shrink-0 items-center gap-2.5">
            <StatusPill tone={statusTone} label={statusLabel} />
            <input
              type="checkbox"
              className="toggle toggle-primary"
              checked={enabled}
              readOnly
              aria-label={`Enable ${name}`}
            />
          </div>
        </div>
        <div className="flex min-w-0 flex-wrap justify-between gap-x-6 gap-y-1 text-xs text-base-content/60">
          <span className="min-w-0">
            LAST SYNC: <span className="font-mono text-base-content">{lastSync}</span>
          </span>
          <span className="min-w-0">
            VOLUME: <span className="font-mono text-base-content">{volume}</span>
          </span>
        </div>
      </div>
    </div>
  );
}
