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

/* The Artifacts tab folds per-sample plumbing (UQ sample configs, ZDOs, failure
 * logs) into one closed list under the results, and counts only the results.
 * Only the chat store and the API client are stubbed. */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import type { ArtifactMeta } from "@/lib/api/types";
import type { ChatItem, ChatState } from "@/lib/store/chat";
import { StatusPanel } from "./StatusPanel.tsx";

const mocks = vi.hoisted(() => ({
  state: { items: [], awaiting: false, conversationId: null } as unknown as ChatState,
}));
vi.mock("@/lib/store/chat", () => ({ useChatState: () => mocks.state }));
vi.mock("@/lib/api/client", () => ({
  api: { artifactContentUrl: (id: string) => `/api/artifacts/${id}/content` },
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

const NOTEBOOK = artifact({ artifact_id: "uq-7", name: "uq_bank_worth.ipynb", tags: ["uq", "notebook"] });
const TABLE = artifact({ artifact_id: "tbl-1", name: "samples.csv", render_hint: "table" });
const SAMPLE_CFG = artifact({ artifact_id: "cfg-1", name: "sample_001.yaml", tags: ["uq-sample"] });
const SAMPLE_ZDO = artifact({ artifact_id: "zdo-1", name: "sample_001.zdo", tags: ["zdo"] });

function renderPanel(collapsed = false) {
  return render(<StatusPanel collapsed={collapsed} onCollapse={() => {}} onExpand={() => {}} />);
}

beforeEach(() => {
  mocks.state = { items: [], awaiting: false, conversationId: null } as unknown as ChatState;
});

test("the Artifacts tab counts and lists results, and folds per-sample files", async () => {
  const user = userEvent.setup();
  mocks.state = {
    ...mocks.state,
    items: [
      { id: "u", kind: "user", text: "run UQ" },
      answer([NOTEBOOK, SAMPLE_CFG]),
      answer([NOTEBOOK, TABLE, SAMPLE_ZDO]), // the notebook again, deduped by id
    ],
  };
  renderPanel();

  await user.click(screen.getByRole("tab", { name: "Artifacts (2)" }));

  expect(screen.getByRole("link", { name: /uq_bank_worth\.ipynb/ })).toHaveAttribute(
    "href",
    "/api/artifacts/uq-7/content",
  );
  expect(screen.getByRole("link", { name: /samples\.csv/ })).toHaveAttribute("href", "/api/artifacts/tbl-1/content");

  const summary = screen.getByText("2 per-sample files (configs, ZDOs, logs)");
  const perSample = summary.closest("details")!;
  expect(perSample).not.toHaveAttribute("open");
  await user.click(summary);
  expect(perSample).toHaveAttribute("open");
  expect(within(perSample).getByRole("link", { name: "sample_001.yaml" })).toHaveAttribute(
    "href",
    "/api/artifacts/cfg-1/content",
  );
  expect(within(perSample).getByRole("link", { name: "sample_001.zdo" })).toBeInTheDocument();
  // Per-sample files are not repeated as cards in the main list.
  expect(screen.getAllByRole("link", { name: /sample_001\.yaml/ })).toHaveLength(1);
});

test("results alone show no per-sample group", async () => {
  const user = userEvent.setup();
  mocks.state = { ...mocks.state, items: [answer([TABLE])] };
  renderPanel();
  await user.click(screen.getByRole("tab", { name: "Artifacts (1)" }));
  expect(screen.getByRole("link", { name: /samples\.csv/ })).toBeInTheDocument();
  expect(screen.queryByText(/per-sample files/)).not.toBeInTheDocument();
});

test("the collapsed rail counts only results", () => {
  mocks.state = { ...mocks.state, items: [answer([TABLE, SAMPLE_CFG, SAMPLE_ZDO])] };
  renderPanel(true);
  expect(screen.getByRole("button", { name: "Artifacts (1)" })).toBeInTheDocument();
});
