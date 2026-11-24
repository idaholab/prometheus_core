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

/* Admin > Signing Keys with the real RTK Query cache and a stubbed backend:
 * the list and its states, and that generating, activating and retiring a key
 * each send their request, refetch the list, and show a failure in its own
 * banner. */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Provider } from "react-redux";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { SigningKey } from "@/lib/api/types";
import { createAppStore } from "@/lib/api/store";
import { AdminSigningKeys } from "./AdminSigningKeys.tsx";

function key(kid: string, state: Partial<SigningKey> = {}): SigningKey {
  return {
    id: kid,
    kid,
    public_key_pem: `PEM ${kid}`,
    is_active: false,
    created_at: "2026-11-01T00:00:00Z",
    retired_at: null,
    ...state,
  };
}

const fetchMock = vi.fn<typeof fetch>();

function respond(status: number, body?: unknown) {
  return body === undefined
    ? new Response(null, { status })
    : new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

/** The method and path of each request so far, as "POST /api/admin/signing-keys". */
function requests(): string[] {
  return fetchMock.mock.calls.map(([input]) => {
    const req = input as Request;
    return `${req.method} ${new URL(req.url).pathname}`;
  });
}

function renderKeys() {
  return render(
    <Provider store={createAppStore()}>
      <AdminSigningKeys />
    </Provider>,
  );
}

function row(kid: string) {
  return screen.getByRole("cell", { name: kid }).closest("tr") as HTMLElement;
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

test("lists the keys with their status, and says when there are none", async () => {
  fetchMock.mockResolvedValueOnce(
    respond(200, [
      key("k-active", { is_active: true }),
      key("k-new"),
      key("k-old", { retired_at: "2026-11-02T00:00:00Z" }),
    ]),
  );
  const { unmount } = renderKeys();

  expect(await screen.findByRole("cell", { name: "k-active" })).toBeInTheDocument();
  expect(within(row("k-active")).getByText("active")).toBeInTheDocument();
  expect(within(row("k-new")).getByRole("button", { name: "Activate" })).toBeInTheDocument();
  expect(within(row("k-old")).queryByRole("button", { name: "Retire" })).not.toBeInTheDocument();
  unmount();

  fetchMock.mockResolvedValueOnce(respond(200, []));
  renderKeys();
  expect(await screen.findByText(/No signing keys yet/)).toBeInTheDocument();
});

test("a failed load shows the backend's message", async () => {
  fetchMock.mockResolvedValueOnce(respond(500, { detail: "Database is down" }));
  renderKeys();
  expect(await screen.findByRole("alert")).toHaveTextContent("Database is down");
  expect(screen.queryByText("Loading...")).not.toBeInTheDocument();
});

test("generating a key sends the request and refetches the list", async () => {
  const user = userEvent.setup();
  fetchMock
    .mockResolvedValueOnce(respond(200, []))
    .mockResolvedValueOnce(respond(201, key("k-1")))
    .mockResolvedValueOnce(respond(200, [key("k-1")]));
  renderKeys();
  await screen.findByText(/No signing keys yet/);

  await user.click(screen.getByRole("button", { name: "Generate key" }));

  expect(await screen.findByRole("cell", { name: "k-1" })).toBeInTheDocument();
  expect(requests()).toEqual([
    "GET /api/admin/signing-keys",
    "POST /api/admin/signing-keys",
    "GET /api/admin/signing-keys",
  ]);
});

test("activating and retiring a key send the request for that key and refetch the list", async () => {
  const user = userEvent.setup();
  fetchMock
    .mockResolvedValueOnce(respond(200, [key("k-1")]))
    .mockResolvedValueOnce(respond(200, key("k-1", { is_active: true })))
    .mockResolvedValueOnce(respond(200, [key("k-1", { is_active: true })]))
    .mockResolvedValueOnce(respond(200, key("k-1", { retired_at: "2026-11-03T00:00:00Z" })))
    .mockResolvedValueOnce(respond(200, [key("k-1", { retired_at: "2026-11-03T00:00:00Z" })]));
  renderKeys();
  await screen.findByRole("cell", { name: "k-1" });

  await user.click(within(row("k-1")).getByRole("button", { name: "Activate" }));
  expect(await within(row("k-1")).findByText("active")).toBeInTheDocument();

  await user.click(within(row("k-1")).getByRole("button", { name: "Retire" }));
  expect(await within(row("k-1")).findByText("retired")).toBeInTheDocument();

  expect(requests()).toEqual([
    "GET /api/admin/signing-keys",
    "POST /api/admin/signing-keys/k-1/activate",
    "GET /api/admin/signing-keys",
    "POST /api/admin/signing-keys/k-1/retire",
    "GET /api/admin/signing-keys",
  ]);
});

/** Answer each request from `routes`, keyed by "METHOD /path"; the last answer for a key repeats. */
function serve(routes: Record<string, Response[]>) {
  fetchMock.mockImplementation(async (input) => {
    const req = input as Request;
    const answers = routes[`${req.method} ${new URL(req.url).pathname}`];
    if (!answers) throw new Error(`unexpected ${req.method} ${req.url}`);
    return (answers.length > 1 ? answers.shift() : answers[0])!.clone();
  });
}

test("a failed action shows its message and keeps the list", async () => {
  const user = userEvent.setup();
  serve({
    "GET /api/admin/signing-keys": [respond(200, [key("k-1")])],
    "POST /api/admin/signing-keys/k-1/activate": [respond(409, { detail: "Another key is being activated" })],
  });
  renderKeys();
  await screen.findByRole("cell", { name: "k-1" });

  await user.click(within(row("k-1")).getByRole("button", { name: "Activate" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Another key is being activated");
  expect(screen.getByRole("cell", { name: "k-1" })).toBeInTheDocument();
});

test("a failed action's message stays when the list also fails to load", async () => {
  const user = userEvent.setup();
  serve({
    "GET /api/admin/signing-keys": [respond(500, { detail: "Database is down" })],
    "POST /api/admin/signing-keys": [respond(503, { detail: "Key store unavailable" })],
  });
  renderKeys();
  await screen.findByRole("alert");

  // Generate sits outside the table, so it can still be tried
  await user.click(screen.getByRole("button", { name: "Generate key" }));

  await screen.findByText("Key store unavailable");
  expect(screen.getAllByRole("alert").map((a) => a.textContent)).toEqual([
    "Key store unavailable",
    "Database is down",
  ]);
});
