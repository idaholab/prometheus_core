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


/* The Active Jobs tab, fed a real Task Graph shape from the backend: running jobs come
 * first, a single-pipeline job opens its pipeline from anywhere on the card, and a UQ
 * run's many pipelines are listed with the failed ones on top. */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { ConversationTasksResponse, TaskNode } from "@/lib/api/types";
import { ActiveJobsPanel } from "./ActiveJobsPanel.tsx";

const mocks = vi.hoisted(() => ({
  conversationId: "conv-1" as string | null,
  getConversationTasks: vi.fn<(id: string) => Promise<ConversationTasksResponse>>(),
}));
vi.mock("@/lib/store/chat", () => ({ useChatState: () => ({ conversationId: mocks.conversationId }) }));
vi.mock("@/lib/api/client", () => ({ api: { getConversationTasks: mocks.getConversationTasks } }));

function node(over: Partial<TaskNode> & { task_id: string }): TaskNode {
  return {
    parent_task_id: null,
    agent: null,
    skill: null,
    title: "",
    state: "working",
    own_state: "working",
    is_background: false,
    waiting_on: [],
    created_at: null,
    started_at: null,
    updated_at: null,
    finished_at: null,
    last_status_message: null,
    progress: null,
    result_ref: null,
    error: null,
    children: [],
    ...over,
  };
}

const GL = "https://gitlab.example/group/okflow/-/pipelines";
const tasks = (list: TaskNode[], available = true): ConversationTasksResponse => ({
  available,
  conversation_id: "conv-1",
  tasks: list,
});

const TREE = [
  node({
    task_id: "turn-1",
    title: "Run forward UQ on bank worth",
    state: "working",
    children: [
      node({
        task_id: "lit",
        skill: "search_literature",
        state: "completed",
        last_status_message: `Pipeline 41 started: ${GL}/41`,
      }),
      node({
        task_id: "uq",
        skill: "forward_sampling_uq",
        state: "working",
        last_status_message:
          `Sample 1: Pipeline 51 started: ${GL}/51\nSample 2: Pipeline 52 started: ${GL}/52\n` +
          "Pipeline 51: success\nPipeline 52: failed",
      }),
      node({
        task_id: "rom",
        skill: "build_rom",
        state: "failed",
        error: "ROM fit did not converge",
        last_status_message: "Fitting the surrogate.",
      }),
      node({ task_id: "odd", skill: "custom_step", state: "paused" }),
    ],
  }),
];

beforeEach(() => {
  mocks.conversationId = "conv-1";
  mocks.getConversationTasks.mockReset();
});
afterEach(() => vi.useRealTimers());

const cardOf = (name: string) => screen.getByText(name).closest(".card") as HTMLElement;

test("running dispatches come first, each under its turn, with a spinner on the running state", async () => {
  mocks.getConversationTasks.mockResolvedValue(tasks(TREE));
  render(<ActiveJobsPanel />);

  const names = await screen.findAllByText(/^(search_literature|forward_sampling_uq|build_rom|custom_step)$/);
  expect(names.map((n) => n.textContent)).toEqual([
    "forward_sampling_uq",
    "search_literature",
    "build_rom",
    "custom_step",
  ]);
  expect(mocks.getConversationTasks).toHaveBeenCalledWith("conv-1");
  expect(screen.getAllByText("Run forward UQ on bank worth")).toHaveLength(4);

  const uq = cardOf("forward_sampling_uq");
  expect(within(uq).getByText("working").querySelector(".loading")).not.toBeNull();
  expect(within(cardOf("search_literature")).getByText("completed").querySelector(".loading")).toBeNull();
  // An unknown state still gets a neutral badge.
  expect(within(cardOf("custom_step")).getByText("paused")).toHaveClass("badge-ghost");
});

test("a job with one pipeline opens it from anywhere on the card", async () => {
  const user = userEvent.setup();
  mocks.getConversationTasks.mockResolvedValue(tasks(TREE));
  render(<ActiveJobsPanel />);

  const card = await screen.findByRole("link", { name: /search_literature/ });
  expect(card).toHaveAttribute("href", `${GL}/41`);
  expect(card).toHaveAttribute("target", "_blank");
  expect(card).toHaveAttribute("title", "Open GitLab pipeline 41");
  expect(within(card).getByText("GitLab pipeline 41")).toBeInTheDocument();
  // Clicking the job's name (not just the link text) follows the card's pipeline link.
  const followed: string[] = [];
  const onClick = (e: MouseEvent) => {
    followed.push((e.target as Element).closest("a")?.getAttribute("href") ?? "");
    e.preventDefault(); // jsdom does not navigate
  };
  document.addEventListener("click", onClick);
  await user.click(within(card).getByText("search_literature"));
  document.removeEventListener("click", onClick);
  expect(followed).toEqual([`${GL}/41`]);
  expect(within(card).queryAllByRole("link")).toHaveLength(0); // no nested links
});

test("a UQ run lists each sample's pipeline with the failed one first and its state", async () => {
  mocks.getConversationTasks.mockResolvedValue(tasks(TREE));
  render(<ActiveJobsPanel />);

  const uq = await waitFor(() => cardOf("forward_sampling_uq"));
  const links = within(uq).getAllByRole("link");
  expect(links.map((a) => a.textContent)).toEqual(["GitLab pipeline 52", "GitLab pipeline 51"]);
  expect(links[0]).toHaveAttribute("href", `${GL}/52`);
  expect(within(uq).getByText("failed")).toHaveClass("badge-error");
  expect(within(uq).getByText("success")).toHaveClass("badge-ghost");
});

test("a failed job shows its error instead of its last message, and a job with no links is a plain card", async () => {
  mocks.getConversationTasks.mockResolvedValue(tasks(TREE));
  render(<ActiveJobsPanel />);

  const rom = await waitFor(() => cardOf("build_rom"));
  expect(rom.tagName).toBe("DIV");
  expect(within(rom).getByText("ROM fit did not converge")).toHaveClass("text-error");
  expect(within(rom).queryByText("Fitting the surrogate.")).not.toBeInTheDocument();
  expect(within(rom).queryByRole("list")).not.toBeInTheDocument();
});

test("a progress message shows under the job, and a turn with no dispatches is its own row", async () => {
  mocks.getConversationTasks.mockResolvedValue(
    tasks([node({ task_id: "solo", title: "Summarize", state: "working", last_status_message: "Reading sources." })]),
  );
  render(<ActiveJobsPanel />);

  const msg = await screen.findByText("Reading sources.");
  expect(msg).toHaveClass("text-base-content/70");
  // The turn title equals the row name, so it is not repeated as a subtitle.
  expect(screen.getAllByText("Summarize")).toHaveLength(1);
});

test("a link reported early stays on the card after later progress replaces it", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const first = node({ task_id: "uq", skill: "forward_sampling_uq", last_status_message: `Pipeline 7 started: ${GL}/7` });
  const later = { ...first, last_status_message: "Pipeline 7: running" };
  mocks.getConversationTasks
    .mockResolvedValueOnce(tasks([node({ task_id: "turn", title: "UQ", children: [first] })]))
    .mockResolvedValue(tasks([node({ task_id: "turn", title: "UQ", children: [later] })]));
  render(<ActiveJobsPanel />);

  await screen.findByText(`Pipeline 7 started: ${GL}/7`);
  await vi.advanceTimersByTimeAsync(3000);
  await screen.findByText("Pipeline 7: running");
  const card = screen.getByRole("link", { name: /forward_sampling_uq/ });
  expect(card).toHaveAttribute("href", `${GL}/7`);
});

test("with no jobs the tab says pipelines will display here", async () => {
  mocks.getConversationTasks.mockResolvedValue(tasks([]));
  render(<ActiveJobsPanel />);
  await waitFor(() => expect(mocks.getConversationTasks).toHaveBeenCalled());
  expect(screen.getByText("No Active Jobs")).toBeInTheDocument();
  expect(screen.getByText("Assigned solver pipelines will display here")).toBeInTheDocument();
});

test("when the Task Graph is unavailable the empty tab says so", async () => {
  mocks.getConversationTasks.mockResolvedValue(tasks([], false));
  render(<ActiveJobsPanel />);
  expect(await screen.findByText("Task status is unavailable right now")).toBeInTheDocument();
});

test("a failed poll keeps the last list, and the next poll refreshes it", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  mocks.getConversationTasks
    .mockResolvedValueOnce(tasks([node({ task_id: "a", title: "First turn", state: "working" })]))
    .mockRejectedValueOnce(new Error("backend restarting"))
    .mockResolvedValue(tasks([node({ task_id: "a", title: "First turn", state: "completed" })]));
  render(<ActiveJobsPanel />);

  expect(await screen.findByText("working")).toBeInTheDocument();
  await vi.advanceTimersByTimeAsync(3000);
  expect(screen.getByText("working")).toBeInTheDocument();
  await vi.advanceTimersByTimeAsync(3000);
  expect(await screen.findByText("completed")).toBeInTheDocument();
});

test("with no open conversation nothing is fetched", () => {
  mocks.conversationId = null;
  render(<ActiveJobsPanel />);
  expect(mocks.getConversationTasks).not.toHaveBeenCalled();
  expect(screen.getByText("No Active Jobs")).toBeInTheDocument();
});

test("a reply that lands after the tab closed is dropped, and polling stops", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  let release!: (v: ConversationTasksResponse) => void;
  mocks.getConversationTasks.mockReturnValueOnce(new Promise((r) => (release = r)));
  const { unmount } = render(<ActiveJobsPanel />);
  unmount();
  release(tasks([node({ task_id: "late", title: "Late" })]));
  await vi.advanceTimersByTimeAsync(10_000);
  expect(mocks.getConversationTasks).toHaveBeenCalledTimes(1);
});
