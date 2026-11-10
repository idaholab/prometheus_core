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

import { artifactFilePresentation } from "./artifactPresentation.ts";

test("uses an artifact description as the visible label without changing its filename", () => {
  assert.deepEqual(
    artifactFilePresentation({
      name: "5a7d23b5a19e4a86-equipment_0cea880e.e",
      props: { description: "Finite-element mesh of the butterfly valve" },
    }),
    {
      label: "Finite-element mesh of the butterfly valve",
      filename: "5a7d23b5a19e4a86-equipment_0cea880e.e",
    },
  );
});

test("uses the filename when the artifact has no description", () => {
  assert.deepEqual(
    artifactFilePresentation({ name: "valve.e" }),
    { label: "valve.e", filename: "valve.e" },
  );
});
