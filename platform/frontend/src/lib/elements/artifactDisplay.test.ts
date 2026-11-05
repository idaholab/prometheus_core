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

import type { ArtifactMeta } from "../api/types.ts";
import { inlineArtifacts, isPanelOnly } from "./artifactAdapter.ts";

function artifact(id: string, display?: ArtifactMeta["display"]): ArtifactMeta {
  return {
    artifact_id: id,
    name: `${id}.i`,
    description: "",
    tags: [],
    render_hint: "code",
    ...(display ? { display } : {}),
  };
}

test("panel-only artifacts are left out of the message body", () => {
  const all = [artifact("plan"), artifact("current", "panel"), artifact("log", "inline")];
  assert.deepEqual(
    inlineArtifacts(all).map((a) => a.artifact_id),
    ["plan", "log"],
  );
});

test("an artifact without a display hint stays inline", () => {
  assert.equal(isPanelOnly(artifact("old")), false);
  assert.equal(isPanelOnly(artifact("new", "panel")), true);
});
