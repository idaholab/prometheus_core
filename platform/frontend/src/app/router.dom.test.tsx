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

/* The real route table, guards and app shell in a memory router. The API is
 * stubbed and the heavier pages are stand-ins, so this checks routing and
 * access, not what each screen shows. */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { beforeEach, expect, test, vi } from "vitest";
import type { User } from "@/lib/api/types";

const api = vi.hoisted(() => ({
  setupStatus: vi.fn(),
  me: vi.fn(),
  logout: vi.fn(),
  getRecentConversations: vi.fn(),
  listAuthProviders: vi.fn(),
}));
vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  api,
}));
vi.mock("@/features/chat", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/chat")>()),
  chatStore: { bootstrap: vi.fn(), connect: vi.fn(), reset: vi.fn(), clear: vi.fn(), suspendForReauth: vi.fn() },
  useAuthLost: () => false,
}));
vi.mock("@/pages/PageHome", () => ({ PageHome: () => <p>Home page</p> }));
vi.mock("@/pages/PageWorkflows", () => ({ PageWorkflows: () => <p>Workflows page</p> }));
vi.mock("@/pages/PageAdmin", () => ({ PageAdmin: () => <p>Admin page</p> }));
vi.mock("@/pages/PageAgentRegistry", () => ({ PageAgentRegistry: () => <p>Agent Registry page</p> }));

// jsdom has no matchMedia; the header's theme toggle reads it.
vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));

const { setCurrentUser } = await import("@/features/auth");
const { routes } = await import("./router.tsx");
const { ApiError } = await import("@/lib/api/client");

const USER: User = { identifier: "someone", role: "user", provider: "local" };
const ADMIN: User = { ...USER, role: "admin" };

function open(url: string) {
  const router = createMemoryRouter(routes, { initialEntries: [url] });
  render(<RouterProvider router={router} />);
  return router;
}

beforeEach(() => {
  vi.clearAllMocks();
  setCurrentUser(null);
  api.setupStatus.mockResolvedValue({ needs_setup: false });
  api.me.mockRejectedValue(new ApiError(401, "Not authenticated"));
  api.getRecentConversations.mockResolvedValue({ available: true, conversations: [] });
  api.listAuthProviders.mockResolvedValue([]);
});

test("a deep link opens that page, with its nav item current and its title", async () => {
  setCurrentUser(USER);
  open("/workflows");

  expect(await screen.findByText("Workflows page")).toBeVisible();
  expect(screen.getByRole("link", { name: "Workflows" })).toHaveAttribute("aria-current", "page");
  expect(screen.getByRole("heading", { level: 1, name: "Workflows" })).toBeInTheDocument();
});

test("a signed-out deep link goes through Login, then lands on the page", async () => {
  const router = open("/agent-registry");

  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
  expect(router.state.location.search).toBe("?next=%2Fagent-registry");

  // What Login does on success, without driving the form
  setCurrentUser(USER);
  await router.navigate("/login?next=%2Fagent-registry");
  expect(await screen.findByText("Agent Registry page")).toBeVisible();
  expect(router.state.location.pathname).toBe("/agent-registry");
});

test("a fresh install goes to Setup", async () => {
  api.setupStatus.mockResolvedValue({ needs_setup: true });
  const router = open("/workflows");
  expect(await screen.findByRole("heading", { name: /admin/i })).toBeVisible();
  expect(router.state.location.pathname).toBe("/setup");
});

test("a non-admin opening Admin is sent Home and never sees it", async () => {
  setCurrentUser(USER);
  const router = open("/admin");
  expect(await screen.findByText("Home page")).toBeVisible();
  expect(router.state.location.pathname).toBe("/");
  expect(screen.queryByText("Admin page")).not.toBeInTheDocument();
});

test("an admin can open Admin", async () => {
  setCurrentUser(ADMIN);
  open("/admin");
  expect(await screen.findByText("Admin page")).toBeVisible();
});

test("an unknown URL shows Not Found inside the shell", async () => {
  setCurrentUser(USER);
  open("/no-such-page");
  expect(await screen.findByRole("heading", { name: "This page does not exist" })).toBeVisible();
  expect(screen.getByRole("link", { name: "Go to Home" })).toHaveAttribute("href", "/");
});

test("sidebar links change the URL, back returns, and Home stays mounted while hidden", async () => {
  const user = userEvent.setup();
  setCurrentUser(USER);
  const router = open("/");
  const home = await screen.findByText("Home page");

  await user.click(screen.getByRole("link", { name: "Workflows" }));
  expect(router.state.location.pathname).toBe("/workflows");
  expect(await screen.findByText("Workflows page")).toBeVisible();
  // jsdom has no Tailwind CSS, so check the class that hides it
  expect(home).toBeInTheDocument();
  expect(home.parentElement).toHaveClass("hidden");

  await router.navigate(-1);
  expect(router.state.location.pathname).toBe("/");
  expect(await screen.findByText("Home page")).toBe(home);
  expect(home.parentElement).not.toHaveClass("hidden");
});

test("logging out returns to Login", async () => {
  const user = userEvent.setup();
  setCurrentUser(USER);
  api.logout.mockResolvedValue(undefined);
  const router = open("/workflows");
  await screen.findByText("Workflows page");

  await user.click(screen.getByRole("button", { name: "Log out" }));
  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
  expect(router.state.location.pathname).toBe("/login");
});
