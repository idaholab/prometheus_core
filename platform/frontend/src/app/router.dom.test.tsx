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
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { beforeEach, expect, test, vi } from "vitest";
import type { User } from "@/lib/api/types";

const api = vi.hoisted(() => ({
  login: vi.fn(),
  bootstrap: vi.fn(),
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
const chat = vi.hoisted(() => ({
  authLost: false,
  store: {
    bootstrap: vi.fn(),
    connect: vi.fn(),
    reset: vi.fn(),
    clear: vi.fn(),
    suspendForReauth: vi.fn(),
    loadConversation: vi.fn(),
  },
}));
// The store module itself, since chat's own files import it directly.
vi.mock("@/features/chat/store/chat", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/chat/store/chat")>()),
  chatStore: chat.store,
  useAuthLost: () => chat.authLost,
}));

// Stand-ins for the heavier pages. Workflows counts its mounts, so a test can
// tell a remount (Builder back to Console) from a re-render; Agent Registry
// throws on demand, for the error page.
const pages = vi.hoisted(() => ({ workflowsMounts: 0, registryThrows: false }));
vi.mock("@/pages/PageHome", () => ({ PageHome: () => <p>Home page</p> }));
vi.mock("@/pages/PageWorkflows", async () => {
  const { useState } = await import("react");
  return {
    PageWorkflows: () => {
      const [mount] = useState(() => ++pages.workflowsMounts);
      return <p>Workflows page, mount {mount}</p>;
    },
  };
});
vi.mock("@/pages/PageAdmin", () => ({ PageAdmin: () => <p>Admin page</p> }));
vi.mock("@/pages/PageAgentRegistry", () => ({
  PageAgentRegistry: () => {
    if (pages.registryThrows) throw new Error("boom");
    return <p>Agent Registry page</p>;
  },
}));
vi.mock("@/pages/PageApprovalQueue", () => ({ PageApprovalQueue: () => <p>Approval Queue page</p> }));
vi.mock("@/pages/PageDataManagement", () => ({ PageDataManagement: () => <p>Data Management page</p> }));
vi.mock("@/pages/PageProjectManagement", () => ({ PageProjectManagement: () => <p>Project Management page</p> }));

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
  chat.authLost = false;
  pages.workflowsMounts = 0;
  pages.registryThrows = false;
  setCurrentUser(null);
  api.setupStatus.mockResolvedValue({ needs_setup: false });
  api.me.mockRejectedValue(new ApiError(401, "Not authenticated"));
  api.getRecentConversations.mockResolvedValue({ available: true, conversations: [] });
  api.listAuthProviders.mockResolvedValue([]);
});

test("a deep link opens that page, with its nav item current and its title", async () => {
  setCurrentUser(USER);
  open("/workflows");

  expect(await screen.findByText(/^Workflows page/)).toBeVisible();
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
  expect(await screen.findByText(/^Workflows page/)).toBeVisible();
  // jsdom has no Tailwind CSS, so check the class that hides it
  expect(home).toBeInTheDocument();
  expect(home.parentElement).toHaveClass("hidden");

  await act(() => router.navigate(-1));
  expect(router.state.location.pathname).toBe("/");
  // Home's text never leaves the page, so wait for the class, not the text
  await waitFor(() => expect(home.parentElement).not.toHaveClass("hidden"));
  expect(screen.getByText("Home page")).toBe(home);
});

test("logging out returns to Login", async () => {
  const user = userEvent.setup();
  setCurrentUser(USER);
  api.logout.mockResolvedValue(undefined);
  const router = open("/workflows");
  await screen.findByText(/^Workflows page/);

  await user.click(screen.getByRole("button", { name: "Log out" }));
  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
  expect(router.state.location.pathname).toBe("/login");
});

const SECTIONS = [
  { url: "/", link: "Home", title: "Home", body: "Home page" },
  { url: "/agent-registry", link: "Agent Registry", title: "Agent Registry", body: "Agent Registry page" },
  { url: "/workflows", link: "Workflows", title: "Workflows", body: /^Workflows page/ },
  { url: "/approval-queue", link: "Approval Queue", title: "Approval Queue", body: "Approval Queue page" },
  { url: "/project-management", link: "Project Management", title: "Project Management", body: "Project Management page" },
  { url: "/data-management", link: "Data Management", title: "Data Management", body: "Data Management page" },
  { url: "/jobs-console", link: "Jobs Console", title: "Jobs Console", body: "Coming soon" },
  { url: "/admin", link: "Admin", title: "Admin", body: "Admin page" },
];

test.each(SECTIONS)("$url opens $link, marks it current, and titles the page", async ({ url, link, title, body }) => {
  setCurrentUser(ADMIN);
  open(url);

  expect(await screen.findByText(body)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: link })).toHaveAttribute("aria-current", "page");
  for (const other of SECTIONS.filter((s) => s.link !== link)) {
    expect(screen.getByRole("link", { name: other.link })).not.toHaveAttribute("aria-current");
  }
  expect(screen.getByRole("heading", { level: 1, name: title })).toBeInTheDocument();
  const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
  expect(within(crumbs).getByText(title)).toHaveAttribute("aria-current", "page");
});

test("forward returns to the page that back left", async () => {
  const user = userEvent.setup();
  setCurrentUser(USER);
  const router = open("/");
  await screen.findByText("Home page");

  await user.click(screen.getByRole("link", { name: "Approval Queue" }));
  await screen.findByText("Approval Queue page");
  await router.navigate(-1);
  expect(router.state.location.pathname).toBe("/");
  await router.navigate(1);
  expect(router.state.location.pathname).toBe("/approval-queue");
  expect(await screen.findByText("Approval Queue page")).toBeInTheDocument();
});

test("clicking Workflows again remounts it, so the Builder returns to the Console", async () => {
  const user = userEvent.setup();
  setCurrentUser(USER);
  open("/workflows");
  expect(await screen.findByText("Workflows page, mount 1")).toBeInTheDocument();

  await user.click(screen.getByRole("link", { name: "Workflows" }));
  expect(await screen.findByText("Workflows page, mount 2")).toBeInTheDocument();
});

test("clicking another section does not remount the page it leaves to", async () => {
  const user = userEvent.setup();
  setCurrentUser(USER);
  open("/approval-queue");
  await screen.findByText("Approval Queue page");

  await user.click(screen.getByRole("link", { name: "Workflows" }));
  expect(await screen.findByText("Workflows page, mount 1")).toBeInTheDocument();
});

test("New Chat goes Home and starts a fresh conversation", async () => {
  const user = userEvent.setup();
  setCurrentUser(USER);
  const router = open("/workflows");
  await screen.findByText(/^Workflows page/);

  await user.click(screen.getByRole("button", { name: "New Chat" }));
  expect(router.state.location.pathname).toBe("/");
  expect(chat.store.reset).toHaveBeenCalledOnce();
});

test("the collapsed sidebar's new-chat button also goes Home", async () => {
  const user = userEvent.setup();
  setCurrentUser(USER);
  const router = open("/workflows");
  await screen.findByText(/^Workflows page/);

  await user.click(screen.getByRole("button", { name: "Collapse sidebar" }));
  await user.click(screen.getByRole("button", { name: "New chat" }));
  expect(router.state.location.pathname).toBe("/");
  expect(chat.store.reset).toHaveBeenCalledOnce();
});

test("opening a past conversation from the history goes Home", async () => {
  const user = userEvent.setup();
  setCurrentUser(USER);
  api.getRecentConversations.mockResolvedValue({
    available: true,
    conversations: [
      { conversation_id: "c-1", title: "Corrosion study", query: "", status: "done", timestamp: "", pending: false },
    ],
  });
  const router = open("/workflows");

  await user.click(await screen.findByRole("button", { name: "Corrosion study" }));
  expect(router.state.location.pathname).toBe("/");
  expect(chat.store.loadConversation).toHaveBeenCalledWith("c-1");
});

test("a lost session goes to Login, remembering the page", async () => {
  setCurrentUser(USER);
  chat.authLost = true;
  const router = open("/approval-queue?tab=open");

  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
  expect(chat.store.suspendForReauth).toHaveBeenCalled();
  expect(router.state.location.pathname).toBe("/login");
  expect(router.state.location.search).toBe(`?next=${encodeURIComponent("/approval-queue?tab=open")}`);
});

test("logging out still returns to Login when the server call fails", async () => {
  const user = userEvent.setup();
  setCurrentUser(USER);
  api.logout.mockRejectedValue(new Error("offline"));
  const router = open("/");
  await screen.findByText("Home page");

  await user.click(screen.getByRole("button", { name: "Log out" }));
  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
  expect(chat.store.clear).toHaveBeenCalledOnce();
  expect(router.state.location.pathname).toBe("/login");
});

test("the settings panel opens from the user menu and closes", async () => {
  const user = userEvent.setup();
  setCurrentUser(USER);
  open("/");
  await screen.findByText("Home page");
  const panel = screen.getByRole("heading", { name: "Settings" }).closest("aside");

  expect(panel).toHaveClass("w-0");
  await user.click(screen.getByRole("button", { name: "Settings" }));
  expect(panel).toHaveClass("w-64");
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(panel).toHaveClass("w-0");
});

test("a page that throws shows the error page, never a blank screen", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  setCurrentUser(USER);
  pages.registryThrows = true;
  open("/agent-registry");

  expect(await screen.findByRole("heading", { name: "Something went wrong" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Reload" })).toBeEnabled();
});

test("signing in on the Login form opens the page it was sent from", async () => {
  const user = userEvent.setup();
  api.login.mockResolvedValue(USER);
  const router = open("/approval-queue");

  await user.type(await screen.findByRole("textbox", { name: "Username" }), "someone");
  await user.type(screen.getByLabelText("Password"), "the-password");
  await user.click(screen.getByRole("button", { name: "Sign in" }));

  expect(await screen.findByText("Approval Queue page")).toBeInTheDocument();
  expect(router.state.location.pathname).toBe("/approval-queue");
});

test("finishing Setup opens Home", async () => {
  const user = userEvent.setup();
  api.setupStatus.mockResolvedValue({ needs_setup: true });
  api.bootstrap.mockResolvedValue({ ...USER, role: "admin" });
  const router = open("/setup");

  await user.type(await screen.findByRole("textbox", { name: "Username" }), "admin");
  await user.type(screen.getByLabelText("Password"), "the-password");
  await user.type(screen.getByLabelText("Confirm password"), "the-password");
  await user.click(screen.getByRole("button", { name: "Create admin account" }));

  expect(await screen.findByText("Home page")).toBeInTheDocument();
  expect(router.state.location.pathname).toBe("/");
});
