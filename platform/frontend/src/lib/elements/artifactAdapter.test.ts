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

import { artifactToElement } from "./artifactAdapter.ts";
import type { ArtifactMeta } from "../api/types.ts";

// Minimal ArtifactMeta factory — only the fields the adapter reads.
function meta(overrides: Partial<ArtifactMeta>): ArtifactMeta {
  return {
    artifact_id: "uq-123",
    name: "rod_worth_uq.ipynb",
    mime_type: "application/x-ipynb+json",
    json_type: "prometheus.uq.result.v1",
    description: "",
    uri: null,
    tags: [],
    json_body: null,
    render_hint: "uq",
    citation: null,
    producer_agent_id: null,
    created_at: null,
    ...overrides,
  } as ArtifactMeta;
}

test("a uq render_hint maps to the UQDashboard custom element", () => {
  const el = artifactToElement(meta({}));
  assert.equal(el.type, "custom");
  assert.equal(el.name, "UQDashboard");
});

test("UQDashboard carries same-origin report/dashboard/download URLs (no host, no secret)", () => {
  const el = artifactToElement(meta({ artifact_id: "uq-abc" }));
  const props = el.props ?? {};

  const reportUrl = props.reportUrl as string;
  const dashboardUrl = props.dashboardUrl as string;
  const downloadUrl = props.downloadUrl as string;

  // Baked report is served by notebook-render at /notebook, not the content proxy.
  assert.equal(reportUrl, "/notebook/render/uq-abc");
  // the 3D UQ console is the static /uq-console/ page carrying this run's result URL.
  assert.equal(dashboardUrl, "/uq-console/index.html?result=/notebook/result/uq-abc");
  // Download is the artifact content proxy.
  assert.equal(downloadUrl, "/api/artifacts/uq-abc/content");

  // Same-origin invariant: every URL is a root-relative path, never absolute.
  for (const u of [reportUrl, dashboardUrl, downloadUrl]) {
    assert.ok(u.startsWith("/"), `${u} must be root-relative`);
    assert.ok(!u.includes("://"), `${u} must not be absolute`);
  }

  // No auth material leaks into props.
  const serialized = JSON.stringify(props).toLowerCase();
  for (const forbidden of ["bearer", "authorization", "secret", "agent_secret"]) {
    assert.ok(!serialized.includes(forbidden), `props must not contain ${forbidden}`);
  }
});

test("the artifact id is stamped into props for dedupe", () => {
  const el = artifactToElement(meta({ artifact_id: "uq-xyz" }));
  assert.equal((el.props ?? {}).artifact_id, "uq-xyz");
});

test("a no-dashboard tag drops the 3D UQ console link but keeps the report and download", () => {
  const props = artifactToElement(meta({ tags: ["no-dashboard"] })).props ?? {};
  assert.equal(props.dashboardUrl, "");
  assert.match(props.reportUrl as string, /^\/notebook\/render\//);
  assert.ok(props.downloadUrl);
});
