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
import { SearchInput } from "./SearchInput.tsx";

type Element = ReactElement<Record<string, unknown>>;
/** The <input> element that SearchInput returns inside its <label>. */
const inputOf = (label: Element) => (label.props.children as Element[])[1];

test("SearchInput renders the icon, placeholder and aria-label, uncontrolled without value", () => {
  const html = renderToStaticMarkup(SearchInput({ placeholder: "Search files", label: "Search the files" }));

  // lucide-react names each icon in its class, so this doesn't break when an icon's paths are redrawn.
  // aria-hidden checks the icon is hidden from screen readers; lucide adds it to any unlabelled icon.
  assert.match(html, /<svg[^>]*class="(?:[^"]* )?lucide-search(?: [^"]*)?"[^>]*aria-hidden="true"/);
  assert.match(html, /placeholder="Search files"/);
  assert.match(html, /aria-label="Search the files"/);
  assert.doesNotMatch(html, /value=/);
});

test("SearchInput renders a given value and reports the new text through onChange", () => {
  const seen: string[] = [];
  const label = SearchInput({ placeholder: "p", label: "l", value: "rea", onChange: (v) => seen.push(v) });

  assert.match(renderToStaticMarkup(label), /value="rea"/);
  const onChange = inputOf(label).props.onChange as (event: unknown) => void;
  onChange({ target: { value: "reactor" } });
  assert.deepEqual(seen, ["reactor"]);
});

// Never called: tsc fails here if a controlled value stops requiring onChange.
void (() =>
  // @ts-expect-error value requires onChange
  SearchInput({ placeholder: "p", label: "l", value: "x" }));
