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
import type { ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { FilterChips } from "./FilterChips.tsx";

type Element = ReactElement<Record<string, unknown>>;
const CHIPS = [
  { id: "all", label: "All" },
  { id: "csv", label: "CSV" },
  { id: "pdf", label: "PDF" },
];
/** The classes that mark the selected chip; an idle chip carries none of them. */
const SELECTED_CLASSES = ["border-primary", "bg-primary/20", "font-bold"];

/** The chip <button> elements that FilterChips returns inside its group. */
const buttonsOf = (group: Element) => group.props.children as Element[];

test("FilterChips renders one button per chip in a wrapping group, and selected decides the active chip", () => {
  const html = renderToStaticMarkup(FilterChips({ chips: CHIPS, selected: "csv", label: "File type" }));

  assert.match(html, /^<div role="group" aria-label="File type" class="[^"]*\bflex-wrap\b/);
  const buttons = [...html.matchAll(/<button[^>]*>([^<]*)<\/button>/g)];
  assert.deepEqual(
    buttons.map((m) => m[1]),
    ["All", "CSV", "PDF"],
  );
  const active = buttons.filter((m) => m[0].includes('aria-pressed="true"')).map((m) => m[1]);
  assert.deepEqual(active, ["CSV"]);
  for (const [tag, text] of buttons) {
    const classes = (tag.match(/class="([^"]*)"/)?.[1] ?? "").split(" ");
    for (const mark of SELECTED_CLASSES) {
      assert.equal(classes.includes(mark), text === "CSV", `${mark} on chip ${text}`);
    }
  }

  const moved = renderToStaticMarkup(FilterChips({ chips: CHIPS, selected: "pdf", label: "File type" }));
  const [, onlyActive] = moved.match(/<button[^>]*aria-pressed="true"[^>]*class="([^"]*)">PDF</) ?? [];
  assert.ok(onlyActive, "PDF is the pressed chip");
  for (const mark of SELECTED_CLASSES) {
    assert.ok(onlyActive.split(" ").includes(mark), `${mark} moved to PDF`);
    assert.equal(moved.split(mark).length - 1, 1, `${mark} on one chip only`);
  }
});

test("FilterChips reports the clicked chip's id through onSelect, and wires no click without onSelect", () => {
  const seen: string[] = [];
  const group = FilterChips({ chips: CHIPS, selected: "all", label: "l", onSelect: (id) => seen.push(id) });

  for (const button of buttonsOf(group)) (button.props.onClick as () => void)();
  assert.deepEqual(seen, ["all", "csv", "pdf"]);

  const bare = FilterChips({ chips: CHIPS, selected: "all", label: "l" });
  assert.deepEqual(
    buttonsOf(bare).map((button) => button.props.onClick),
    [undefined, undefined, undefined],
  );
});
