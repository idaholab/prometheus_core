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

/**
 * Placeholder for sidebar destinations that exist in the nav but aren't
 * scoped/built yet (currently Jobs Console). Mirrors the old per-tab "coming soon" stubs.
 */
export function ComingSoon({ label }: { label: string }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center">
      <h2 className="m-0 text-lg font-semibold text-base-content">{label}</h2>
      <p className="m-0 text-sm text-base-content/50">Coming soon</p>
    </div>
  );
}
