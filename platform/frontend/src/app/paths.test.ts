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

import { expect, test } from "vitest";
import { loginPathFor, NAV_PATHS, navIdForPath, PATHS, safeNextPath } from "./paths.ts";

test("every nav destination has a distinct URL", () => {
  const paths = Object.values(NAV_PATHS);
  expect(new Set(paths).size).toBe(paths.length);
});

test("navIdForPath maps a URL to its section, nested URLs included", () => {
  expect(navIdForPath("/")).toBe("home");
  expect(navIdForPath("/workflows")).toBe("workflows");
  expect(navIdForPath("/workflows/builder")).toBe("workflows");
  expect(navIdForPath("/admin")).toBe("admin");
  expect(navIdForPath("/workflowsx")).toBeNull();
  expect(navIdForPath("/nope")).toBeNull();
});

test("safeNextPath keeps in-app paths and drops everything else", () => {
  expect(safeNextPath("/workflows?tab=1#top")).toBe("/workflows?tab=1#top");
  for (const bad of [null, undefined, "", "https://evil.example", "//evil.example", "/\\evil.example", "workflows"]) {
    expect(safeNextPath(bad)).toBe(PATHS.home);
  }
  expect(safeNextPath("/login?next=/x")).toBe(PATHS.home);
  expect(safeNextPath("/setup")).toBe(PATHS.home);
});

test("loginPathFor carries the page to return to, and none for Home", () => {
  expect(loginPathFor("/admin?x=1")).toBe("/login?next=%2Fadmin%3Fx%3D1");
  expect(loginPathFor("/")).toBe("/login");
  expect(loginPathFor("//evil.example")).toBe("/login");
});
