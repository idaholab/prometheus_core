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
  api: { artifactContentUrl: (a: { artifact_id: string }) => `/api/artifacts/${a.artifact_id}/content` },
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
const onViewerOpenChange = vi.fn();

function renderPanel(state: PanelState, collapsed = false) {
  const panel = (isCollapsed: boolean) => (
    <StatusPanel
      collapsed={isCollapsed}
      onCollapse={onCollapse}
      onExpand={onExpand}
      onViewerOpenChange={onViewerOpenChange}
    />
  );
  mocks.state = state;
  const view = render(panel(collapsed));
  const update = (next: PanelState, nextCollapsed = collapsed) => {
    mocks.state = next;
    view.rerender(panel(nextCollapsed));
  };
  return { ...view, update };
}

beforeEach(() => {
  onCollapse.mockReset();
  onExpand.mockReset();
  onViewerOpenChange.mockReset();
});

describe("the Artifacts tab list", () => {
  test("lists each artifact once across turns, with its description, skipping other items", async () => {
    const user = userEvent.setup();
    const shared = artifact("shared", { description: "Verified MOOSE input" });
    renderPanel({
      items: [
        { kind: "user", id: "u1", text: "run it" },
        {
          kind: "assistant",
          id: "a1",
          text: "",
          artifacts: [shared],
          recommendedMaterials: [],
          followUpSuggestions: [],
        },
        {
          kind: "assistant",
          id: "a2",
          text: "",
          artifacts: [shared, artifact("log")],
          recommendedMaterials: [],
          followUpSuggestions: [],
        },
      ] as ChatState["items"],
      resumingConversationId: null,
    });

    await user.click(screen.getByRole("tab", { name: "Artifacts (2)" }));
    expect(screen.getAllByText("shared.txt")).toHaveLength(1);
    expect(screen.getByText("Verified MOOSE input")).toBeInTheDocument();
  });

  test("lists artifacts from turns that paused at a form, and skips a form with none", async () => {
    const user = userEvent.setup();
    const report = artifact("report");
    renderPanel({
      items: [
        {
          kind: "assistant",
          id: "a1",
          text: "",
          artifacts: [report],
          recommendedMaterials: [],
          followUpSuggestions: [],
        },
        // A form whose turn published nothing.
        {
          kind: "needs_info",
          id: "ni-1",
          turnId: "t1",
          message: "Gate 1: approve?",
          fields: [],
          artifacts: [],
          submitted: true,
        },
        {
          kind: "needs_info",
          id: "ni-2",
          turnId: "t2",
          message: "Gate 2: approve?",
          fields: [],
          artifacts: [artifact("criterion_status"), report],
          submitted: false,
        },
      ] as ChatState["items"],
      resumingConversationId: null,
    });

    await user.click(screen.getByRole("tab", { name: "Artifacts (2)" }));
    expect(screen.getAllByText("report.txt")).toHaveLength(1);
    expect(screen.getByText("criterion_status.txt")).toBeInTheDocument();
  });
});

describe("opening an artifact from the Artifacts tab", () => {
  test("a viewable artifact opens in the panel, and Back returns to the list", async () => {
    const user = userEvent.setup();
    renderPanel(stateWith([artifact("input")]));

    await user.click(screen.getByRole("tab", { name: /Artifacts/ }));
    await user.click(screen.getByText("input.txt"));
    expect(screen.getByTestId("viewer")).toHaveTextContent("input.txt");
    // The viewer owns the name and actions; the panel adds no title of its own.
    expect(screen.getAllByText("input.txt")).toHaveLength(1);
    expect(onViewerOpenChange).toHaveBeenLastCalledWith(true);

    await user.click(screen.getByRole("button", { name: "All artifacts" }));
    expect(screen.queryByTestId("viewer")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "All artifacts" })).not.toBeInTheDocument();
    expect(screen.getByText("input.txt")).toBeInTheDocument();
    expect(onViewerOpenChange).toHaveBeenLastCalledWith(false);
  });

  test("clicking the Artifacts tab from an open artifact returns to the list", async () => {
    const user = userEvent.setup();
    renderPanel(stateWith([artifact("input"), artifact("log")]));
    await user.click(screen.getByRole("tab", { name: /Artifacts/ }));
    await user.click(screen.getByText("input.txt"));
    expect(screen.getByTestId("viewer")).toHaveTextContent("input.txt");

    await user.click(screen.getByRole("tab", { name: /Artifacts/ }));
    expect(screen.queryByTestId("viewer")).not.toBeInTheDocument();
    await user.click(screen.getByText("log.txt"));
    expect(screen.getByTestId("viewer")).toHaveTextContent("log.txt");
  });

  test("the layout is told the viewer closed when the panel collapses or the tab changes", async () => {
    const user = userEvent.setup();
    const { update } = renderPanel(stateWith([artifact("input")]));
    await user.click(screen.getByRole("tab", { name: /Artifacts/ }));
    await user.click(screen.getByText("input.txt"));
    expect(onViewerOpenChange).toHaveBeenLastCalledWith(true);

    update(stateWith([artifact("input")]), true);
    expect(onViewerOpenChange).toHaveBeenLastCalledWith(false);
    update(stateWith([artifact("input")]), false);
    expect(onViewerOpenChange).toHaveBeenLastCalledWith(true);

    await user.click(screen.getByRole("tab", { name: "Active Jobs" }));
    expect(onViewerOpenChange).toHaveBeenLastCalledWith(false);
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

describe("tabs and the collapsed rail", () => {
  test("the tab bar switches between Active Jobs and Artifacts", async () => {
    const user = userEvent.setup();
    renderPanel(stateWith([]));
    expect(screen.getByText("No Active Jobs")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Artifacts" }));
    expect(screen.getByText("No Artifacts Yet")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Active Jobs" }));
    expect(screen.getByText("No Active Jobs")).toBeInTheDocument();
  });

  test("the collapse button collapses the panel", async () => {
    const user = userEvent.setup();
    renderPanel(stateWith([]));
    await user.click(screen.getByRole("button", { name: "Collapse status panel" }));
    expect(onCollapse).toHaveBeenCalledTimes(1);
  });

  test("a rail icon expands the panel straight to its tab", async () => {
    const user = userEvent.setup();
    const { update } = renderPanel(stateWith([artifact("a"), artifact("b")]), true);

    await user.click(screen.getByRole("button", { name: "Artifacts (2)" }));
    expect(onExpand).toHaveBeenCalledTimes(1);
    update(stateWith([artifact("a"), artifact("b")]), false);
    expect(screen.getByRole("tab", { name: /Artifacts/ })).toHaveClass("tab-active");

    update(stateWith([artifact("a"), artifact("b")]), true);
    await user.click(screen.getByRole("button", { name: "Active Jobs" }));
    expect(onExpand).toHaveBeenCalledTimes(2);
    update(stateWith([artifact("a"), artifact("b")]), false);
    expect(screen.getByRole("tab", { name: "Active Jobs" })).toHaveClass("tab-active");
  });

  test("the rail's expand button and an empty Artifacts label", async () => {
    const user = userEvent.setup();
    renderPanel(stateWith([]), true);
    expect(screen.getByRole("button", { name: "Artifacts" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Expand status panel" }));
    expect(onExpand).toHaveBeenCalledTimes(1);
  });
});
