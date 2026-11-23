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

/**
 * The one RTK Query API for server data. Each feature adds its own endpoints
 * with `baseApi.injectEndpoints` from its own folder (see `features/admin/adminApi.ts`),
 * so this file stays the same as features are added.
 *
 * Requests go to the same `/api` base with the same session cookie as
 * `client.ts`. A 401 from any query or mutation means the session is gone:
 * the handler registered with `onUnauthorized` (App sends the user to Login)
 * runs, the same place a lost session already ends up.
 */
import { createApi, fetchBaseQuery, type BaseQueryFn, type FetchArgs } from "@reduxjs/toolkit/query/react";

/** An API error as screens see it: the HTTP status (or "network") and the backend's message. */
export interface ApiQueryError {
  status: number | "network";
  message: string;
}

// The page's own origin, so requests go to the same /api as client.ts. Spelled
// out because fetchBaseQuery builds a Request, which needs an absolute URL
// outside a browser (tests).
const rawBaseQuery = fetchBaseQuery({
  baseUrl: new URL("/api", globalThis.location?.origin ?? "http://localhost").href,
  credentials: "include",
});

let unauthorizedHandler: (() => void) | null = null;

/** Register what happens when a request comes back 401. App wires it to Login; tests pass a spy. */
export function onUnauthorized(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

/** The backend's `detail` message, or a generic one if the body has none. */
function messageFrom(data: unknown, fallback: string): string {
  if (data && typeof data === "object" && "detail" in data && typeof data.detail === "string") {
    return data.detail;
  }
  return fallback;
}

/** `fetchBaseQuery`, with errors turned into `ApiQueryError` and 401 handed to `onUnauthorized`. */
export const baseQuery: BaseQueryFn<string | FetchArgs, unknown, ApiQueryError> = async (
  args,
  api,
  extraOptions,
) => {
  const result = await rawBaseQuery(args, api, extraOptions);
  if (!result.error) return { data: result.data, meta: result.meta };

  const { status } = result.error;
  if (status === 401) unauthorizedHandler?.();
  if (typeof status === "number") {
    return { error: { status, message: messageFrom(result.error.data, `Request failed (${status})`) } };
  }
  return { error: { status: "network", message: "The server is unreachable" } };
};

export const baseApi = createApi({
  reducerPath: "api",
  baseQuery,
  // Each feature lists the tags its endpoints use when it injects them
  tagTypes: ["AdminUser", "SigningKey", "OidcProvider"],
  endpoints: () => ({}),
});
