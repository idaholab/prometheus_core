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

/* The pages LayoutApp renders around the outlet: Home owns the status rail
 * state, Admin owns its sub-tab, and the error page offers a reload. Their
 * children are stand-ins, so this checks the wiring, not the screens. */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { expect, test, vi } from "vitest";

vi.mock("@/features/chat", () => ({ Chat: () => <p>Chat</p>, useChatState: () => ({ items: [] }) }));
vi.mock("@/features/admin/AdminUsers", () => ({ AdminUsers: () => <p>Users panel</p> }));
vi.mock("@/features/admin/AdminSigningKeys", () => ({ AdminSigningKeys: () => <p>Signing Keys panel</p> }));
vi.mock("@/features/admin/AdminOidcProviders", () => ({ AdminOidcProviders: () => <p>Identity Providers panel</p> }));

const { PageHome } = await import("./PageHome.tsx");
const { PageAdmin } = await import("./PageAdmin.tsx");
const { PageError } = await import("./PageError.tsx");

test("Home collapses the status rail and expands it again", async () => {
  const user = userEvent.setup();
  render(<PageHome />);
  const rail = screen.getByRole("button", { name: "Collapse status panel" }).closest("aside");

  expect(rail).not.toHaveClass("w-16");
  await user.click(screen.getByRole("button", { name: "Collapse status panel" }));
  expect(rail).toHaveClass("w-16");
  await user.click(screen.getByRole("button", { name: "Expand status panel" }));
  expect(rail).not.toHaveClass("w-16");
});

test("Admin opens on Users and switches sub-tabs", async () => {
  const user = userEvent.setup();
  render(<PageAdmin />);

  expect(screen.getByText("Users panel")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Signing Keys" }));
  expect(screen.getByText("Signing Keys panel")).toBeInTheDocument();
  expect(screen.queryByText("Users panel")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Identity Providers" }));
  expect(screen.getByText("Identity Providers panel")).toBeInTheDocument();
});

function renderError(error: unknown) {
  vi.spyOn(console, "error").mockImplementation(() => {});
  const router = createMemoryRouter(
    [
      {
        path: "/",
        loader: () => {
          throw error;
        },
        element: null,
        errorElement: <PageError />,
      },
    ],
    { initialEntries: ["/"] },
  );
  render(<RouterProvider router={router} />);
}

test("the error page names an HTTP error and reloads on request", async () => {
  const user = userEvent.setup();
  const reload = vi.fn();
  vi.stubGlobal("location", { ...window.location, reload });
  renderError(new Response(null, { status: 503, statusText: "Service Unavailable" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("(503 Service Unavailable)");
  await user.click(screen.getByRole("button", { name: "Reload" }));
  expect(reload).toHaveBeenCalledOnce();
  vi.unstubAllGlobals();
});

test("the error page shows no detail for a plain exception", async () => {
  renderError(new Error("boom"));
  expect(await screen.findByRole("heading", { name: "Something went wrong" })).toBeVisible();
  expect(screen.getByRole("alert")).not.toHaveTextContent("(");
});
