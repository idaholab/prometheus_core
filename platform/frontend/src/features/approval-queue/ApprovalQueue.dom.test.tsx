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

/* The approval queue as a whole: the summary, the list of checkpoints, and
 * the selected one's details. The view takes everything as props, so it runs
 * without a backend. */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import { ApprovalQueue } from "./ApprovalQueue.tsx";
import type { QueueCounter } from "./QueueSummary.tsx";
import type { Checkpoint } from "./types.ts";

const COUNTERS: QueueCounter[] = [
  { id: "pending", label: "Pending Reviews", count: 2, tone: "primary" },
  { id: "urgent", label: "Urgent", count: 1, tone: "error" },
];

const CHECKPOINTS: Checkpoint[] = [
  {
    id: "CKP-1",
    title: "Mesh check for test assembly",
    priority: "urgent",
    workflow: "WF-TEST-1",
    agent: "Test Mesh Agent v1",
    confidence: "91.0%",
    submitted: "5m ago",
    artifact: {
      previewLabel: "Test mesh preview",
      fileName: "test_mesh.vtk",
      size: "1.0 MB",
      generated: "5 min ago",
      metrics: [{ id: "cells", name: "Cell Count", value: "1,000 hex", status: "pass", threshold: "500" }],
      requirement: { id: "REQ-TEST-1", version: "v1.0", text: "The test mesh stays within its made-up bounds." },
    },
  },
  {
    id: "CKP-2",
    title: "Stress check for test nozzle",
    priority: "standard",
    workflow: "WF-TEST-2",
    agent: "Test Stress Agent v1",
    confidence: "88.0%",
    submitted: "1h ago",
  },
];

function card(id: string) {
  return screen.getByRole("article", { name: new RegExp(`^${id}:`) });
}

test("lists every checkpoint and marks only the selected one", () => {
  render(<ApprovalQueue counters={COUNTERS} checkpoints={CHECKPOINTS} selectedId="CKP-1" />);

  const summary = screen.getByRole("list", { name: "Queue summary" });
  expect(within(summary).getByText("Pending Reviews")).toBeInTheDocument();
  expect(within(summary).getByText("Urgent")).toBeInTheDocument();

  expect(card("CKP-1")).toHaveAccessibleName("CKP-1: Mesh check for test assembly");
  expect(card("CKP-2")).toHaveAccessibleName("CKP-2: Stress check for test nozzle");
  expect(card("CKP-1")).toHaveAttribute("aria-current", "true");
  expect(card("CKP-2")).not.toHaveAttribute("aria-current");
});

test("shows the selected checkpoint's details and its artifact preview", () => {
  render(<ApprovalQueue counters={COUNTERS} checkpoints={CHECKPOINTS} selectedId="CKP-1" />);

  const details = screen.getByRole("region", { name: "Checkpoint details" });
  expect(within(details).getByText("WF-TEST-1")).toBeInTheDocument();
  expect(within(details).getByText("Test Mesh Agent v1")).toBeInTheDocument();
  expect(within(details).getByRole("tab", { name: "Artifact Preview" })).toHaveAttribute("aria-selected", "true");
  expect(within(details).getByRole("tabpanel", { name: "Artifact Preview" })).toHaveTextContent("test_mesh.vtk");
  expect(within(details).getByRole("button", { name: "Approve & Deploy" })).toBeInTheDocument();
});

test("selecting a checkpoint with no artifact shows a placeholder preview", () => {
  render(<ApprovalQueue counters={COUNTERS} checkpoints={CHECKPOINTS} selectedId="CKP-2" />);

  expect(card("CKP-2")).toHaveAttribute("aria-current", "true");
  expect(screen.getByRole("tabpanel", { name: "Artifact Preview" })).toHaveTextContent("Artifact Preview coming soon");
});

test("with nothing selected, the details show the empty state", () => {
  render(<ApprovalQueue counters={COUNTERS} checkpoints={CHECKPOINTS} />);

  expect(screen.getByText("Select a checkpoint to review it.")).toBeInTheDocument();
  expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  expect(card("CKP-1")).not.toHaveAttribute("aria-current");
});

test("the detail tabs switch panels by click and by arrow key", async () => {
  const user = userEvent.setup();
  render(<ApprovalQueue counters={COUNTERS} checkpoints={CHECKPOINTS} selectedId="CKP-1" />);

  await user.click(screen.getByRole("tab", { name: "Quality Metrics" }));
  expect(screen.getByRole("tab", { name: "Quality Metrics" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("tabpanel", { name: "Quality Metrics" })).toHaveTextContent("Quality Metrics coming soon");

  await user.keyboard("{ArrowRight}");
  expect(screen.getByRole("tab", { name: "Agent Trace" })).toHaveFocus();
  expect(screen.getByRole("tabpanel", { name: "Agent Trace" })).toBeInTheDocument();

  await user.keyboard("{Home}");
  expect(screen.getByRole("tab", { name: "Artifact Preview" })).toHaveFocus();
  expect(screen.getByRole("tabpanel", { name: "Artifact Preview" })).toHaveTextContent("test_mesh.vtk");
});
