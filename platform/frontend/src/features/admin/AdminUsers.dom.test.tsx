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
 * error and empty states, a create the backend rejects, how often it fetches (the /admin loader's prefetch is
 * not fetched again, a list older than LIST_MAX_AGE_SECONDS is), and that
 * coming back to the tab shows the cached list at once. The full create, edit
 * and delete flow is covered end to end in e2e/full/admin-users.spec.ts. */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Provider } from "react-redux";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { AdminUser } from "@/lib/api/types";
import { createAppStore } from "@/lib/api/store";
import { adminApi, LIST_MAX_AGE_SECONDS } from "./adminApi.ts";
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

// jsdom has no modal dialogs: showModal and close just set the open attribute
beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

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

test("a duplicate username shows the backend's message in the dialog, which stays open", async () => {
  const user_ = userEvent.setup();
  fetchMock.mockImplementation(async (input) => {
    const req = input as Request;
    return req.method === "POST"
      ? respond(409, { detail: "Username already exists" })
      : respond(200, [user("someone")]);
  });
  renderUsers();
  await screen.findByRole("cell", { name: "someone" });

  await user_.click(screen.getByRole("button", { name: "New user" }));
  const dialog = screen.getByRole("dialog", { name: "New user" });
  await user_.type(within(dialog).getByLabelText("Username"), "someone");
  await user_.type(within(dialog).getByLabelText("Password"), "pw");
  await user_.click(within(dialog).getByRole("button", { name: "Create" }));

  expect(await within(dialog).findByRole("alert")).toHaveTextContent("Username already exists");
  expect(dialog).toHaveAttribute("open");
});

test("a failed refresh shows its error in place of the rows from before it", async () => {
  fetchMock.mockResolvedValueOnce(respond(200, [user("someone")]));
  const { store } = renderUsers();
  expect(await screen.findByRole("cell", { name: "someone" })).toBeInTheDocument();

  // Still on the screen when the list refetches and fails (say the admin was demoted)
  fetchMock.mockResolvedValueOnce(respond(403, { detail: "Admin only" }));
  store.dispatch(adminApi.util.invalidateTags(["AdminUser"]));

  expect(await screen.findByRole("alert")).toHaveTextContent("Admin only");
  expect(screen.queryByRole("cell", { name: "someone" })).not.toBeInTheDocument();
});

test("a list the loader started is fetched once, whether it's still loading or already in", async () => {
  // Still in flight when the page mounts: the page joins that request
  fetchMock.mockImplementation(() => Promise.resolve(respond(200, [user("someone")])));
  const inFlight = createAppStore();
  void inFlight.dispatch(adminApi.endpoints.listAdminUsers.initiate());
  const first = renderUsers(inFlight);
  expect(await screen.findByRole("cell", { name: "someone" })).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
  first.unmount();

  // Already in when the page mounts: shown from the cache, no second request
  fetchMock.mockClear();
  const settled = createAppStore();
  await settled.dispatch(adminApi.endpoints.listAdminUsers.initiate());
  renderUsers(settled);
  expect(screen.getByRole("cell", { name: "someone" })).toBeInTheDocument();
  await new Promise((r) => setTimeout(r, 50));
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test("coming back to the tab shows the cached list at once, and refreshes it once it's old", async () => {
  // Only the clock is faked; timers and promises run for real
  vi.useFakeTimers({ toFake: ["Date"] });
  const start = Date.now();
  fetchMock.mockResolvedValueOnce(respond(200, [user("first")]));
  const { store, unmount } = renderUsers();
  expect(await screen.findByRole("cell", { name: "first" })).toBeInTheDocument();
  unmount();

  // Back within the max age: the cached list, and no request
  vi.setSystemTime(start + (LIST_MAX_AGE_SECONDS - 1) * 1000);
  renderUsers(store).unmount();
  await new Promise((r) => setTimeout(r, 50));
  expect(fetchMock).toHaveBeenCalledTimes(1);

  // Back after it: the cached list at once, then the refreshed one
  vi.setSystemTime(start + (LIST_MAX_AGE_SECONDS + 1) * 1000);
  let resolve!: (r: Response) => void;
  fetchMock.mockReturnValueOnce(new Promise((r) => (resolve = r)));
  renderUsers(store);

  expect(screen.getByRole("cell", { name: "first" })).toBeInTheDocument();
  expect(screen.queryByText("Loading...")).not.toBeInTheDocument();
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

  resolve(respond(200, [user("first"), user("second")]));
  expect(await screen.findByRole("cell", { name: "second" })).toBeInTheDocument();
});
