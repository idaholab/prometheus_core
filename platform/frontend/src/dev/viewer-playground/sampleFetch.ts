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

/** Backend URL path -> sample asset URL that answers it, as in `ViewerCase.files`. */
export type SampleRoutes = Record<string, string>;

/**
 * What the playground fetch does with one request:
 * - `sample`: the path is mapped; fetch `url`, the sample asset, instead.
 * - `missing`: an unmapped `/api/` path; answer 404 so the page never calls the backend.
 * - `passthrough`: any other URL (unpkg for web-ifc, Vite assets); fetch it unchanged.
 */
export type SampleResolution = { kind: "sample"; url: string } | { kind: "missing" } | { kind: "passthrough" };

function requestPath(input: RequestInfo | URL): string {
  const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  // Only the path is matched; the base resolves relative URLs such as "/api/...".
  return new URL(raw, "http://localhost").pathname;
}

/**
 * Decide how the playground answers a fetch of `input` (a string, a `URL` or a
 * `Request`). The match is on the URL path only; the origin and query are ignored.
 */
export function resolveSample(input: RequestInfo | URL, routes: SampleRoutes): SampleResolution {
  const path = requestPath(input);
  if (path in routes) return { kind: "sample", url: routes[path] };
  if (path.startsWith("/api/")) return { kind: "missing" };
  return { kind: "passthrough" };
}

/**
 * Replace `globalThis.fetch` with a wrapper that answers the viewers' backend
 * URLs from the sample files, as `resolveSample` decides. The wrapper calls the
 * fetch that was in place when this ran.
 */
export function installSampleFetch(routes: SampleRoutes): void {
  const original = globalThis.fetch;
  globalThis.fetch = (input, init) => {
    const resolution = resolveSample(input, routes);
    if (resolution.kind === "sample") return original(resolution.url, init);
    if (resolution.kind === "missing") return Promise.resolve(new Response(null, { status: 404 }));
    return original(input, init);
  };
}
