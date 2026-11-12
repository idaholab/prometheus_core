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

import assert from "node:assert/strict";
import { test } from "vitest";

import { ALL, filterList, type ListFilterConfig } from "./listFilter.ts";

interface Item {
  name: string;
  description: string;
  kind: string;
}

const MESH: Item = { name: "Mesh Generator", description: "Builds grids for thermal models", kind: "a" };
const HEAT: Item = { name: "Heat Solver", description: "Runs transport", kind: "b" };
const REPORT: Item = { name: "Report Writer", description: "Summarises results", kind: "a" };
const FLUX: Item = { name: "Flux Plotter", description: "Plots thermal flux", kind: "b" };
const ITEMS: readonly Item[] = [MESH, HEAT, REPORT, FLUX];

const FULL: ListFilterConfig<Item> = {
  searchFields: [(item) => item.name, (item) => item.description],
  facetOf: (item) => item.kind,
};

const names = (items: readonly Item[]) => items.map((item) => item.name);

test("filterList query ignores case", () => {
  assert.deepEqual(names(filterList(ITEMS, FULL, { query: "MESH", facet: ALL })), ["Mesh Generator"]);
});

test("filterList query is trimmed", () => {
  assert.deepEqual(names(filterList(ITEMS, FULL, { query: "  mesh ", facet: ALL })), ["Mesh Generator"]);
});

test("filterList query matches any search field", () => {
  assert.deepEqual(names(filterList(ITEMS, FULL, { query: "transport", facet: ALL })), ["Heat Solver"]);
});

test("filterList facet keeps only items with that facet", () => {
  assert.deepEqual(names(filterList(ITEMS, FULL, { query: "", facet: "b" })), ["Heat Solver", "Flux Plotter"]);
});

test("filterList query and facet combine with AND", () => {
  assert.deepEqual(names(filterList(ITEMS, FULL, { query: "thermal", facet: "b" })), ["Flux Plotter"]);
});

test("filterList blank query and ALL keep every item in input order", () => {
  assert.deepEqual(filterList(ITEMS, FULL, { query: "", facet: ALL }), [MESH, HEAT, REPORT, FLUX]);
  assert.deepEqual(filterList(ITEMS, FULL, { query: "   ", facet: ALL }), [MESH, HEAT, REPORT, FLUX]);
});

test("filterList without facetOf ignores the facet", () => {
  const config: ListFilterConfig<Item> = { searchFields: FULL.searchFields };
  assert.deepEqual(filterList(ITEMS, config, { query: "", facet: "b" }), [MESH, HEAT, REPORT, FLUX]);
  assert.deepEqual(names(filterList(ITEMS, config, { query: "thermal", facet: "b" })), [
    "Mesh Generator",
    "Flux Plotter",
  ]);
});

test("filterList without searchFields ignores the query", () => {
  const config: ListFilterConfig<Item> = { facetOf: FULL.facetOf };
  assert.deepEqual(filterList(ITEMS, config, { query: "mesh", facet: ALL }), [MESH, HEAT, REPORT, FLUX]);
  assert.deepEqual(names(filterList(ITEMS, config, { query: "mesh", facet: "b" })), ["Heat Solver", "Flux Plotter"]);
});
