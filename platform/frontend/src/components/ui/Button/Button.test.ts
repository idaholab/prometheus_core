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

/* Pins what Button renders for each prop it styles by, so a change to
 * buttonClassName shows up here as a deliberate test edit. */
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { test } from "vitest";
import { Button } from "./Button.tsx";

type Props = Parameters<typeof Button>[0];
const render = (props: Props) => renderToStaticMarkup(createElement(Button, props));
/** The <button> element's class attribute. */
const classOf = (props: Props) => render(props).match(/<button[^>]*class="([^"]*)"/)?.[1];

const ICON = createElement("svg", { "data-icon": "" });

test("Button's classes for each variant, size and style flag", () => {
  const cases: Array<[Props, string]> = [
    [{ label: "Go" }, "btn btn-md"],
    [{ label: "Go", variant: "primary", size: "sm" }, "btn btn-primary btn-sm"],
    [{ label: "Go", variant: "error", size: "xs", outline: true }, "btn btn-error btn-xs btn-outline"],
    // A neutral outline keeps its border on hover, with a faint tint
    [{ label: "Go", outline: true }, "btn btn-md btn-outline hover:border-base-content hover:bg-base-content/8"],
    [{ label: "Go", variant: "neutral", size: "lg", soft: true }, "btn btn-neutral btn-lg btn-soft"],
    [{ label: "Go", wide: true }, "btn btn-md btn-block"],
    [{ label: "Go", active: true }, "btn btn-md btn-active"],
    [
      { label: "Go", outline: true, subtle: true },
      "btn btn-md btn-outline border-base-content/15 text-base-content/70 hover:border-base-content/30 hover:bg-base-content/8 hover:text-base-content",
    ],
    // subtle only applies to an outline button with no variant
    [{ label: "Go", variant: "primary", outline: true, subtle: true }, "btn btn-primary btn-md btn-outline"],
    [{ label: "Go", subtle: true }, "btn btn-md"],
    [{ label: "Go", icon: ICON, size: "sm" }, "btn btn-sm ps-2.5"],
    [{ label: "Go", icon: ICON, iconPosition: "right", size: "lg" }, "btn btn-lg pe-4"],
    [{ label: "Go", className: "mt-2" }, "btn btn-md mt-2"],
  ];
  for (const [props, expected] of cases) assert.equal(classOf(props), expected, JSON.stringify(props));
});

test("Button's classes for icon-only buttons, including the ghost rail style", () => {
  const cases: Array<[Props, string]> = [
    [{ icon: ICON, ariaLabel: "Bell" }, "btn btn-md btn-square"],
    [{ icon: ICON, ariaLabel: "Bell", shape: "circle", size: "xs" }, "btn btn-xs btn-circle"],
    [{ icon: ICON, ariaLabel: "Bell", variant: "ghost" }, "btn btn-ghost btn-md btn-square text-base-content/60 hover:text-base-content"],
    [{ icon: ICON, ariaLabel: "Bell", variant: "ghost", muted: false }, "btn btn-ghost btn-md btn-square"],
    [{ icon: ICON, ariaLabel: "Bell", variant: "ghost", active: true }, "btn btn-ghost btn-md btn-square bg-primary/15 text-primary"],
    [{ icon: ICON, ariaLabel: "Bell", variant: "primary", active: true }, "btn btn-primary btn-md btn-square btn-active"],
  ];
  for (const [props, expected] of cases) assert.equal(classOf(props), expected, JSON.stringify(props));
});

test("Button's attributes, icon slot and tooltip wrapper", () => {
  assert.match(render({ label: "Go" }), /^<button type="button" class="btn btn-md">Go<\/button>$/);
  assert.match(render({ label: "Go", type: "submit", disabled: true }), /type="submit"[^>]*disabled=""/);
  assert.match(render({ label: "Go", loading: true }), /disabled="" aria-busy="true"><span class="loading loading-spinner size-5" aria-hidden="true"><\/span>Go/);
  assert.match(render({ label: "Go", active: true }), /aria-pressed="true"/);
  assert.match(render({ label: "Go", icon: ICON, size: "xs" }), /<span class="flex shrink-0 \[&amp;&gt;svg\]:size-full size-3" aria-hidden="true"><svg data-icon=""><\/svg><\/span>Go/);
  assert.match(render({ label: "Go", icon: ICON, iconPosition: "right" }), />Go<span class="flex shrink-0/);

  // Icon-only: the name goes on aria-label, and the tooltip wrapper repeats it
  assert.equal(
    render({ icon: ICON, ariaLabel: "Bell", tooltipPlacement: "bottom", wide: true }),
    '<span class="tooltip tooltip-bottom w-full" data-tip="Bell"><button type="button" class="btn btn-md btn-square btn-block" aria-label="Bell"><span class="flex shrink-0 [&amp;&gt;svg]:size-full size-5" aria-hidden="true"><svg data-icon=""></svg></span></button></span>',
  );
  assert.doesNotMatch(render({ label: "Go" }), /aria-label/);
});
