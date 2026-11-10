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

import { FilterChips } from "@/components/ui/FilterChips";
import { SearchInput } from "@/components/ui/SearchInput";

// The C.1 domain chips; visual only until AR-4 adds filtering.
const DOMAIN_CHIPS = [
  { id: "all", label: "All" },
  { id: "plant-systems", label: "Plant & Systems" },
  { id: "core-fuel", label: "Core & Fuel" },
  { id: "structural-seismic", label: "Structural & Seismic" },
  { id: "licensing-regulatory", label: "Licensing & Regulatory" },
  { id: "data-knowledge", label: "Data & Knowledge" },
];

/** Search bar and domain chips of the Agent Registry. Props only, no state. */
export function RegistryToolbar({ selected }: { selected: string }) {
  return (
    <div className="flex flex-col gap-4 lg:flex-row lg:items-center">
      <div className="w-full md:w-96">
        <SearchInput placeholder="Search agents..." label="Search agents" />
      </div>
      <FilterChips chips={DOMAIN_CHIPS} selected={selected} label="Agent domains" />
    </div>
  );
}
