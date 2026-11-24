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

/* Admin > Identity Providers with the real RTK Query cache and a stubbed
 * backend: the list and its states, and creating, editing and deleting a
 * provider through the dialogs, each refetching the list, with a failure shown
 * where it happened. */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Provider } from "react-redux";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { OidcProvider } from "@/lib/api/types";
import { createAppStore } from "@/lib/api/store";
import { AdminOidcProviders } from "./AdminOidcProviders.tsx";

function provider(name: string, fields: Partial<OidcProvider> = {}): OidcProvider {
  return {
    id: name.toLowerCase(),
    provider_id: name.toLowerCase(),
    display_name: name,
    issuer_url: `https://${name.toLowerCase()}.example`,
    client_id: `${name.toLowerCase()}-client`,
    scopes: "openid profile email",
    default_role: "user",
    is_enabled: true,
    created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-01T00:00:00Z",
    ...fields,
  };
}

const fetchMock = vi.fn<typeof fetch>();

function respond(status: number, body?: unknown) {
  return body === undefined
    ? new Response(null, { status })
    : new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

/** Answer each request from `routes`, keyed by "METHOD /path"; the last answer for a key repeats. */
function serve(routes: Record<string, Response[]>) {
  fetchMock.mockImplementation(async (input) => {
    const req = input as Request;
    const answers = routes[`${req.method} ${new URL(req.url).pathname}`];
    if (!answers) throw new Error(`unexpected ${req.method} ${req.url}`);
    return (answers.length > 1 ? answers.shift() : answers[0])!.clone();
  });
}

/** The requests so far, as "PATCH /api/admin/oidc-providers/okta". */
function requests(): string[] {
  return fetchMock.mock.calls.map(([input]) => {
    const req = input as Request;
    return `${req.method} ${new URL(req.url).pathname}`;
  });
}

/** The JSON body of the first request matching "METHOD /path". */
async function bodyOf(match: string): Promise<unknown> {
  const call = fetchMock.mock.calls.find(([input]) => {
    const req = input as Request;
    return `${req.method} ${new URL(req.url).pathname}` === match;
  });
  return (call![0] as Request).clone().json();
}

function renderProviders() {
  return render(
    <Provider store={createAppStore()}>
      <AdminOidcProviders />
    </Provider>,
  );
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
  vi.restoreAllMocks();
});

test("lists the providers, and says when there are none", async () => {
  serve({ "GET /api/admin/oidc-providers": [respond(200, [provider("Okta", { is_enabled: false })])] });
  const { unmount } = renderProviders();

  const row = (await screen.findByRole("cell", { name: "Okta" })).closest("tr") as HTMLElement;
  expect(within(row).getByText("disabled")).toBeInTheDocument();
  unmount();

  serve({ "GET /api/admin/oidc-providers": [respond(200, [])] });
  renderProviders();
  expect(await screen.findByText(/No identity providers/)).toBeInTheDocument();
});

test("a failed load shows the backend's message", async () => {
  serve({ "GET /api/admin/oidc-providers": [respond(500, { detail: "Database is down" })] });
  renderProviders();
  expect(await screen.findByRole("alert")).toHaveTextContent("Database is down");
  expect(screen.queryByText("Loading...")).not.toBeInTheDocument();
});

test("creating a provider sends its fields and shows it in the list", async () => {
  const user = userEvent.setup();
  serve({
    "GET /api/admin/oidc-providers": [respond(200, []), respond(200, [provider("Okta")])],
    "POST /api/admin/oidc-providers": [respond(201, provider("Okta"))],
  });
  renderProviders();
  await screen.findByText(/No identity providers/);

  await user.click(screen.getByRole("button", { name: "New provider" }));
  const dialog = screen.getByRole("dialog", { name: "New identity provider" });
  await user.type(within(dialog).getByLabelText("Provider ID"), "okta");
  await user.type(within(dialog).getByLabelText("Display name"), "Okta");
  await user.type(within(dialog).getByLabelText("Issuer URL"), "https://okta.example");
  await user.type(within(dialog).getByLabelText("Client ID"), "okta-client");
  await user.type(within(dialog).getByLabelText("Client secret"), "s3cret");
  await user.click(within(dialog).getByRole("button", { name: "Create" }));

  expect(await screen.findByRole("cell", { name: "Okta" })).toBeInTheDocument();
  expect(dialog).not.toHaveAttribute("open");
  expect(await bodyOf("POST /api/admin/oidc-providers")).toEqual({
    provider_id: "okta",
    display_name: "Okta",
    issuer_url: "https://okta.example",
    client_id: "okta-client",
    client_secret: "s3cret",
    scopes: "openid profile email",
    default_role: "user",
    is_enabled: true,
  });
});

test("a create the backend rejects shows its message in the dialog, which stays open", async () => {
  const user = userEvent.setup();
  serve({
    "GET /api/admin/oidc-providers": [respond(200, [])],
    "POST /api/admin/oidc-providers": [respond(409, { detail: "Provider ID already exists" })],
  });
  renderProviders();
  await screen.findByText(/No identity providers/);

  await user.click(screen.getByRole("button", { name: "New provider" }));
  const dialog = screen.getByRole("dialog", { name: "New identity provider" });
  for (const [label, value] of [
    ["Provider ID", "okta"],
    ["Display name", "Okta"],
    ["Issuer URL", "https://okta.example"],
    ["Client ID", "okta-client"],
    ["Client secret", "s3cret"],
  ]) {
    await user.type(within(dialog).getByLabelText(label), value);
  }
  await user.click(within(dialog).getByRole("button", { name: "Create" }));

  expect(await within(dialog).findByRole("alert")).toHaveTextContent("Provider ID already exists");
  expect(dialog).toHaveAttribute("open");
});

test("editing a provider sends only a new secret when one is typed, and refetches the list", async () => {
  const user = userEvent.setup();
  serve({
    "GET /api/admin/oidc-providers": [respond(200, [provider("Okta")]), respond(200, [provider("Okta SSO")])],
    "PATCH /api/admin/oidc-providers/okta": [respond(200, provider("Okta SSO"))],
  });
  renderProviders();
  await screen.findByRole("cell", { name: "Okta" });

  await user.click(screen.getByRole("button", { name: "Edit Okta" }));
  const dialog = screen.getByRole("dialog", { name: "Edit Okta" });
  const name = within(dialog).getByLabelText("Display name");
  await user.clear(name);
  await user.type(name, "Okta SSO");
  await user.click(within(dialog).getByRole("button", { name: "Save" }));

  expect(await screen.findByRole("cell", { name: "Okta SSO" })).toBeInTheDocument();
  const patch = (await bodyOf("PATCH /api/admin/oidc-providers/okta")) as Record<string, unknown>;
  expect(patch.display_name).toBe("Okta SSO");
  expect(patch).not.toHaveProperty("client_secret");
});

test("a new client secret is sent with the edit", async () => {
  const user = userEvent.setup();
  serve({
    "GET /api/admin/oidc-providers": [respond(200, [provider("Okta")])],
    "PATCH /api/admin/oidc-providers/okta": [respond(200, provider("Okta"))],
  });
  renderProviders();
  await screen.findByRole("cell", { name: "Okta" });

  await user.click(screen.getByRole("button", { name: "Edit Okta" }));
  const dialog = screen.getByRole("dialog", { name: "Edit Okta" });
  await user.type(within(dialog).getByLabelText("New client secret (optional)"), "rotated");
  await user.click(within(dialog).getByRole("button", { name: "Save" }));

  await vi.waitFor(() => expect(dialog).not.toHaveAttribute("open"));
  const patch = (await bodyOf("PATCH /api/admin/oidc-providers/okta")) as Record<string, unknown>;
  expect(patch.client_secret).toBe("rotated");
});

test("an edit the backend rejects shows its message in the dialog, which stays open", async () => {
  const user = userEvent.setup();
  serve({
    "GET /api/admin/oidc-providers": [respond(200, [provider("Okta")])],
    "PATCH /api/admin/oidc-providers/okta": [respond(422, { detail: "Issuer URL is not reachable" })],
  });
  renderProviders();
  await screen.findByRole("cell", { name: "Okta" });

  await user.click(screen.getByRole("button", { name: "Edit Okta" }));
  const dialog = screen.getByRole("dialog", { name: "Edit Okta" });
  await user.click(within(dialog).getByRole("button", { name: "Save" }));

  expect(await within(dialog).findByRole("alert")).toHaveTextContent("Issuer URL is not reachable");
  expect(dialog).toHaveAttribute("open");
});

test("deleting a provider asks first, then sends the request and refetches the list", async () => {
  const user = userEvent.setup();
  const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
  serve({
    "GET /api/admin/oidc-providers": [respond(200, [provider("Okta")]), respond(200, [])],
    "DELETE /api/admin/oidc-providers/okta": [respond(204)],
  });
  renderProviders();
  await screen.findByRole("cell", { name: "Okta" });

  // Cancelled: nothing is sent
  await user.click(screen.getByRole("button", { name: "Delete Okta" }));
  expect(requests()).toEqual(["GET /api/admin/oidc-providers"]);

  await user.click(screen.getByRole("button", { name: "Delete Okta" }));
  expect(await screen.findByText(/No identity providers/)).toBeInTheDocument();
  expect(confirm).toHaveBeenCalledTimes(2);
  expect(requests()).toEqual([
    "GET /api/admin/oidc-providers",
    "DELETE /api/admin/oidc-providers/okta",
    "GET /api/admin/oidc-providers",
  ]);
});

test("a failed delete shows its message and keeps the list", async () => {
  const user = userEvent.setup();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  serve({
    "GET /api/admin/oidc-providers": [respond(200, [provider("Okta")])],
    "DELETE /api/admin/oidc-providers/okta": [respond(409, { detail: "Users still sign in with Okta" })],
  });
  renderProviders();
  await screen.findByRole("cell", { name: "Okta" });

  await user.click(screen.getByRole("button", { name: "Delete Okta" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Users still sign in with Okta");
  expect(screen.getByRole("cell", { name: "Okta" })).toBeInTheDocument();
});
