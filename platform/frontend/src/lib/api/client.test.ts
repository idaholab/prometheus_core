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
import { test, vi } from "vitest";

import { api, ApiError } from "./client.ts";

test("artifactContentUrl uses the backend's conversation content_url as given", () => {
  const content_url = "/api/conversations/c1/artifacts/a1/content";

  assert.equal(api.artifactContentUrl({ artifact_id: "a1", content_url }), content_url);
});

test("artifactContentUrl falls back to the session route when content_url is empty or absent", () => {
  // The backend sends "" when it knows no conversation; fixtures and samples omit it.
  for (const artifact of [{ artifact_id: "a1", content_url: "" }, { artifact_id: "a1" }]) {
    assert.equal(api.artifactContentUrl(artifact), "/api/artifacts/a1/content");
  }
});

test("artifactContentUrl quotes the artifact id in the fallback", () => {
  assert.equal(api.artifactContentUrl({ artifact_id: "a b/c?d" }), "/api/artifacts/a%20b%2Fc%3Fd/content");
});

test("meshProps fetches mesh_url as given and maps an error's detail", async () => {
  const fetchMock = vi.fn<typeof fetch>();
  vi.stubGlobal("fetch", fetchMock);
  try {
    const url = "/api/conversations/c1/artifacts/m1/mesh";
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ baseUrl: "/b" }), { status: 200 }));
    assert.deepEqual(await api.meshProps(url), { baseUrl: "/b" });
    assert.equal(fetchMock.mock.calls[0][0], url);
    assert.equal(fetchMock.mock.calls[0][1]?.credentials, "include");

    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Could not convert out.e for viewing." }), { status: 422 }),
    );
    await assert.rejects(api.meshProps(url), (err: unknown) => {
      assert.ok(err instanceof ApiError);
      assert.equal(err.status, 422);
      assert.equal(err.message, "Could not convert out.e for viewing.");
      return true;
    });
  } finally {
    vi.unstubAllGlobals();
  }
});
