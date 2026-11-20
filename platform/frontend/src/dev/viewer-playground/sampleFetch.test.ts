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

/* The playground fetch answers each mapped artifact URL from its sample file,
 * answers any other `/api/` URL with 404, and passes every other URL through,
 * so the page never reaches the backend proxy. */
import { afterEach, describe, expect, test, vi } from "vitest";
import { installSampleFetch, resolveSample, type SampleRoutes } from "./sampleFetch.ts";

const IFC_PATH = "/api/artifacts/sample-ifc/content";
const IFC_ASSET = "/e2e/samples/model.ifc";
const WEB_IFC_WASM = "https://unpkg.com/web-ifc@0.0.77/web-ifc.wasm";
const routes: SampleRoutes = { [IFC_PATH]: IFC_ASSET };

/** Stub `fetch` with a call that answers 200, so the wrapper has an original to call. */
function stubFetch() {
  const fetchMock = vi.fn<typeof fetch>(() => Promise.resolve(new Response("sample", { status: 200 })));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("resolveSample", () => {
  test.each([
    ["a string", IFC_PATH],
    ["a URL", new URL(IFC_PATH, "http://localhost:5150")],
    ["a Request", new Request(new URL(IFC_PATH, "http://localhost:5150"))],
  ])("maps a mapped artifact path given as %s to its asset URL", (_form, input) => {
    expect(resolveSample(input, routes)).toEqual({ kind: "sample", url: IFC_ASSET });
  });

  test("answers an unmapped /api/ path with the 404 marker", () => {
    expect(resolveSample("/api/artifacts/other/content", routes)).toEqual({ kind: "missing" });
  });

  test("passes a URL outside /api/ through unchanged", () => {
    expect(resolveSample(WEB_IFC_WASM, routes)).toEqual({ kind: "passthrough" });
  });
});

describe("installSampleFetch", () => {
  test("fetches the asset URL for a mapped artifact path", async () => {
    const fetchMock = stubFetch();
    installSampleFetch(routes);
    const init: RequestInit = { credentials: "include" };

    const res = await fetch(IFC_PATH, init);

    expect(fetchMock).toHaveBeenCalledWith(IFC_ASSET, init);
    expect(await res.text()).toBe("sample");
  });

  test("answers an unmapped /api/ path with 404 and never calls the original fetch", async () => {
    const fetchMock = stubFetch();
    installSampleFetch(routes);

    const res = await fetch("/api/artifacts/other/content");

    expect(res.status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test("passes an unpkg URL to the original fetch unchanged", async () => {
    const fetchMock = stubFetch();
    installSampleFetch(routes);

    await fetch(WEB_IFC_WASM);

    expect(fetchMock).toHaveBeenCalledWith(WEB_IFC_WASM, undefined);
  });
});
