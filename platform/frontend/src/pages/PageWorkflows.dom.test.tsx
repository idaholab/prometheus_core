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

import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { ApiError } from "@/lib/api/client";
import type { GraphNode, Workflow, WorkflowDetail, WorkflowListResponse } from "@/lib/api/types";
import { PageWorkflows } from "./PageWorkflows.tsx";

// The API is stubbed; ApiError stays the real class.
const api = vi.hoisted(() => ({ listWorkflows: vi.fn(), getWorkflow: vi.fn() }));
vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  api,
}));

// The seed row of CONTRACT.md's `GET /api/workflows` example, with a smaller graph: Get Material
// Data feeding Synthesize Material Analysis.
const SEED: Workflow = {
  workflow_id: "comprehensive_material_analysis",
  name: "Comprehensive Material Analysis",
  summary: "Full multi-domain assessment with data retrieval and specialist analysis.",
  category: "Safety",
  version: "1.0.0",
  source: "local",
  owner: "materials-team",
  complexity: null,
  estimated_runtime_seconds: 270,
  speedup: null,
  requires_approval: true,
  agent_count: 5,
  checkpoint_count: 0,
};
// A made-up template that an agent card declares, with no runtime set.
const OTHER: Workflow = {
  workflow_id: "patriotic_usa_png",
  name: "Patriotic USA PNG",
  summary: "Renders a patriotic USA image as a PNG artifact.",
  category: "General",
  version: "0.1.0",
  source: "agent_card",
  owner: "artifact-debug-agent",
  complexity: "simple",
  estimated_runtime_seconds: null,
  speedup: 2.0,
  requires_approval: false,
  agent_count: 1,
  checkpoint_count: 0,
};

const listed = (...workflows: Workflow[]): WorkflowListResponse => ({ available: true, workflows });

function skill(node_id: string, label: string, is_final = false): GraphNode {
  return {
    node_id,
    kind: "skill",
    skill_id: node_id,
    label,
    agent_name: `${node_id}-agent`,
    is_final,
    inputs: [{ port: "material_id", source: "input.material_id", optional: false }],
  };
}

const DETAILS: Record<string, WorkflowDetail> = {
  [SEED.workflow_id]: {
    ...SEED,
    inputs: { required: ["material_id"], optional: [] },
    graph: {
      workflow_id: SEED.workflow_id,
      mode: "dag",
      nodes: [
        skill("retrieve_material", "Get Material Data"),
        skill("synthesize_report", "Synthesize Material Analysis", true),
      ],
      edges: [
        {
          edge_id: "comprehensive_material_analysis-e1",
          from_node: "retrieve_material",
          to_node: "synthesize_report",
          kind: "data",
          port: "tool_results.material_data",
        },
      ],
    },
  },
  [OTHER.workflow_id]: {
    ...OTHER,
    inputs: { required: [], optional: [] },
    graph: {
      workflow_id: OTHER.workflow_id,
      mode: "sequential",
      nodes: [skill("render_png", "Render Patriotic PNG", true)],
      edges: [],
    },
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  api.listWorkflows.mockResolvedValue(listed(SEED));
  api.getWorkflow.mockImplementation(async (id: string) => {
    const detail = DETAILS[id];
    if (!detail) throw new ApiError(404, "Workflow not found");
    return detail;
  });
});

// React Flow measures its container and watches it for resizes, and jsdom has
// neither, nor modal dialogs: showModal and close just set the open attribute.
beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});
afterEach(() => vi.unstubAllGlobals());

const commitButtons = () =>
  within(screen.getByRole("group", { name: "Workflow actions" }))
    .getAllByRole("button")
    .map((b) => b.textContent);

test("Modify Plan's main click opens the Builder changing this run", async () => {
  const user = userEvent.setup();
  render(<PageWorkflows />);

  await user.click(await screen.findByRole("button", { name: "Modify Plan" }));

  expect(screen.getByRole("button", { name: /Changing:/ })).toHaveTextContent("this run");
  expect(
    screen.getByText(/Changes apply to this run only\. The template \(v1\.2\.0\) is untouched\./),
  ).toBeInTheDocument();
  expect(commitButtons()).toEqual(["Save as variant", "Propose new version", "Run once"]);
  expect(screen.getByRole("region", { name: "Canvas" })).not.toHaveTextContent("Drag a skill here to begin");
});

test("Edit the template opens the Builder changing the template, and switching to this run asks first", async () => {
  const user = userEvent.setup();
  render(<PageWorkflows />);

  await user.click(await screen.findByRole("button", { name: "More Modify Plan options" }));
  expect(screen.getByRole("menuitem", { name: /Change this run/ })).toHaveAccessibleDescription(
    "Default. Tweak steps for this run only; the template is untouched.",
  );
  await user.click(screen.getByRole("menuitem", { name: /Edit the template/ }));

  expect(screen.getByRole("button", { name: /Changing:/ })).toHaveTextContent("the template");
  // The name is PageWorkflows' BUILDER_TEMPLATE_NAME placeholder, equal to the seed's by chance;
  // PPLT-240 replaces it when the Builder loads real templates.
  expect(
    screen.getByText(
      "Editing the template. Saving creates v1.3.0 for everyone who uses Comprehensive Material Analysis.",
    ),
  ).toBeInTheDocument();
  expect(commitButtons()).toEqual(["Validate", "Save", "Run Workflow"]);

  await user.click(screen.getByRole("button", { name: /Changing:/ }));
  await user.click(screen.getByRole("menuitemradio", { name: /Change this run/ }));
  const dialog = screen.getByRole("dialog", { name: "Switch to changing this run?" });
  expect(dialog).toHaveTextContent("(1 node added, 2 wires changed)");
  await user.click(within(dialog).getByRole("button", { name: "Discard and switch" }));
  expect(commitButtons()).toEqual(["Save as variant", "Propose new version", "Run once"]);

  // The changes are gone, so going back to the template and out again doesn't ask.
  await user.click(screen.getByRole("button", { name: /Changing:/ }));
  await user.click(screen.getByRole("menuitemradio", { name: /Edit the template/ }));
  await user.click(screen.getByRole("button", { name: /Changing:/ }));
  await user.click(screen.getByRole("menuitemradio", { name: /Change this run/ }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(commitButtons()).toEqual(["Save as variant", "Propose new version", "Run once"]);
});

test("from this run or a new workflow, switching to this run doesn't ask", async () => {
  const user = userEvent.setup();
  const { unmount } = render(<PageWorkflows />);

  await user.click(await screen.findByRole("button", { name: "Modify Plan" }));
  await user.click(screen.getByRole("button", { name: /Changing:/ }));
  await user.click(screen.getByRole("menuitemradio", { name: /Edit the template/ }));
  await user.click(screen.getByRole("button", { name: /Changing:/ }));
  await user.click(screen.getByRole("menuitemradio", { name: /Change this run/ }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  unmount();

  render(<PageWorkflows />);
  await user.click(screen.getByRole("button", { name: "New Workflow" }));
  await user.click(screen.getByRole("button", { name: /Changing:/ }));
  await user.click(screen.getByRole("menuitemradio", { name: /Change this run/ }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(commitButtons()).toEqual(["Save as variant", "Propose new version", "Run once"]);
});

test("New Workflow opens the Builder changing the template, on an empty canvas", async () => {
  const user = userEvent.setup();
  render(<PageWorkflows />);

  await user.click(screen.getByRole("button", { name: "New Workflow" }));

  expect(screen.getByRole("button", { name: /Changing:/ })).toHaveTextContent("the template");
  expect(screen.getByText("Drag a skill here to begin")).toBeInTheDocument();
  expect(screen.getByText("No node selected.")).toBeInTheDocument();
});

test("the commit buttons do nothing yet and log no errors", async () => {
  const error = vi.spyOn(console, "error").mockImplementation(() => {});
  const user = userEvent.setup();
  render(<PageWorkflows />);

  await user.click(await screen.findByRole("button", { name: "Modify Plan" }));
  for (const name of ["Save as variant", "Propose new version", "Run once"]) {
    await user.click(screen.getByRole("button", { name }));
  }
  await user.click(screen.getByRole("button", { name: /Changing:/ }));
  await user.click(screen.getByRole("menuitemradio", { name: /Edit the template/ }));
  for (const name of ["Validate", "Save", "Run Workflow"]) {
    await user.click(screen.getByRole("button", { name }));
  }

  expect(commitButtons()).toEqual(["Validate", "Save", "Run Workflow"]);
  expect(error).not.toHaveBeenCalled();
  error.mockRestore();
});

// The Workflow Console MUST show a loading, an unavailable, an empty, an error or a success state
// for the template list, and selecting a template MUST load its detail and draw its graph.
describe("workflow_console_states", () => {
  const card = (name: string) =>
    screen.getAllByRole("article").find((a) => within(a).queryByRole("heading", { name })) as HTMLElement;
  /**
   * The definition in the row of a definition-list term, e.g. "Est. Runtime" in a card. The
   * `term` role takes no accessible name from its content, so the term is matched by its text.
   */
  const termValue = (scope: HTMLElement, term: string) => {
    const dt = within(scope)
      .getAllByRole("term")
      .find((t) => t.textContent === term) as HTMLElement;
    return within(dt.parentElement as HTMLElement).getByRole("definition");
  };

  test("a pending template list shows the loading state", () => {
    api.listWorkflows.mockReturnValue(new Promise(() => {}));
    render(<PageWorkflows />);

    expect(screen.getByText("Loading workflow templates...")).toBeInTheDocument();
    expect(screen.queryByText("Workflow Execution Planner")).not.toBeInTheDocument();
  });

  test("an unavailable workflow library shows the unavailable alert, no cards and no planner", async () => {
    api.listWorkflows.mockResolvedValue({ available: false, workflows: [] });
    render(<PageWorkflows />);

    expect(await screen.findByRole("alert")).toHaveTextContent("The workflow library is unavailable.");
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    expect(screen.queryByText("No workflow templates are available.")).not.toBeInTheDocument();
    expect(screen.queryByText("Workflow Execution Planner")).not.toBeInTheDocument();
    expect(api.getWorkflow).not.toHaveBeenCalled();
  });

  test("an empty template list shows the empty state and no planner", async () => {
    api.listWorkflows.mockResolvedValue(listed());
    render(<PageWorkflows />);

    expect(await screen.findByText("No workflow templates are available.")).toBeInTheDocument();
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText("Workflow Execution Planner")).not.toBeInTheDocument();
    expect(api.getWorkflow).not.toHaveBeenCalled();
  });

  test("a failed template list shows the error alert and no planner", async () => {
    api.listWorkflows.mockRejectedValue(new ApiError(500, "Internal Server Error"));
    render(<PageWorkflows />);

    expect(await screen.findByRole("alert")).toHaveTextContent("The workflow templates are unavailable.");
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    expect(screen.queryByText("Workflow Execution Planner")).not.toBeInTheDocument();
  });

  test("a backend without the workflow routes (404) shows the error alert and no planner", async () => {
    api.listWorkflows.mockRejectedValue(new ApiError(404, "Not Found"));
    render(<PageWorkflows />);

    expect(await screen.findByRole("alert")).toHaveTextContent("The workflow templates are unavailable.");
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    expect(screen.queryByText("Workflow Execution Planner")).not.toBeInTheDocument();
  });

  test("two templates show two cards, the first selected, and draw its graph without a status pill", async () => {
    api.listWorkflows.mockResolvedValue(listed(SEED, OTHER));
    render(<PageWorkflows />);

    expect(await screen.findByText("Get Material Data")).toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(2);
    expect(within(card(SEED.name)).getByRole("button", { name: "Selected" })).toBeInTheDocument();
    expect(within(card(OTHER.name)).getByRole("button", { name: "Select Template" })).toBeInTheDocument();
    expect(api.getWorkflow).toHaveBeenCalledWith(SEED.workflow_id);
    expect(screen.getByText("Workflow Execution Planner")).toBeInTheDocument();
    expect(screen.getByText("Synthesize Material Analysis")).toBeInTheDocument();
    // The pill labels of WorkflowGraphNodes' STATUS_PILL; nothing else on the page shows them.
    for (const pill of ["Done", "Queued", "Blocked"]) {
      expect(screen.queryByText(pill)).not.toBeInTheDocument();
    }
    // The wire has no step estimate, so no agent node shows an EST row.
    expect(screen.queryByText("EST")).not.toBeInTheDocument();
  });

  test("the seed card shows its approval and runtime, and no complexity, speed-up or owner", async () => {
    render(<PageWorkflows />);
    await screen.findByText("Get Material Data");

    const seed = card(SEED.name);
    expect(within(seed).getByText("Needs approval")).toBeInTheDocument();
    for (const complexity of ["simple", "moderate", "complex"]) {
      expect(within(seed).queryByText(complexity)).not.toBeInTheDocument();
    }
    expect(within(seed).queryByText(/faster/)).not.toBeInTheDocument();
    expect(termValue(seed, "Est. Runtime")).toHaveTextContent("4m 30s");
    expect(within(seed).queryByText("Owner")).not.toBeInTheDocument();
    expect(within(seed).queryByText(SEED.owner as string)).not.toBeInTheDocument();
  });

  test("an agent-card card shows its owner, complexity and speed-up, and no approval or runtime", async () => {
    api.listWorkflows.mockResolvedValue(listed(SEED, OTHER));
    render(<PageWorkflows />);
    await screen.findByText("Get Material Data");

    const other = card(OTHER.name);
    expect(termValue(other, "Owner")).toHaveTextContent("artifact-debug-agent");
    expect(within(other).getByText("simple")).toBeInTheDocument();
    expect(within(other).getByText("2.0x faster")).toBeInTheDocument();
    expect(within(other).queryByText("Needs approval")).not.toBeInTheDocument();
    expect(within(other).queryByText("Est. Runtime")).not.toBeInTheDocument();
  });

  test("the seed plan shows that it needs approval before it runs, and its pipeline time", async () => {
    render(<PageWorkflows />);
    await screen.findByText("Get Material Data");

    expect(termValue(document.body, "Approval")).toHaveTextContent("Required before run");
    expect(termValue(document.body, "Pipeline Time")).toHaveTextContent("4m 30s");
  });

  test("a plan without approval or runtime hides the Approval and Pipeline Time rows", async () => {
    const user = userEvent.setup();
    api.listWorkflows.mockResolvedValue(listed(SEED, OTHER));
    render(<PageWorkflows />);
    await screen.findByText("Get Material Data");

    await user.click(within(card(OTHER.name)).getByRole("button", { name: "Select Template" }));

    expect(await screen.findByText("Render Patriotic PNG")).toBeInTheDocument();
    expect(screen.queryByText("Required before run")).not.toBeInTheDocument();
    expect(screen.queryByText("Pipeline Time")).not.toBeInTheDocument();
  });

  test("selecting the second card loads its detail and draws its graph", async () => {
    const user = userEvent.setup();
    api.listWorkflows.mockResolvedValue(listed(SEED, OTHER));
    render(<PageWorkflows />);
    await screen.findByText("Get Material Data");

    await user.click(within(card(OTHER.name)).getByRole("button", { name: "Select Template" }));

    expect(api.getWorkflow).toHaveBeenLastCalledWith(OTHER.workflow_id);
    expect(await screen.findByText("Render Patriotic PNG")).toBeInTheDocument();
    expect(screen.queryByText("Get Material Data")).not.toBeInTheDocument();
    expect(within(card(OTHER.name)).getByRole("button", { name: "Selected" })).toBeInTheDocument();
    expect(within(card(SEED.name)).getByRole("button", { name: "Select Template" })).toBeInTheDocument();
  });

  test.each([
    ["an unknown template (404)", new ApiError(404, "Workflow not found")],
    ["an unavailable library (503)", new ApiError(503, "Workflow library is unavailable")],
  ])("a failed template detail for %s shows the plan error alert and keeps the cards", async (_, error) => {
    api.getWorkflow.mockRejectedValue(error);
    render(<PageWorkflows />);

    expect(await screen.findByRole("alert")).toHaveTextContent("The workflow plan is unavailable.");
    expect(within(card(SEED.name)).getByRole("button", { name: "Selected" })).toBeInTheDocument();
    expect(screen.getByText("Workflow Execution Planner")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Modify Plan" })).not.toBeInTheDocument();
  });

  // The first template's detail is held back until the second card is selected and drawn.
  async function selectSecondWhileFirstPending() {
    let settle!: { resolve: (d: WorkflowDetail) => void; reject: (e: unknown) => void };
    api.getWorkflow.mockImplementationOnce(
      () => new Promise<WorkflowDetail>((resolve, reject) => (settle = { resolve, reject })),
    );
    const user = userEvent.setup();
    api.listWorkflows.mockResolvedValue(listed(SEED, OTHER));
    render(<PageWorkflows />);
    expect(await screen.findByText("Loading the workflow plan...")).toBeInTheDocument();
    expect(api.getWorkflow).toHaveBeenCalledWith(SEED.workflow_id);

    await user.click(within(card(OTHER.name)).getByRole("button", { name: "Select Template" }));
    expect(await screen.findByText("Render Patriotic PNG")).toBeInTheDocument();
    return settle;
  }

  test("a late detail of a template no longer selected is dropped", async () => {
    const first = await selectSecondWhileFirstPending();

    await act(async () => first.resolve(DETAILS[SEED.workflow_id]));

    expect(screen.getByText("Render Patriotic PNG")).toBeInTheDocument();
    expect(screen.queryByText("Get Material Data")).not.toBeInTheDocument();
  });

  test("a late failure of a template no longer selected is dropped", async () => {
    const first = await selectSecondWhileFirstPending();

    await act(async () => first.reject(new ApiError(500, "Internal Server Error")));

    expect(screen.getByText("Render Patriotic PNG")).toBeInTheDocument();
    expect(screen.queryByText("The workflow plan is unavailable.")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
