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

/* `api.listWorkflows()` and `api.getWorkflow(id)` MUST GET `/api/workflows` and
 * `/api/workflows/{id}` with the session cookie and MUST throw `ApiError` with the
 * status and the backend `detail` on a non-2xx answer. */
import { afterEach, describe, expect, test, vi } from "vitest";
import { api, ApiError } from "./client.ts";
import type { WorkflowListResponse } from "./types.ts";

const LIST: WorkflowListResponse = {
  available: true,
  workflows: [
    {
      workflow_id: "comprehensive_material_analysis",
      name: "Comprehensive Material Analysis",
      summary: "Full multi-domain assessment with data retrieval and specialist analysis.",
      category: "Safety",
      version: "1.0.0",
      source: "local",
      owner: "materials-team",
      complexity: null,
      estimated_runtime_seconds: 270,
      speedup: null,
      requires_approval: true,
      agent_count: 5,
      checkpoint_count: 0,
    },
  ],
};

/** Stub `fetch` with a call that answers `body` as JSON with `status`. */
function stubFetch(body: unknown, status = 200) {
  const fetchMock = vi.fn<typeof fetch>(() =>
    Promise.resolve(
      new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
    ),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("workflows client", () => {
  test("listWorkflows GETs /api/workflows with the session cookie and returns the response unchanged", async () => {
    const fetchMock = stubFetch(LIST);

    const response = await api.listWorkflows();

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/workflows");
    expect(init?.credentials).toBe("include");
    expect(init?.method ?? "GET").toBe("GET");
    expect(response).toEqual(LIST);
  });

  test("listWorkflows returns an unavailable library as is, without throwing", async () => {
    stubFetch({ available: false, workflows: [] });

    const response = await api.listWorkflows();

    expect(response).toEqual({ available: false, workflows: [] });
  });

  test("getWorkflow GETs the URL-encoded /api/workflows/{id} with the session cookie", async () => {
    const fetchMock = stubFetch({ ...LIST.workflows[0], workflow_id: "a b/c" });

    await api.getWorkflow("a b/c");

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/workflows/a%20b%2Fc");
    expect(init?.credentials).toBe("include");
    expect(init?.method ?? "GET").toBe("GET");
  });

  test("getWorkflow rejects a 404 with an ApiError carrying the status and the backend detail", async () => {
    stubFetch({ detail: "Workflow not found" }, 404);

    const error = await api.getWorkflow("missing").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(404);
    expect((error as ApiError).message).toBe("Workflow not found");
  });

  test("getWorkflow rejects a 503 with an ApiError carrying the status and the backend detail", async () => {
    stubFetch({ detail: "Workflow library is unavailable" }, 503);

    const error = await api.getWorkflow("comprehensive_material_analysis").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(503);
    expect((error as ApiError).message).toBe("Workflow library is unavailable");
  });

  test("listWorkflows rejects a 500 with an ApiError carrying the status and the backend detail", async () => {
    stubFetch({ detail: "Database unavailable" }, 500);

    const error = await api.listWorkflows().catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(500);
    expect((error as ApiError).message).toBe("Database unavailable");
  });
});
