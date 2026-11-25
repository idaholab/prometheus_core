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

/* Admin's RTK Query endpoints: each sends the backend's method and path, a
 * change refetches its list, and the users list can be loaded before the page
 * renders. `fetch` is stubbed; the store is real. */
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { appStore, createAppStore } from "@/lib/api/store";
import { adminApi, errorMessage, prefetchAdminUsers } from "./adminApi.ts";

const fetchMock = vi.fn<typeof fetch>();

/** Answer every request with `body` (200), or 204 when `body` is undefined. */
function answerAll(body?: unknown) {
  fetchMock.mockImplementation(() =>
    Promise.resolve(
      body === undefined
        ? new Response(null, { status: 204 })
        : new Response(JSON.stringify(body), {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
    ),
  );
}

/** "METHOD /path" of every request, in order. */
function calls(): string[] {
  return fetchMock.mock.calls.map(([input]) => {
    const request = input as Request;
    return `${request.method} ${new URL(request.url).pathname}`;
  });
}

async function bodyOf(index: number): Promise<unknown> {
  return (fetchMock.mock.calls[index][0] as Request).json();
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  appStore.dispatch(adminApi.util.resetApiState());
});

describe("endpoints send the backend's method and path", () => {
  const cases: [string, (store: ReturnType<typeof createAppStore>) => unknown, string, unknown?][] = [
    ["list users", (s) => s.dispatch(adminApi.endpoints.listAdminUsers.initiate()), "GET /api/admin/users"],
    [
      "create a user",
      (s) =>
        s.dispatch(
          adminApi.endpoints.createAdminUser.initiate({ username: "a", password: "p", role: "user" }),
        ),
      "POST /api/admin/users",
      { username: "a", password: "p", role: "user" },
    ],
    [
      "update a user",
      (s) => s.dispatch(adminApi.endpoints.updateAdminUser.initiate({ id: "u 1", patch: { role: "admin" } })),
      "PATCH /api/admin/users/u%201",
      { role: "admin" },
    ],
    [
      "delete a user",
      (s) => s.dispatch(adminApi.endpoints.deleteAdminUser.initiate("u1")),
      "DELETE /api/admin/users/u1",
    ],
    [
      "list signing keys",
      (s) => s.dispatch(adminApi.endpoints.listSigningKeys.initiate()),
      "GET /api/admin/signing-keys",
    ],
    [
      "generate a key",
      (s) => s.dispatch(adminApi.endpoints.generateSigningKey.initiate()),
      "POST /api/admin/signing-keys",
    ],
    [
      "activate a key",
      (s) => s.dispatch(adminApi.endpoints.activateSigningKey.initiate("k1")),
      "POST /api/admin/signing-keys/k1/activate",
    ],
    [
      "retire a key",
      (s) => s.dispatch(adminApi.endpoints.retireSigningKey.initiate("k1")),
      "POST /api/admin/signing-keys/k1/retire",
    ],
    [
      "list identity providers",
      (s) => s.dispatch(adminApi.endpoints.listOidcProviders.initiate()),
      "GET /api/admin/oidc-providers",
    ],
    [
      "create a provider",
      (s) =>
        s.dispatch(
          adminApi.endpoints.createOidcProvider.initiate({
            provider_id: "p",
            display_name: "P",
            issuer_url: "https://idp",
            client_id: "c",
            client_secret: "s",
            scopes: "openid",
            default_role: "user",
            is_enabled: true,
          }),
        ),
      "POST /api/admin/oidc-providers",
    ],
    [
      "update a provider",
      (s) =>
        s.dispatch(
          adminApi.endpoints.updateOidcProvider.initiate({ id: "p1", patch: { is_enabled: false } }),
        ),
      "PATCH /api/admin/oidc-providers/p1",
      { is_enabled: false },
    ],
    [
      "delete a provider",
      (s) => s.dispatch(adminApi.endpoints.deleteOidcProvider.initiate("p1")),
      "DELETE /api/admin/oidc-providers/p1",
    ],
  ];

  test.each(cases)("%s", async (_name, run, expected, body) => {
    answerAll({});
    await run(createAppStore());
    expect(calls()[0]).toBe(expected);
    if (body !== undefined) expect(await bodyOf(0)).toEqual(body);
  });
});

describe("a change refetches its list", () => {
  test("creating a user refetches the users list", async () => {
    const store = createAppStore();
    answerAll([]);
    const list = store.dispatch(adminApi.endpoints.listAdminUsers.initiate());
    await list;

    await store.dispatch(
      adminApi.endpoints.createAdminUser.initiate({ username: "a", password: "p", role: "user" }),
    );
    await vi.waitFor(() =>
      expect(calls()).toEqual(["GET /api/admin/users", "POST /api/admin/users", "GET /api/admin/users"]),
    );
    list.unsubscribe();
  });

  test("activating a key refetches the keys, not the users", async () => {
    const store = createAppStore();
    answerAll([]);
    const users = store.dispatch(adminApi.endpoints.listAdminUsers.initiate());
    const keys = store.dispatch(adminApi.endpoints.listSigningKeys.initiate());
    await Promise.all([users, keys]);

    await store.dispatch(adminApi.endpoints.activateSigningKey.initiate("k1"));
    await vi.waitFor(() =>
      expect(calls().filter((c) => c === "GET /api/admin/signing-keys")).toHaveLength(2),
    );
    expect(calls().filter((c) => c === "GET /api/admin/users")).toHaveLength(1);
    users.unsubscribe();
    keys.unsubscribe();
  });
});

describe("prefetchAdminUsers", () => {
  test("starts loading the users list into the app's cache", async () => {
    answerAll([{ id: "u1", username: "someone" }]);
    prefetchAdminUsers();

    await vi.waitFor(() => {
      const cached = adminApi.endpoints.listAdminUsers.select()(appStore.getState());
      expect(cached.data).toEqual([{ id: "u1", username: "someone" }]);
    });
    expect(calls()).toEqual(["GET /api/admin/users"]);
  });
});

describe("errorMessage", () => {
  test("uses the backend's message", () => {
    expect(errorMessage({ status: 409, message: "Username already exists" }, "Could not create user")).toBe(
      "Username already exists",
    );
  });

  test("falls back when there's no message", () => {
    expect(errorMessage({ status: 500, message: "" }, "Could not create user")).toBe("Could not create user");
    expect(errorMessage(undefined, "Could not create user")).toBe("Could not create user");
    expect(errorMessage(new Error("boom"), "Fallback")).toBe("boom");
  });
});
