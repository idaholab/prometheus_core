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

/* The RTK Query base: where requests go, how errors reach screens, and that a
 * 401 hands off to the registered handler. Runs in jsdom because fetchBaseQuery
 * resolves the relative /api base against the page's location. */
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { baseApi, onUnauthorized } from "./baseApi.ts";
import { createAppStore } from "./store.ts";

const probe = baseApi.injectEndpoints({
  endpoints: (build) => ({
    probe: build.query<{ ok: boolean }, void>({ query: () => "/probe" }),
  }),
  overrideExisting: true,
});

const fetchMock = vi.fn<typeof fetch>();

function answer(status: number, body?: unknown) {
  fetchMock.mockResolvedValueOnce(
    new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
}

async function runProbe() {
  const store = createAppStore();
  return store.dispatch(probe.endpoints.probe.initiate());
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  onUnauthorized(null);
  vi.unstubAllGlobals();
});

describe("requests", () => {
  test("go to /api with the session cookie and return the body", async () => {
    answer(200, { ok: true });
    const result = await runProbe();

    expect(result.data).toEqual({ ok: true });
    const request = fetchMock.mock.calls[0][0] as Request;
    expect(new URL(request.url).pathname).toBe("/api/probe");
    expect(request.credentials).toBe("include");
  });
});

describe("errors", () => {
  test("carry the status and the backend's detail message", async () => {
    answer(409, { detail: "Username already exists" });
    const result = await runProbe();
    expect(result.error).toEqual({ status: 409, message: "Username already exists" });
  });

  test("fall back to a generic message when the body has no detail", async () => {
    answer(500, { something: "else" });
    const result = await runProbe();
    expect(result.error).toEqual({ status: 500, message: "Request failed (500)" });
  });

  test("a network failure reads as the server being unreachable", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const result = await runProbe();
    expect(result.error).toEqual({ status: "network", message: "The server is unreachable" });
  });
});

describe("a 401", () => {
  test("calls the registered handler and still returns the error", async () => {
    const handler = vi.fn();
    onUnauthorized(handler);
    answer(401, { detail: "Not authenticated" });

    const result = await runProbe();
    expect(handler).toHaveBeenCalledTimes(1);
    expect(result.error).toEqual({ status: 401, message: "Not authenticated" });
  });

  test("with no handler registered is just an error", async () => {
    answer(401, { detail: "Not authenticated" });
    const result = await runProbe();
    expect(result.error).toEqual({ status: 401, message: "Not authenticated" });
  });

  test("other errors don't call the handler", async () => {
    const handler = vi.fn();
    onUnauthorized(handler);
    answer(403, { detail: "Admin only" });

    await runProbe();
    expect(handler).not.toHaveBeenCalled();
  });
});
