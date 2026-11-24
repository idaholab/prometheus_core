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

/* App's wiring around the router: the Redux store is provided, and a 401 from
 * any RTK Query request ends the session as a lost one and sends the user to
 * Login, then back.
 * The route table is swapped for a tiny memory router so the test can see
 * where App navigates; the real routes are covered by app/router.dom.test.tsx. */
import { act, render, screen } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

const auth = vi.hoisted(() => ({ setCurrentUser: vi.fn() }));
vi.mock("@/features/auth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/auth")>()),
  setCurrentUser: auth.setCurrentUser,
}));

const chat = vi.hoisted(() => ({ clear: vi.fn(), suspendForReauth: vi.fn() }));
vi.mock("@/features/chat", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/chat")>()),
  chatStore: chat,
}));

const routing = vi.hoisted(() => ({ router: null as ReturnType<typeof createMemoryRouter> | null }));
vi.mock("@/app/router", async () => {
  const { createMemoryRouter } = await import("react-router");
  return {
    createAppRouter: () => {
      routing.router = createMemoryRouter(
        [
          { path: "/admin", element: <p>Admin page</p> },
          { path: "/login", element: <p>Login page</p> },
        ],
        { initialEntries: ["/admin?tab=users"] },
      );
      return routing.router;
    },
  };
});

const { default: App } = await import("./App.tsx");
const { baseQuery } = await import("@/lib/api/baseApi");

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  auth.setCurrentUser.mockReset();
  chat.clear.mockReset();
  chat.suspendForReauth.mockReset();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

/** Run one request through the real base query, as any endpoint would. */
async function request(status: number) {
  fetchMock.mockResolvedValueOnce(
    new Response(JSON.stringify({ detail: "x" }), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
  const api = { signal: new AbortController().signal, dispatch: vi.fn(), getState: vi.fn() };
  await act(async () => {
    await baseQuery("/probe", api as never, {});
  });
}

test("a 401 from any request forgets the user and goes to Login, then back to the page", async () => {
  render(<App />);
  expect(await screen.findByText("Admin page")).toBeInTheDocument();

  await request(401);

  expect(auth.setCurrentUser).toHaveBeenCalledWith(null);
  // As a lost chat session does: chat stops, but keeps its conversation for after sign-in
  expect(chat.suspendForReauth).toHaveBeenCalledOnce();
  expect(chat.clear).not.toHaveBeenCalled();
  expect(await screen.findByText("Login page")).toBeInTheDocument();
  expect(routing.router?.state.location.search).toBe(`?next=${encodeURIComponent("/admin?tab=users")}`);
});

test("other errors leave the user where they are", async () => {
  render(<App />);
  expect(await screen.findByText("Admin page")).toBeInTheDocument();

  await request(500);

  expect(auth.setCurrentUser).not.toHaveBeenCalled();
  expect(screen.getByText("Admin page")).toBeInTheDocument();
});

test("unmounting App stops handling 401s", async () => {
  const { unmount } = render(<App />);
  expect(await screen.findByText("Admin page")).toBeInTheDocument();
  unmount();

  await request(401);
  expect(auth.setCurrentUser).not.toHaveBeenCalled();
});
