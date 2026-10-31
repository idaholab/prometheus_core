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


/* The status rail on Home: tab switching between the Live Agents Arena, Active Jobs and
 * Artifacts, and the collapsed icon rail that expands straight to the tab clicked. The
 * tabs' own panels render for real; only the chat store and the Task Graph read are stubbed. */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, expect, test, vi } from "vitest";
import type { ArtifactMeta } from "@/lib/api/types";
import type { ChatItem, ChatState } from "@/lib/store/chat";
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

function artifact(over: Partial<ArtifactMeta> & { artifact_id: string }): ArtifactMeta {
  return {
    name: over.artifact_id,
    mime_type: "application/json",
    json_type: null,
    description: "",
    uri: null,
    tags: [],
    json_body: null,
    render_hint: "json",
    citation: null,
    producer_agent_id: null,
    created_at: null,
    ...over,
  } as ArtifactMeta;
}
const answer = (artifacts: ArtifactMeta[]): ChatItem => ({
  id: `a-${artifacts.map((a) => a.artifact_id).join("-")}`,
  kind: "assistant",
  text: "done",
  artifacts,
  recommendedMaterials: [],
  followUpSuggestions: [],
});

const REPORT = artifact({
  artifact_id: "uq-7",
  name: "uq_bank_worth.ipynb",
  render_hint: "uq",
  description: "Forward UQ on control bank worth",
  tags: ["uq", "notebook"],
});
const TABLE = artifact({ artifact_id: "tbl-1", name: "samples.csv", render_hint: "table" });
const SAMPLE_CFG = artifact({ artifact_id: "cfg-1", name: "sample_001.yaml", tags: ["uq-sample"] });
const SAMPLE_ZDO = artifact({ artifact_id: "zdo-1", name: "sample_001.zdo", tags: ["zdo"] });

/** StatusPanel with its collapsed flag held in state, as Home holds it. */
function Home({ startCollapsed = false }: { startCollapsed?: boolean }) {
  const [collapsed, setCollapsed] = useState(startCollapsed);
  return <StatusPanel collapsed={collapsed} onCollapse={() => setCollapsed(true)} onExpand={() => setCollapsed(false)} />;
}

beforeEach(() => {
  mocks.state = { items: [], awaiting: false, conversationId: null } as unknown as ChatState;
});

test("the Live Agents Arena is the default tab, and the tabs switch panels", async () => {
  const user = userEvent.setup();
  render(<Home />);

  expect(screen.getByRole("tab", { name: "Live Agents Arena" })).toHaveClass("tab-active");
  expect(screen.getByText("No Agents Yet")).toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: "Active Jobs" }));
  expect(screen.getByRole("tab", { name: "Active Jobs" })).toHaveClass("tab-active");
  expect(screen.getByRole("tab", { name: "Live Agents Arena" })).not.toHaveClass("tab-active");
  expect(await screen.findByText("No Active Jobs")).toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: "Artifacts" }));
  expect(screen.getByRole("tab", { name: "Artifacts" })).toHaveClass("tab-active");
  expect(screen.getByText("No Artifacts Yet")).toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: "Live Agents Arena" }));
  expect(screen.getByText("No Agents Yet")).toBeInTheDocument();
});

test("the Artifacts tab counts and lists results, opens a UQ notebook as its report, and folds per-sample files", async () => {
  const user = userEvent.setup();
  mocks.state = {
    ...mocks.state,
    items: [
      { id: "u", kind: "user", text: "run UQ" },
      answer([REPORT, SAMPLE_CFG]),
      answer([REPORT, TABLE, SAMPLE_ZDO]), // the report again, deduped by id
    ],
  };
  render(<Home />);

  await user.click(screen.getByRole("tab", { name: "Artifacts (2)" }));

  const report = screen.getByRole("link", { name: /uq_bank_worth\.ipynb/ });
  expect(report).toHaveAttribute("href", "/notebook/render/uq-7");
  expect(report).toHaveAttribute("target", "_blank");
  expect(within(report).getByText("Forward UQ on control bank worth")).toBeInTheDocument();
  expect(within(report).getByText("uq")).toBeInTheDocument();

  const table = screen.getByRole("link", { name: /samples\.csv/ });
  expect(table).toHaveAttribute("href", "/api/artifacts/tbl-1/content");
  expect(table.querySelector("p")).toBeNull(); // no description line

  const perSample = screen.getByText("2 per-sample files (configs, ZDOs, logs)").closest("details")!;
  expect(perSample).not.toHaveAttribute("open");
  await user.click(screen.getByText("2 per-sample files (configs, ZDOs, logs)"));
  expect(perSample).toHaveAttribute("open");
  expect(within(perSample).getByRole("link", { name: "sample_001.yaml" })).toHaveAttribute(
    "href",
    "/api/artifacts/cfg-1/content",
  );
  expect(within(perSample).getByRole("link", { name: "sample_001.zdo" })).toBeInTheDocument();
});

test("results alone show no per-sample group", async () => {
  const user = userEvent.setup();
  mocks.state = { ...mocks.state, items: [answer([TABLE])] };
  render(<Home />);
  await user.click(screen.getByRole("tab", { name: "Artifacts (1)" }));
  expect(screen.getByRole("link", { name: /samples\.csv/ })).toBeInTheDocument();
  expect(screen.queryByText(/per-sample files/)).not.toBeInTheDocument();
});

test("collapsing shows the icon rail, and its toggle expands back to the same tab", async () => {
  const user = userEvent.setup();
  render(<Home />);
  await user.click(screen.getByRole("tab", { name: "Active Jobs" }));

  await user.click(screen.getByRole("button", { name: "Collapse status panel" }));
  expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Active Jobs" })).toHaveClass("text-primary");
  expect(screen.getByRole("button", { name: "Live Agents Arena" })).not.toHaveClass("text-primary");
  expect(screen.getByRole("button", { name: "Artifacts" })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Expand status panel" }));
  expect(screen.getByRole("tab", { name: "Active Jobs" })).toHaveClass("tab-active");
});

test("clicking a rail icon expands the panel straight to that tab", async () => {
  const user = userEvent.setup();
  mocks.state = { ...mocks.state, items: [answer([REPORT])] };
  render(<Home startCollapsed />);

  expect(screen.getByRole("button", { name: "Artifacts (1)" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Artifacts (1)" }));
  expect(screen.getByRole("tab", { name: "Artifacts (1)" })).toHaveClass("tab-active");
  expect(screen.getByRole("link", { name: /uq_bank_worth\.ipynb/ })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Collapse status panel" }));
  await user.click(screen.getByRole("button", { name: "Active Jobs" }));
  expect(screen.getByRole("tab", { name: "Active Jobs" })).toHaveClass("tab-active");

  await user.click(screen.getByRole("button", { name: "Collapse status panel" }));
  await user.click(screen.getByRole("button", { name: "Live Agents Arena" }));
  expect(screen.getByRole("tab", { name: "Live Agents Arena" })).toHaveClass("tab-active");
});
