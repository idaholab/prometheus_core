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
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { DataTable } from "./DataTable.tsx";

type Person = { id: string; name: string; role: string; seen: string | null };
const PEOPLE: Person[] = [
  { id: "1", name: "Sarah Chen", role: "reviewer", seen: "2026-10-03" },
  { id: "2", name: "Aris Thorne", role: "analyst", seen: null },
  { id: "3", name: "Elena Rostova", role: "reviewer", seen: "2026-10-05" },
];
const COLUMNS = [
  { id: "name", header: "Name", value: (p: Person) => p.name, sortable: true },
  { id: "role", header: "Role", value: (p: Person) => p.role, cell: (p: Person) => `<${p.role}>` },
  { id: "seen", header: "Seen", value: (p: Person) => p.seen, sortable: true },
  { id: "actions", align: "right" as const, cell: (p: Person) => `edit ${p.id}` },
];

type Props = Partial<Parameters<typeof DataTable<Person>>[0]>;
const render = (props: Props = {}) =>
  renderToStaticMarkup(createElement(DataTable<Person>, { data: PEOPLE, columns: COLUMNS, ...props }));

/** The first cell's text in each body row. */
const names = (html: string) =>
  [...html.split("<tbody>")[1].matchAll(/<tr[^>]*><td[^>]*>([^<]*)</g)].map((m) => m[1]);

test("DataTable draws a header per column and a row per item, in data order with no sort", () => {
  const html = render();
  assert.deepEqual(
    [...html.matchAll(/<th(?: [^>]*)?>(?:<button[^>]*>)?([^<]*)/g)].map((m) => m[1]),
    ["Name", "Role", "Seen", ""],
  );
  assert.deepEqual(names(html), ["Sarah Chen", "Aris Thorne", "Elena Rostova"]);
  assert.match(html, /&lt;reviewer&gt;/, "custom cell content is drawn");
  assert.match(html, /<td class="[^"]*\btext-right\b[^"]*">edit 2<\/td>/);
});

test("DataTable makes only sortable columns with a value into sort buttons, and applies defaultSort", () => {
  const html = render({ defaultSort: { id: "name" } });
  assert.equal(html.match(/<th[^>]*><button/g)?.length, 2, "Name and Seen sort; Role and actions don't");
  assert.match(html, /<th class="[^"]*" aria-sort="ascending"><button[^>]*>Name/);
  assert.deepEqual(names(html), ["Aris Thorne", "Elena Rostova", "Sarah Chen"]);

  assert.deepEqual(names(render({ defaultSort: { id: "name", desc: true } })), [
    "Sarah Chen",
    "Elena Rostova",
    "Aris Thorne",
  ]);
  // A null value sorts last in either direction.
  assert.deepEqual(names(render({ defaultSort: { id: "seen" } })), ["Sarah Chen", "Elena Rostova", "Aris Thorne"]);
  assert.deepEqual(names(render({ defaultSort: { id: "seen", desc: true } })), [
    "Elena Rostova",
    "Sarah Chen",
    "Aris Thorne",
  ]);
});

test("DataTable search matches any valued column case-insensitively, and columnFilters match exactly", () => {
  assert.deepEqual(names(render({ search: "  ROSTOVA " })), ["Elena Rostova"]);
  assert.deepEqual(names(render({ search: "analyst" })), ["Aris Thorne"], "searches non-text cells by value");
  assert.deepEqual(names(render({ search: "edit" })), [], "columns without a value aren't searched");

  assert.deepEqual(names(render({ columnFilters: { role: "reviewer" } })), ["Sarah Chen", "Elena Rostova"]);
  assert.deepEqual(names(render({ columnFilters: { role: "review" } })), [], "filters are exact, not substring");
  assert.equal(names(render({ columnFilters: { role: "" } })).length, 3, "an empty filter means All");
  assert.deepEqual(names(render({ search: "sarah", columnFilters: { role: "reviewer" } })), ["Sarah Chen"]);
});

test("DataTable tells an empty table apart from one whose rows are all filtered out", () => {
  assert.match(render({ data: [], empty: "No people yet." }), /<\/table><\/div><p [^>]*>No people yet\.<\/p><\/div>$/);
  assert.match(render({ search: "zzz", noMatches: "Nothing matches." }), /<\/table><\/div><p [^>]*>Nothing matches\.<\/p><\/div>$/);
  assert.doesNotMatch(render(), /<p /, "no message while rows show");
});

test("DataTable caps its height only when maxHeight is given", () => {
  assert.match(render({ maxHeight: "20rem" }), /^<div [^>]*><div class="overflow-auto" style="max-height:20rem">/);
  assert.match(render(), /^<div [^>]*><div class="overflow-auto">/);
});

test("DataTable's card can shrink inside a flex parent, so a wide table scrolls inside it, not the page", () => {
  const card = render().match(/^<div class="([^"]*)"/)?.[1].split(" ") ?? [];
  for (const cls of ["w-full", "min-w-0", "overflow-hidden"]) assert.ok(card.includes(cls), cls);
});
