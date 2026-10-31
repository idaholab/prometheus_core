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

/* The status rail on Home: the Agents tab (the Live Agents Arena) is the default, the
 * tabs switch panels, and the collapsed icon rail expands straight to the tab clicked.
 * The tabs' own panels render for real; only the chat store and the Task Graph read are stubbed. */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, expect, test, vi } from "vitest";
import type { ChatState } from "@/lib/store/chat";
import { StatusPanel } from "./StatusPanel.tsx";

const mocks = vi.hoisted(() => ({
  state: { items: [], awaiting: false, conversationId: null } as unknown as ChatState,
}));
vi.mock("@/lib/store/chat", () => ({ useChatState: () => mocks.state }));
vi.mock("@/lib/api/client", () => ({
  api: {
    getConversationTasks: async () => ({ available: true, conversation_id: "c", tasks: [] }),
    artifactContentUrl: (id: string) => `/api/artifacts/${id}/content`,
  },
}));

/** StatusPanel with its collapsed flag held in state, as Home holds it. */
function Home({ startCollapsed = false }: { startCollapsed?: boolean }) {
  const [collapsed, setCollapsed] = useState(startCollapsed);
  return <StatusPanel collapsed={collapsed} onCollapse={() => setCollapsed(true)} onExpand={() => setCollapsed(false)} />;
}

beforeEach(() => {
  mocks.state = { items: [], awaiting: false, conversationId: "c" } as unknown as ChatState;
});

const tab = (name: string) => screen.getByRole("tab", { name });

test("the Agents tab is the default, titled Live Agents Arena, and the tabs switch panels", async () => {
  const user = userEvent.setup();
  render(<Home />);

  expect(tab("Agents")).toHaveClass("tab-active");
  expect(tab("Agents")).toHaveAttribute("title", "Live Agents Arena");
  expect(screen.getByText("No Agents Yet")).toBeInTheDocument();

  await user.click(tab("Active Jobs"));
  expect(tab("Active Jobs")).toHaveClass("tab-active");
  expect(tab("Agents")).not.toHaveClass("tab-active");
  expect(await screen.findByText("No Active Jobs")).toBeInTheDocument();

  await user.click(tab("Artifacts"));
  expect(tab("Artifacts")).toHaveClass("tab-active");
  expect(screen.getByText("No Artifacts Yet")).toBeInTheDocument();

  await user.click(tab("Agents"));
  expect(screen.getByText("No Agents Yet")).toBeInTheDocument();
});

test("exactly the active tab is aria-selected", async () => {
  const user = userEvent.setup();
  render(<Home />);
  const selected = () => screen.getAllByRole("tab", { selected: true }).map((t) => t.textContent);

  expect(selected()).toEqual(["Agents"]);
  await user.click(tab("Active Jobs"));
  expect(selected()).toEqual(["Active Jobs"]);
  expect(tab("Agents")).toHaveAttribute("aria-selected", "false");
  await user.click(tab("Artifacts"));
  expect(selected()).toEqual(["Artifacts"]);
});

test("collapsing shows the icon rail, and its toggle expands back to the same tab", async () => {
  const user = userEvent.setup();
  render(<Home />);
  await user.click(tab("Active Jobs"));

  await user.click(screen.getByRole("button", { name: "Collapse status panel" }));
  expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Active Jobs" })).toHaveClass("text-primary");
  expect(screen.getByRole("button", { name: "Live Agents Arena" })).not.toHaveClass("text-primary");
  expect(screen.getByRole("button", { name: "Artifacts" })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Expand status panel" }));
  expect(tab("Active Jobs")).toHaveClass("tab-active");
});

test("clicking a rail icon expands the panel straight to that tab", async () => {
  const user = userEvent.setup();
  render(<Home startCollapsed />);

  expect(screen.getByRole("button", { name: "Live Agents Arena" })).toHaveClass("text-primary");
  await user.click(screen.getByRole("button", { name: "Active Jobs" }));
  expect(tab("Active Jobs")).toHaveClass("tab-active");

  await user.click(screen.getByRole("button", { name: "Collapse status panel" }));
  await user.click(screen.getByRole("button", { name: "Live Agents Arena" }));
  expect(tab("Agents")).toHaveClass("tab-active");
  expect(screen.getByText("No Agents Yet")).toBeInTheDocument();
});
