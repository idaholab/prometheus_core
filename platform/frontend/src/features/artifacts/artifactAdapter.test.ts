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

import type { ArtifactMeta } from "@/lib/api/types";
import { artifactToElement } from "./artifactAdapter.ts";

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
    has_report: true,
    ...overrides,
  } as ArtifactMeta;
}

test("a uq render_hint maps to the UQDashboard custom element", () => {
  const el = artifactToElement(meta({}));
  assert.equal(el.type, "custom");
  assert.equal(el.name, "UQDashboard");
});

test("UQDashboard carries same-origin report/download URLs (no host, no secret)", () => {
  const el = artifactToElement(meta({ artifact_id: "uq-abc" }));
  const props = el.props ?? {};

  const reportUrl = props.reportUrl as string;
  const downloadUrl = props.downloadUrl as string;

  // Baked report comes from the backend's report route, not the content proxy.
  assert.equal(reportUrl, "/api/artifacts/uq-abc/report");
  // Download is the artifact content proxy.
  assert.equal(downloadUrl, "/api/artifacts/uq-abc/content");

  // Same-origin invariant: every URL is a root-relative path, never absolute.
  for (const u of [reportUrl, downloadUrl]) {
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

test("links the producing agent attached are passed to the viewer", () => {
  const links = [
    { label: "Pipeline", url: "https://gitlab.example/g/p/-/pipelines/42" },
    { label: "Open interactive dashboard", url: "/api/artifacts/uq-123/links/1" },
  ];
  assert.deepEqual(artifactToElement(meta({ links })).props?.links, links);
  assert.deepEqual(artifactToElement(meta({})).props?.links, []);
});

test("a UQ artifact without a report gets no report URL", () => {
  assert.equal(artifactToElement(meta({ has_report: false })).props?.reportUrl, "");
});

test("a UQ artifact with no name gets a default notebook filename", () => {
  assert.equal(artifactToElement(meta({ name: "" })).props?.filename, "uq_result.ipynb");
});

function jsonArtifact(overrides: Partial<ArtifactMeta>): ArtifactMeta {
  return {
    artifact_id: "art-1",
    name: "result.json",
    mime_type: "application/json",
    description: "",
    tags: [],
    json_body: null,
    render_hint: "json",
    ...overrides,
  };
}

test("json artifact without an inline body points CollapsibleJson at the content URL", () => {
  const element = artifactToElement(jsonArtifact({ artifact_id: "a b", json_body: null }));

  assert.equal(element.name, "CollapsibleJson");
  assert.equal(element.props?.url, "/api/artifacts/a%20b/content");
  assert.equal(element.props?.data, null);
});

test("json artifact with an inline body keeps it as CollapsibleJson data", () => {
  const body = { status: "ok", values: [1, 2, 3], nested: { flag: true } };
  const element = artifactToElement(jsonArtifact({ json_body: body }));

  assert.equal(element.name, "CollapsibleJson");
  assert.deepEqual(element.props?.data, { status: "ok", values: [1, 2, 3], nested: { flag: true } });
  assert.equal(element.props?.url, "/api/artifacts/art-1/content");
});
