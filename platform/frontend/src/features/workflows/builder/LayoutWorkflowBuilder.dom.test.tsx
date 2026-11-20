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

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { BuilderMode } from "@/features/workflows/builderMode";
import {
  BUILDER_NODES,
  BUILDER_WIRES,
  INSPECTED_NODE,
  RUN_NODES,
  SKILL_GROUPS,
  TWEAKED_STEP,
  UNSAVED_CHANGES,
  VERSION_DETAILS,
  WORKFLOW_VERSIONS,
} from "./builderPlaceholders.ts";
import { LayoutWorkflowBuilder } from "./LayoutWorkflowBuilder.tsx";

// React Flow watches its container for resizes, and jsdom has no modal
// dialogs, so stand in for both: showModal and close just set the open attribute.
beforeEach(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});
afterEach(() => vi.unstubAllGlobals());

/** The Builder with its mode held as PageWorkflows holds it. */
function Builder({ initial, unsavedChanges }: { initial: BuilderMode; unsavedChanges?: string }) {
  const [mode, setMode] = useState(initial);
  return (
    <LayoutWorkflowBuilder
      name="Comprehensive Material Analysis"
      mode={mode}
      onModeChange={setMode}
      version="v1.2.0"
      nextVersion="v1.3.0"
      skillGroups={SKILL_GROUPS}
      versions={WORKFLOW_VERSIONS}
      versionDetails={VERSION_DETAILS}
      nodes={mode === "run" ? RUN_NODES : BUILDER_NODES}
      wires={BUILDER_WIRES}
      inspected={INSPECTED_NODE}
      tweaked={TWEAKED_STEP}
      unsavedChanges={unsavedChanges}
    />
  );
}

const badge = () => screen.getByRole("button", { name: /Changing:/ });
async function pickMode(user: ReturnType<typeof userEvent.setup>, name: RegExp) {
  await user.click(badge());
  await user.click(screen.getByRole("menuitemradio", { name }));
}

test("changing this run locks the library, drops the wiring and shows the Tweak Step inspector", () => {
  render(<Builder initial="run" />);

  const library = screen.getByRole("complementary", { name: "Skill library" });
  expect(library).toHaveTextContent("Adding, wiring and removing steps changes the template.");
  // inert takes the skills out of the tab order and the accessibility tree.
  // jsdom doesn't implement it, so check it's set; the browser check covers the rest.
  expect(within(library).getByText("Corrosion").closest("[inert]")).not.toBeNull();
  expect(within(library).getByRole("searchbox", { name: "Search skills" }).closest("[inert]")).not.toBeNull();

  const canvas = screen.getByRole("region", { name: "Canvas" });
  expect(within(canvas).queryByText("drop to connect →")).not.toBeInTheDocument();

  const inspector = screen.getByRole("complementary", { name: "Node inspector" });
  expect(within(inspector).getByText("Tweak Step")).toBeInTheDocument();
  expect(within(inspector).getByRole("combobox", { name: "Agent" })).toHaveValue("Corrosion Agent v2.1");
  expect(within(inspector).queryByRole("button", { name: "Remove Node" })).not.toBeInTheDocument();
});

test("changing the template keeps the Builder as before: an open library, wiring and the Node Inspector", () => {
  render(<Builder initial="template" />);

  const library = screen.getByRole("complementary", { name: "Skill library" });
  expect(library).not.toHaveTextContent("Adding, wiring and removing steps changes the template.");
  expect(within(library).getByRole("searchbox", { name: "Search skills" })).toBeInTheDocument();
  expect(within(library).getByText("Corrosion").closest("[inert]")).toBeNull();
  expect(screen.getByText("drop to connect →")).toBeInTheDocument();

  const inspector = screen.getByRole("complementary", { name: "Node inspector" });
  expect(within(inspector).getByText("Node Inspector")).toBeInTheDocument();
  expect(within(inspector).getByRole("button", { name: "Remove Node" })).toBeInTheDocument();
});

test("with unsaved structural changes, switching to this run asks first, and Keep editing stays", async () => {
  const user = userEvent.setup();
  render(<Builder initial="template" unsavedChanges={UNSAVED_CHANGES} />);

  await pickMode(user, /Change this run/);
  const dialog = screen.getByRole("dialog", { name: "Switch to changing this run?" });
  expect(dialog).toHaveAccessibleDescription(
    "You have unsaved structural changes to the template (1 node added, 2 wires changed). A run can only change step settings, so these changes would be dropped.",
  );
  // Then the backdrop's close button
  expect(within(dialog).getAllByRole("button").map((b) => b.textContent)).toEqual([
    "Keep editing",
    "Save template first",
    "Discard and switch",
    "close",
  ]);

  await user.click(within(dialog).getByRole("button", { name: "Keep editing" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(badge()).toHaveTextContent("the template");
});

test.each(["Save template first", "Discard and switch"])("%s switches to this run", async (choice) => {
  const user = userEvent.setup();
  render(<Builder initial="template" unsavedChanges={UNSAVED_CHANGES} />);

  await pickMode(user, /Change this run/);
  await user.click(screen.getByRole("button", { name: choice }));

  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(badge()).toHaveTextContent("this run");
});

test("Escape on the confirm keeps editing the template", async () => {
  const user = userEvent.setup();
  render(<Builder initial="template" unsavedChanges={UNSAVED_CHANGES} />);

  await pickMode(user, /Change this run/);
  const dialog = screen.getByRole("dialog");
  dialog.dispatchEvent(new Event("cancel", { cancelable: true }));

  expect(await screen.findByRole("button", { name: /Changing:/ })).toHaveTextContent("the template");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("a click on the backdrop keeps editing the template", async () => {
  const user = userEvent.setup();
  render(<Builder initial="template" unsavedChanges={UNSAVED_CHANGES} />);

  await pickMode(user, /Change this run/);
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "close" }));

  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(badge()).toHaveTextContent("the template");
});

test("switching without structural changes, or from this run to the template, doesn't ask", async () => {
  const user = userEvent.setup();
  const { unmount } = render(<Builder initial="template" />);
  await pickMode(user, /Change this run/);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(badge()).toHaveTextContent("this run");
  unmount();

  render(<Builder initial="run" unsavedChanges={UNSAVED_CHANGES} />);
  await pickMode(user, /Edit the template/);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(badge()).toHaveTextContent("the template");
});

test("the Builder opens on the Canvas tab, with the commit buttons", () => {
  render(<Builder initial="template" />);

  const tabs = within(screen.getByRole("tablist", { name: "Builder view" })).getAllByRole("tab");
  expect(tabs.map((tab) => tab.textContent)).toEqual(["Canvas", "History"]);
  expect(screen.getByRole("tab", { name: "Canvas" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("region", { name: "Canvas" })).toBeInTheDocument();
  expect(screen.getByRole("group", { name: "Workflow actions" })).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Version history" })).not.toBeInTheDocument();
});

test("the History tab shows the version list and hides the commit buttons and the mode strip", async () => {
  const user = userEvent.setup();
  render(<Builder initial="template" />);

  await user.click(screen.getByRole("tab", { name: "History" }));

  expect(screen.getByRole("tab", { name: "History" })).toHaveAttribute("aria-selected", "true");
  const list = screen.getByRole("region", { name: "Version history" });
  expect(within(list).getAllByRole("article").map((item) => item.getAttribute("aria-label"))).toEqual([
    "v1.2.0",
    "v1.1.0",
    "v1.0.0",
  ]);
  expect(within(list).getByRole("article", { name: "v1.2.0" })).toHaveAttribute("aria-current", "true");
  const details = screen.getByRole("region", { name: "Version details" });
  expect(within(details).getByRole("heading", { level: 2, name: "v1.2.0" })).toBeInTheDocument();
  expect(screen.queryByRole("group", { name: "Workflow actions" })).not.toBeInTheDocument();
  expect(screen.queryByText(/Saving creates v1\.3\.0/)).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Canvas" })).not.toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: "Canvas" }));
  expect(screen.getByRole("group", { name: "Workflow actions" })).toBeInTheDocument();
});

test("the version link opens the History tab, and reads + this run when changing this run", async () => {
  const user = userEvent.setup();
  const { unmount } = render(<Builder initial="template" />);
  expect(screen.getByRole("button", { name: "v1.2.0" })).toBeInTheDocument();
  unmount();

  render(<Builder initial="run" />);
  await user.click(screen.getByRole("button", { name: "v1.2.0 + this run" }));
  expect(screen.getByRole("tab", { name: "History" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("region", { name: "Version history" })).toBeInTheDocument();
});
