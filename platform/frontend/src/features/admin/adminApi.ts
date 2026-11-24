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
 * Admin's server data through RTK Query. Each list is cached under its own tag
 * ("AdminUser", "SigningKey", "OidcProvider"); a change to an item invalidates
 * that tag, so the list refetches on its own. Mirrors `backend/app/routers/admin*.py`
 * (require_admin server-side; 403 for non-admins).
 */
import { baseApi, type ApiQueryError } from "@/lib/api/baseApi";
import { appStore } from "@/lib/api/store";
import type {
  AdminUser,
  AdminUserCreate,
  AdminUserUpdate,
  OidcProvider,
  OidcProviderCreate,
  OidcProviderUpdate,
  SigningKey,
} from "@/lib/api/types";

/**
 * How old, in seconds, a cached list can be when a screen mounts before it is
 * fetched again. Coming back to a tab shows the cached list at once and
 * refreshes it once it's this old; a list the /admin loader has just fetched
 * isn't fetched a second time. Changes refetch their list straight away
 * through its tag, whatever its age.
 */
export const LIST_MAX_AGE_SECONDS = 30;

/** The backend's message for a failed Admin request, or `fallback`. */
export function errorMessage(error: unknown, fallback: string): string {
  const message = (error as Partial<ApiQueryError> | undefined)?.message;
  return typeof message === "string" && message ? message : fallback;
}

export const adminApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    listAdminUsers: build.query<AdminUser[], void>({
      query: () => "/admin/users",
      providesTags: ["AdminUser"],
    }),
    createAdminUser: build.mutation<AdminUser, AdminUserCreate>({
      query: (body) => ({ url: "/admin/users", method: "POST", body }),
      invalidatesTags: ["AdminUser"],
    }),
    updateAdminUser: build.mutation<AdminUser, { id: string; patch: AdminUserUpdate }>({
      query: ({ id, patch }) => ({
        url: `/admin/users/${encodeURIComponent(id)}`,
        method: "PATCH",
        body: patch,
      }),
      invalidatesTags: ["AdminUser"],
    }),
    deleteAdminUser: build.mutation<void, string>({
      query: (id) => ({ url: `/admin/users/${encodeURIComponent(id)}`, method: "DELETE" }),
      invalidatesTags: ["AdminUser"],
    }),

    listSigningKeys: build.query<SigningKey[], void>({
      query: () => "/admin/signing-keys",
      providesTags: ["SigningKey"],
    }),
    generateSigningKey: build.mutation<SigningKey, void>({
      query: () => ({ url: "/admin/signing-keys", method: "POST" }),
      invalidatesTags: ["SigningKey"],
    }),
    activateSigningKey: build.mutation<SigningKey, string>({
      query: (id) => ({ url: `/admin/signing-keys/${encodeURIComponent(id)}/activate`, method: "POST" }),
      invalidatesTags: ["SigningKey"],
    }),
    retireSigningKey: build.mutation<SigningKey, string>({
      query: (id) => ({ url: `/admin/signing-keys/${encodeURIComponent(id)}/retire`, method: "POST" }),
      invalidatesTags: ["SigningKey"],
    }),

    listOidcProviders: build.query<OidcProvider[], void>({
      query: () => "/admin/oidc-providers",
      providesTags: ["OidcProvider"],
    }),
    createOidcProvider: build.mutation<OidcProvider, OidcProviderCreate>({
      query: (body) => ({ url: "/admin/oidc-providers", method: "POST", body }),
      invalidatesTags: ["OidcProvider"],
    }),
    updateOidcProvider: build.mutation<OidcProvider, { id: string; patch: OidcProviderUpdate }>({
      query: ({ id, patch }) => ({
        url: `/admin/oidc-providers/${encodeURIComponent(id)}`,
        method: "PATCH",
        body: patch,
      }),
      invalidatesTags: ["OidcProvider"],
    }),
    deleteOidcProvider: build.mutation<void, string>({
      query: (id) => ({ url: `/admin/oidc-providers/${encodeURIComponent(id)}`, method: "DELETE" }),
      invalidatesTags: ["OidcProvider"],
    }),
  }),
});

export const {
  useListAdminUsersQuery,
  useCreateAdminUserMutation,
  useUpdateAdminUserMutation,
  useDeleteAdminUserMutation,
  useListSigningKeysQuery,
  useGenerateSigningKeyMutation,
  useActivateSigningKeyMutation,
  useRetireSigningKeyMutation,
  useListOidcProvidersQuery,
  useCreateOidcProviderMutation,
  useUpdateOidcProviderMutation,
  useDeleteOidcProviderMutation,
} = adminApi;

/**
 * Start loading the users list before Admin renders, so the table usually has
 * data on first paint. Called from the /admin route's loader, after the admin
 * guard. It doesn't wait: the page still shows its own loading state if the
 * list hasn't arrived. The subscription is released once the request settles;
 * the page's own hook keeps the cached list alive from then on.
 */
export function prefetchAdminUsers(): void {
  const request = appStore.dispatch(adminApi.endpoints.listAdminUsers.initiate());
  void request.finally(() => request.unsubscribe());
}
