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

/* The status panel's Artifacts tab: opening an artifact in the panel, and a new
 * panel-only artifact (`display: "panel"`) opening itself. The chat store is
 * mocked; the artifact viewers are stubbed so each test sees which artifact the
 * panel chose to show. */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import type { ArtifactMeta } from "@/lib/api/types";
import type { ChatState } from "@/features/chat";
import { StatusPanel } from "./StatusPanel.tsx";

type PanelState = Pick<ChatState, "items" | "resumingConversationId">;

const mocks = vi.hoisted(() => ({ state: {} as PanelState }));

vi.mock("@/features/chat", () => ({ useChatState: () => mocks.state }));
vi.mock("@/features/artifacts", () => ({
  artifactToElement: (a: ArtifactMeta) => ({ id: a.artifact_id, name: a.name }),
  isPanelOnly: (a: ArtifactMeta) => a.display === "panel",
  ElementList: ({ elements }: { elements: { id: string; name: string }[] }) => (
    <div data-testid="viewer">{elements.map((e) => e.name).join(",")}</div>
  ),
}));
vi.mock("@/lib/api/client", () => ({
  api: { artifactContentUrl: (id: string) => `/api/artifacts/${id}/content` },
}));

function artifact(id: string, overrides: Partial<ArtifactMeta> = {}): ArtifactMeta {
  return { artifact_id: id, name: `${id}.txt`, description: "", tags: [], render_hint: "code", ...overrides };
}

function stateWith(artifacts: ArtifactMeta[], resumingConversationId: string | null = null): PanelState {
  return {
    items: [
      { kind: "assistant", id: "a1", text: "", artifacts, recommendedMaterials: [], followUpSuggestions: [] },
    ],
    resumingConversationId,
  };
}

const onCollapse = vi.fn();
const onExpand = vi.fn();

function renderPanel(state: PanelState, collapsed = false) {
  mocks.state = state;
  const view = render(<StatusPanel collapsed={collapsed} onCollapse={onCollapse} onExpand={onExpand} />);
  const update = (next: PanelState, nextCollapsed = collapsed) => {
    mocks.state = next;
    view.rerender(<StatusPanel collapsed={nextCollapsed} onCollapse={onCollapse} onExpand={onExpand} />);
  };
  return { ...view, update };
}

beforeEach(() => {
  onCollapse.mockReset();
  onExpand.mockReset();
});

describe("opening an artifact from the Artifacts tab", () => {
  test("a viewable artifact opens in the panel, and Back returns to the list", async () => {
    const user = userEvent.setup();
    renderPanel(stateWith([artifact("input")]));

    await user.click(screen.getByRole("tab", { name: /Artifacts/ }));
    await user.click(screen.getByText("input.txt"));
    expect(screen.getByTestId("viewer")).toHaveTextContent("input.txt");
    expect(screen.getByRole("link", { name: "Open input.txt in a new tab" })).toHaveAttribute(
      "href",
      "/api/artifacts/input/content",
    );

    await user.click(screen.getByRole("button", { name: "Back to artifacts" }));
    expect(screen.queryByTestId("viewer")).not.toBeInTheDocument();
    expect(screen.getByText("input.txt")).toBeInTheDocument();
  });

  test("an artifact with no panel viewer stays a link to the raw file", async () => {
    const user = userEvent.setup();
    renderPanel(stateWith([artifact("mesh", { render_hint: "mesh" })]));

    await user.click(screen.getByRole("tab", { name: /Artifacts/ }));
    const card = screen.getByRole("link", { name: /mesh\.txt/ });
    expect(card).toHaveAttribute("href", "/api/artifacts/mesh/content");
    await user.click(card);
    expect(screen.queryByTestId("viewer")).not.toBeInTheDocument();
  });
});

describe("a new panel-only artifact opens itself", () => {
  test("a panel artifact that arrives live opens on the Artifacts tab", () => {
    const { update } = renderPanel(stateWith([]));
    update(stateWith([artifact("plan"), artifact("current", { display: "panel" })]));

    expect(screen.getByRole("tab", { name: /Artifacts/ })).toHaveClass("tab-active");
    expect(screen.getByTestId("viewer")).toHaveTextContent("current.txt");
    expect(onExpand).not.toHaveBeenCalled();
  });

  test("the newest of several arrivals is the one opened", () => {
    const { update } = renderPanel(stateWith([]));
    update(stateWith([artifact("first", { display: "panel" }), artifact("second", { display: "panel" })]));
    expect(screen.getByTestId("viewer")).toHaveTextContent("second.txt");
  });

  test("a collapsed panel expands for it", () => {
    const { update } = renderPanel(stateWith([]), true);
    update(stateWith([artifact("current", { display: "panel" })]), true);
    expect(onExpand).toHaveBeenCalledTimes(1);
  });

  test("inline artifacts and panel artifacts with no panel viewer don't open", () => {
    const { update } = renderPanel(stateWith([]));
    update(stateWith([artifact("log"), artifact("mesh", { display: "panel", render_hint: "mesh" })]));
    expect(screen.queryByTestId("viewer")).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Active Jobs/ })).toHaveClass("tab-active");
  });

  test("artifacts already there when the panel mounts don't open", () => {
    renderPanel(stateWith([artifact("current", { display: "panel" })]));
    expect(screen.queryByTestId("viewer")).not.toBeInTheDocument();
  });

  test("artifacts loaded with a resumed conversation don't open", () => {
    const { update } = renderPanel(stateWith([]));
    // A sidebar switch (or recovering after a reload): the transcript lands while
    // the resume is still in flight, then the resume finishes.
    update(stateWith([artifact("old", { display: "panel" })], "conv-2"));
    update(stateWith([artifact("old", { display: "panel" })]));
    expect(screen.queryByTestId("viewer")).not.toBeInTheDocument();

    // A panel artifact that arrives after that still opens.
    update(stateWith([artifact("old", { display: "panel" }), artifact("new", { display: "panel" })]));
    expect(screen.getByTestId("viewer")).toHaveTextContent("new.txt");
  });
});
