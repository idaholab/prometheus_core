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

/* Admin > Users with the real RTK Query cache and a stubbed fetch: its loading,
 * error and empty states, and that leaving the tab and coming back shows the
 * cached list at once and then refreshes it. The full create, edit and delete
 * flow is covered end to end in e2e/full/admin-users.spec.ts. */
import { render, screen, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { AdminUser } from "@/lib/api/types";
import { createAppStore } from "@/lib/api/store";
import { AdminUsers } from "./AdminUsers.tsx";

const fetchMock = vi.fn<typeof fetch>();

function user(username: string): AdminUser {
  return {
    id: username,
    username,
    role: "user",
    provider: "local",
    is_active: true,
    last_login_at: null,
  } as AdminUser;
}

function respond(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function renderUsers(store = createAppStore()) {
  return {
    store,
    ...render(
      <Provider store={store}>
        <AdminUsers />
      </Provider>,
    ),
  };
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

test("shows Loading until the list arrives, then the users", async () => {
  let resolve!: (r: Response) => void;
  fetchMock.mockReturnValueOnce(new Promise((r) => (resolve = r)));
  renderUsers();

  expect(screen.getByText("Loading...")).toBeInTheDocument();
  resolve(respond(200, [user("someone")]));
  expect(await screen.findByRole("cell", { name: "someone" })).toBeInTheDocument();
  expect(screen.queryByText("Loading...")).not.toBeInTheDocument();
});

test("an empty list says there are no users", async () => {
  fetchMock.mockResolvedValueOnce(respond(200, []));
  renderUsers();
  expect(await screen.findByText("No users yet.")).toBeInTheDocument();
});

test("a failed load shows the backend's message", async () => {
  fetchMock.mockResolvedValueOnce(respond(500, { detail: "Database is down" }));
  renderUsers();
  expect(await screen.findByRole("alert")).toHaveTextContent("Database is down");
});

test("coming back to the tab shows the cached list at once, then refreshes it", async () => {
  fetchMock.mockResolvedValueOnce(respond(200, [user("first")]));
  const { store, unmount } = renderUsers();
  expect(await screen.findByRole("cell", { name: "first" })).toBeInTheDocument();
  unmount();

  // The refresh hangs until released, to see what shows meanwhile
  let resolve!: (r: Response) => void;
  fetchMock.mockReturnValueOnce(new Promise((r) => (resolve = r)));
  renderUsers(store);

  expect(screen.getByRole("cell", { name: "first" })).toBeInTheDocument();
  expect(screen.queryByText("Loading...")).not.toBeInTheDocument();
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

  resolve(respond(200, [user("first"), user("second")]));
  expect(await screen.findByRole("cell", { name: "second" })).toBeInTheDocument();
});
