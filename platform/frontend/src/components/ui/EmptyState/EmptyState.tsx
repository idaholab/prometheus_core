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

import type { ReactNode } from "react";

interface EmptyStateProps {
  icon: ReactNode;
  title: string;
  hint: string;
}

/** Centred placeholder for an empty list or panel: boxed icon, title, hint. */
export function EmptyState({ icon, title, hint }: EmptyStateProps) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 text-center">
      <div className="flex items-center justify-center rounded-2xl border border-base-300 bg-base-200 p-4 text-base-content/40">
        {icon}
      </div>
      <div className="space-y-1.5">
        <p className="m-0 font-semibold text-base-content">{title}</p>
        <p className="m-0 text-xs text-base-content/60">{hint}</p>
      </div>
    </div>
  );
}
