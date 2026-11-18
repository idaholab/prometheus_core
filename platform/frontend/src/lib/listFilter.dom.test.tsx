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

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import { FilterChips } from "@/components/ui/FilterChips";
import { SearchInput } from "@/components/ui/SearchInput";
import { ALL, type ListFilterConfig, useListFilter } from "./listFilter.ts";

type Item = { name: string; kind: string };

const ITEMS: readonly Item[] = [
  { name: "Fuel Analyzer", kind: "analysis" },
  { name: "Fuel Reporter", kind: "reporting" },
  { name: "Core Monitor", kind: "analysis" },
];

const NO_ITEMS: readonly Item[] = [];

/** A module constant, as at a real call site: the hook memoizes visible on config. */
const CONFIG: ListFilterConfig<Item> = {
  searchFields: [(item) => item.name],
  facetOf: (item) => item.kind,
};

const CHIPS = [
  { id: ALL, label: "All" },
  { id: "analysis", label: "Analysis" },
  { id: "reporting", label: "Reporting" },
];

const NO_MATCH_TEXT = "No items match the filters";

/** The hook wired to the real SearchInput and FilterChips, as a page would wire them. */
function Harness({ items }: { items: readonly Item[] }) {
  const filter = useListFilter(items, CONFIG);
  return (
    <>
      <SearchInput placeholder="Search" label="Search items" value={filter.query} onChange={filter.setQuery} />
      <FilterChips chips={CHIPS} selected={filter.facet} label="Kind" onSelect={filter.setFacet} />
      <ul aria-label="Items">
        {filter.visible.map((item) => (
          <li key={item.name}>{item.name}</li>
        ))}
      </ul>
      {filter.noMatches && <p role="status">{NO_MATCH_TEXT}</p>}
    </>
  );
}

function visibleNames(): string[] {
  return screen.queryAllByRole("listitem").map((item) => item.textContent ?? "");
}

test("list filter: typing narrows the list, a chip narrows it further, a nonsense query shows no-match", async () => {
  const user = userEvent.setup();
  render(<Harness items={ITEMS} />);

  expect(visibleNames()).toEqual(["Fuel Analyzer", "Fuel Reporter", "Core Monitor"]);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();

  const search = screen.getByRole("searchbox", { name: "Search items" });
  await user.type(search, "fuel");
  expect(visibleNames()).toEqual(["Fuel Analyzer", "Fuel Reporter"]);

  await user.click(screen.getByRole("button", { name: "Reporting" }));
  expect(screen.getByRole("button", { name: "Reporting" })).toHaveAttribute("aria-pressed", "true");
  expect(visibleNames()).toEqual(["Fuel Reporter"]);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();

  await user.clear(search);
  await user.type(search, "zzqx");
  expect(visibleNames()).toEqual([]);
  expect(screen.getByRole("status")).toHaveTextContent(NO_MATCH_TEXT);
});

test("list filter: an empty list shows no no-match text, even with a query", async () => {
  const user = userEvent.setup();
  render(<Harness items={NO_ITEMS} />);

  expect(visibleNames()).toEqual([]);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();

  await user.type(screen.getByRole("searchbox", { name: "Search items" }), "zzqx");
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});
