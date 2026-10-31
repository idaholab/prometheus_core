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


/* The Live Agents Arena, fed the chat store's real status-log shapes: the agents a run
 * names appear in order with their connectors, the per-sample loop collapses into one
 * badge, and failures show on the agent's card and in the footer. */
import { render, screen, within } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import type { ArtifactMeta } from "@/lib/api/types";
import type { ChatItem, ChatState } from "@/lib/store/chat";
import { LiveAgentPanel } from "./LiveAgentPanel.tsx";

const store = vi.hoisted(() => ({ state: { items: [], awaiting: false } as unknown as ChatState }));
vi.mock("@/lib/store/chat", () => ({ useChatState: () => store.state }));

function show(items: ChatItem[], awaiting = false) {
  store.state = { ...store.state, items, awaiting };
  return render(<LiveAgentPanel />);
}

const tool = (history: string[], done: boolean, id = "tool-1"): ChatItem => ({
  id,
  kind: "tool",
  turnId: "t1",
  name: history.at(-1) ?? "",
  history,
  done,
});
const user: ChatItem = { id: "u1", kind: "user", text: "run forward UQ on the bank worth model" };
const assistant = (artifacts: ArtifactMeta[]): ChatItem => ({
  id: `a${artifacts.length}`,
  kind: "assistant",
  text: "Here is the UQ report.",
  artifacts,
  recommendedMaterials: [],
  followUpSuggestions: [],
});
const report = { artifact_id: "uq-7", name: "uq_bank_worth.ipynb" } as ArtifactMeta;

const UQ_RUNNING = [
  "Received request.",
  "Next step: 'forward_sampling_uq'.",
  "Invoking 'forward_sampling_uq'.",
  "[forward_sampling_uq] Pipeline 1001: running",
  "[forward_sampling_uq] Pipeline 1002: running",
  "[forward_sampling_uq] Pipeline 1003: running",
  "[forward_sampling_uq] Running okflow neutronics: 1/3 cases complete (3 max concurrent)",
];
const UQ_DONE = [
  ...UQ_RUNNING,
  "[forward_sampling_uq] Pipeline 1001: success",
  "[forward_sampling_uq] Pipeline 1002: success",
  "[forward_sampling_uq] Pipeline 1003: success",
  "[forward_sampling_uq] Running okflow neutronics: 3/3 cases complete (3 max concurrent)",
  "'forward_sampling_uq' completed.",
  "Response ready.",
];

const footer = (container: HTMLElement) => container.lastElementChild as HTMLElement;

beforeEach(() => {
  store.state = { items: [], awaiting: false } as unknown as ChatState;
});

test("before any run the arena says agents will appear", () => {
  const { container } = show([]);
  expect(screen.getByText("No Agents Yet")).toBeInTheDocument();
  expect(screen.getByText("Agents appear here as the run calls them")).toBeInTheDocument();
  expect(within(footer(container)).getByText("Derived from the live status log.")).toBeInTheDocument();
  expect(screen.queryByLabelText("run in progress")).not.toBeInTheDocument();
});

test("a running UQ turn shows planner, UQ agent and runner, with the pipeline loop collapsed into one badge", () => {
  const { container } = show([user, tool(UQ_RUNNING, false)], true);

  const names = [...container.querySelectorAll(".lap-name")].map((n) => n.textContent);
  expect(names).toEqual(["Planner", "UQ agent", "okflow runner"]);
  expect(screen.getByText("client-agent")).toBeInTheDocument();
  expect(screen.getByText("HPC pipelines")).toBeInTheDocument();

  // One badge for the three pipelines, not three rows.
  expect(screen.getByText("×3")).toBeInTheDocument();
  expect(screen.getByTitle("1/3 cases complete")).toBeInTheDocument();
  // The live connector is the one into the runner.
  expect(screen.getByText("pipelines")).toBeInTheDocument();
  expect(within(footer(container)).getByText("Now: okflow runner.")).toBeInTheDocument();
  expect(screen.getByLabelText("run in progress")).toBeInTheDocument();
  // Still running: the report has not docked yet.
  expect(screen.queryByText("report")).not.toBeInTheDocument();
});

test("the in-flight step is shown even when an older finished step comes first", () => {
  show([tool(["Received request.", "Invoking 'search_literature'.", "'search_literature' completed."], true, "old"), tool(UQ_RUNNING, false, "new")]);
  expect(screen.getByText("UQ agent")).toBeInTheDocument();
  expect(screen.queryByText("search_literature")).not.toBeInTheDocument();
});

test("a finished turn docks the report as a link to the artifact the turn produced", () => {
  const { container } = show([user, tool(UQ_DONE, true), assistant([report]), assistant([])]);

  const chip = screen.getByRole("link", { name: /report/ });
  expect(chip).toHaveAttribute("href", "/api/artifacts/uq-7/content");
  expect(chip).toHaveAttribute("target", "_blank");
  expect(chip).toHaveAttribute("title", "Open the report");
  expect(chip).toHaveTextContent("report ↗");
  expect(screen.getByTitle("3/3 cases complete")).toBeInTheDocument();
  expect(within(footer(container)).getByText("Turn complete.")).toBeInTheDocument();
  expect(screen.queryByLabelText("run in progress")).not.toBeInTheDocument();
});

test("a finished turn with no artifact docks a plain, non-clickable report chip", () => {
  show([user, tool(["Invoking 'search_literature'.", "'search_literature' completed."], true)]);
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  expect(screen.getByTitle("report")).toHaveTextContent(/^report$/);
  // A skill with no friendly name shows its id once, with no separate role line.
  expect(screen.getAllByText("search_literature")).toHaveLength(1);
  // Results flow back up the connector to the planner.
  expect(screen.getByText("result")).toBeInTheDocument();
});

test("an unreachable UQ agent is shown red on its card and named in the footer", () => {
  const { container } = show([
    user,
    tool(
      [
        "Received request.",
        "Next step: 'forward_sampling_uq'.",
        "Invoking 'forward_sampling_uq'.",
        "'forward_sampling_uq' failed: Network communication error: All connection attempts failed (host.docker.internal:8042)",
        "Response ready.",
      ],
      true,
    ),
  ]);
  const alert = screen.getByRole("alert");
  expect(within(alert).getByText("unreachable")).toBeInTheDocument();
  expect(alert).toHaveTextContent("host.docker.internal:8042");
  expect(within(footer(container)).getByText("UQ agent failed. See the agent card for the error.")).toBeInTheDocument();
});

test("a task error with no message is tagged failed, without an error line", () => {
  show([tool(["Invoking 'search_literature'.", "'search_literature' failed:"], true)]);
  const alert = screen.getByRole("alert");
  expect(within(alert).getByText("failed")).toBeInTheDocument();
  expect(alert.querySelector("[title]")).toBeNull();
});

test("results flowing back from the runner light the connector upward, and an empty loop shows no progress", () => {
  show([
    tool(
      [
        "Invoking 'forward_sampling_uq'.",
        "[forward_sampling_uq] Running okflow neutronics: 2/2 cases complete",
      ],
      false,
    ),
  ]);
  expect(screen.getByText("results")).toBeInTheDocument();
  expect(screen.getByTitle("2/2 cases complete")).toBeInTheDocument();

  show([tool(["Invoking 'forward_sampling_uq'.", "[forward_sampling_uq] Pipelines (0/0): none started"], false, "t0")]);
  expect(screen.getByTitle("0/0 cases complete")).toBeInTheDocument();
});

test("a peer agent the UQ agent calls joins the column below it with its own connector", () => {
  const { container } = show([
    tool(
      [
        "Invoking 'forward_sampling_uq'.",
        "[forward_sampling_uq] Requesting baseline pipeline config from okflow-config-agent ...",
      ],
      false,
    ),
  ]);
  const names = [...container.querySelectorAll(".lap-name")].map((n) => n.textContent);
  expect(names).toEqual(["Planner", "UQ agent", "okflow config"]);
  expect(screen.getByText("pipeline config")).toBeInTheDocument();
  expect(screen.getByText("A2A")).toBeInTheDocument();
});
