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

import { useMemo, useState } from "react";

/** The facet value that means "no facet filter" (the "All" chip or option). */
export const ALL = "all";

export interface ListFilterConfig<T> {
  /** Text fields that the search reads. Omit for a list with no search box. */
  searchFields?: readonly ((item: T) => string)[];
  /** The one facet value of an item. Omit for a list with no facet control. */
  facetOf?: (item: T) => string;
}

export interface ListFilterState {
  query: string;
  facet: string;
}

/** Items whose facet matches and whose search fields contain the trimmed query, ignoring case. */
export function filterList<T>(
  items: readonly T[],
  config: ListFilterConfig<T>,
  state: ListFilterState,
): readonly T[] {
  const { searchFields, facetOf } = config;
  const needle = state.query.trim().toLowerCase();
  const search = searchFields && needle !== "" ? searchFields : undefined;
  const facet = facetOf && state.facet !== ALL ? facetOf : undefined;
  if (!search && !facet) return items;
  return items.filter(
    (item) =>
      (!facet || facet(item) === state.facet) &&
      (!search || search.some((field) => field(item).toLowerCase().includes(needle))),
  );
}

export interface ListFilter<T> extends ListFilterState {
  setQuery: (query: string) => void;
  setFacet: (facet: string) => void;
  /** The filtered items, in input order. */
  visible: readonly T[];
  /** True when items exist but none is visible: show the SH-1 empty state. */
  noMatches: boolean;
}

export function useListFilter<T>(items: readonly T[], config: ListFilterConfig<T>): ListFilter<T> {
  const [query, setQuery] = useState("");
  const [facet, setFacet] = useState<string>(ALL);

  const visible = useMemo(() => filterList(items, config, { query, facet }), [items, config, query, facet]);

  return {
    query,
    setQuery,
    facet,
    setFacet,
    visible,
    noMatches: items.length > 0 && visible.length === 0,
  };
}
