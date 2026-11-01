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

/* An artifact card in the Artifacts tab opens a UQ notebook's baked report, and any
 * other artifact's raw content. Only the chat store and the API client are stubbed. */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { ArtifactMeta } from "@/lib/api/types";
import type { ChatItem, ChatState } from "@/lib/store/chat";
import { StatusPanel } from "./StatusPanel.tsx";

const mocks = vi.hoisted(() => ({
  state: { items: [], awaiting: false, conversationId: null } as unknown as ChatState,
}));
vi.mock("@/lib/store/chat", () => ({ useChatState: () => mocks.state }));
vi.mock("@/lib/api/client", () => ({
  api: {
    artifactContentUrl: (id: string) => `/api/artifacts/${id}/content`,
    artifactReportUrl: (id: string) => `/api/artifacts/${id}/report`,
  },
}));

function artifact(over: Partial<ArtifactMeta> & { artifact_id: string; name: string }): ArtifactMeta {
  return {
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

test("a notebook with a baked report opens the report; other artifacts open their content", async () => {
  const user = userEvent.setup();
  const answer: ChatItem = {
    id: "a-1",
    kind: "assistant",
    text: "done",
    artifacts: [
      artifact({ artifact_id: "uq-7", name: "uq_bank_worth.ipynb", render_hint: "uq", has_report: true }),
      artifact({ artifact_id: "nb-2", name: "raw.ipynb", render_hint: "uq", has_report: false }),
      artifact({ artifact_id: "tbl-1", name: "samples.csv", render_hint: "table" }),
    ],
    recommendedMaterials: [],
    followUpSuggestions: [],
  };
  mocks.state = { ...mocks.state, items: [answer] };
  render(<StatusPanel collapsed={false} onCollapse={() => {}} onExpand={() => {}} />);
  await user.click(screen.getByRole("tab", { name: /Artifacts/ }));

  const card = (name: string) => screen.getByText(name).closest("a");
  expect(card("uq_bank_worth.ipynb")).toHaveAttribute("href", "/api/artifacts/uq-7/report");
  expect(card("raw.ipynb")).toHaveAttribute("href", "/api/artifacts/nb-2/content");
  expect(card("samples.csv")).toHaveAttribute("href", "/api/artifacts/tbl-1/content");
  expect(card("uq_bank_worth.ipynb")).toHaveAttribute("target", "_blank");
});
