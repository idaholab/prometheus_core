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
import { ALL } from "@/lib/listFilter";
import { AGENT_DOMAINS } from "./store/agents";

// The C.1 domain chips; each id is the domain it filters on.
const DOMAIN_CHIPS = [{ id: ALL, label: "All" }, ...AGENT_DOMAINS.map((d) => ({ id: d, label: d }))];

type Props = {
  query: string;
  onQueryChange: (query: string) => void;
  selected: string;
  onSelect: (id: string) => void;
};

/** Search bar and domain chips of the Agent Registry. Props only, no state. */
export function RegistryToolbar({ query, onQueryChange, selected, onSelect }: Props) {
  return (
    <div className="flex flex-col gap-4 lg:flex-row lg:items-center">
      <div className="w-full md:w-96">
        <SearchInput placeholder="Search agents..." label="Search agents" value={query} onChange={onQueryChange} />
      </div>
      <FilterChips chips={DOMAIN_CHIPS} selected={selected} label="Agent domains" onSelect={onSelect} />
    </div>
  );
}
