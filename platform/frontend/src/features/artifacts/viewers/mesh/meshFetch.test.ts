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

import { ApiError } from "@/lib/api/client";
import { meshFailureMessage } from "./meshFetch.ts";

const GENERIC = "The mesh couldn't be prepared. Try again, or download the file.";

test("a conversion failure shows the backend's reason", () => {
  assert.equal(
    meshFailureMessage(new ApiError(422, "Could not convert out.e for viewing."), false),
    "Could not convert out.e for viewing.",
  );
});

test("an ended session asks the user to sign in again", () => {
  assert.equal(
    meshFailureMessage(new ApiError(401, "Unauthorized"), false),
    "Your session has ended. Sign in again to view this mesh.",
  );
});

test("status texts and browser errors become plain words", () => {
  for (const err of [
    new ApiError(500, "Internal Server Error"),
    new ApiError(502, ""),
    new ApiError(422, ""),
    new TypeError("Failed to fetch"),
    "boom",
  ]) {
    assert.equal(meshFailureMessage(err, false), GENERIC, String(err));
  }
});

test("a timeout says so", () => {
  assert.equal(
    meshFailureMessage(new DOMException("aborted", "AbortError"), true),
    "Preparing the mesh took too long. Try again, or download the file.",
  );
});
