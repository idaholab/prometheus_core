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


/* The UQ notebook viewer, reached the way the chat reaches it: an artifact goes through
 * the adapter and the element registry, and the user sees the baked report inline with
 * its download and agent-attached buttons. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ElementList } from "@/components/ElementRenderer";
import type { ArtifactMeta } from "@/lib/api/types";
import { artifactToElement } from "@/lib/elements/artifactAdapter";
import { UQNotebookElement } from "./UQNotebookElement.tsx";

// The registry loads the 3D viewers eagerly in dev; three.js needs WebGL, which jsdom lacks.
vi.mock("./ifc/IFCViewerElement", () => ({ default: () => null }));
vi.mock("./mesh/MeshViewerElement", () => ({ default: () => null }));

afterEach(() => {
  vi.unstubAllGlobals();
});

function uqArtifact(over: Partial<ArtifactMeta> = {}): ArtifactMeta {
  return {
    artifact_id: "uq-7",
    name: "uq_bank_worth.ipynb",
    mime_type: "application/x-ipynb+json",
    json_type: "prometheus.uq.result.v1",
    description: "",
    uri: null,
    tags: ["uq", "notebook"],
    json_body: null,
    render_hint: "uq",
    citation: null,
    producer_agent_id: null,
    created_at: null,
    has_report: true,
    ...over,
  } as ArtifactMeta;
}

test("a UQ artifact shows its baked report inline, with a notebook download and the agent's buttons", () => {
  const links = [
    { label: "Open interactive dashboard", url: "https://uq.example/console/run-7" },
    { label: "Not a web link", url: "javascript:alert(1)" },
  ];
  render(<ElementList elements={[artifactToElement(uqArtifact({ links }))]} />);

  const frame = screen.getByTitle("uq_bank_worth.ipynb");
  expect(frame.tagName).toBe("IFRAME");
  expect(frame).toHaveAttribute("src", "/api/artifacts/uq-7/report");
  // Scripts run, but in an opaque origin: no allow-same-origin.
  expect(frame.getAttribute("sandbox")).toContain("allow-scripts");
  expect(frame.getAttribute("sandbox")).not.toContain("allow-same-origin");
  // Popups the report opens stay sandboxed.
  expect(frame.getAttribute("sandbox")).not.toContain("allow-popups-to-escape-sandbox");
  expect(frame).toHaveAttribute("loading", "lazy");
  expect(frame).toHaveStyle({ height: "760px" });

  const download = screen.getByRole("link", { name: "Download uq_bank_worth.ipynb notebook" });
  expect(download).toHaveAttribute("href", "/api/artifacts/uq-7/content");
  expect(download).toHaveAttribute("download", "uq_bank_worth.ipynb");

  const dashboard = screen.getByRole("link", { name: "Open interactive dashboard (opens in a new tab)" });
  expect(dashboard).toHaveAttribute("href", "https://uq.example/console/run-7");
  expect(dashboard).toHaveAttribute("target", "_blank");
  expect(screen.queryByText("Not a web link")).not.toBeInTheDocument();
});

test("without a filename or download URL the viewer falls back to the element name and hides the download", () => {
  render(
    <UQNotebookElement element={{ type: "custom", name: "UQDashboard", props: { reportUrl: "/api/artifacts/x/report" } }} />,
  );
  const frame = screen.getByTitle("UQDashboard");
  expect(frame).toHaveAttribute("src", "/api/artifacts/x/report");
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});

test("an element with no name and no props falls back to a generic title and renders nothing without a report", () => {
  const { container } = render(<UQNotebookElement element={{ type: "custom" }} />);
  expect(container).toBeEmptyDOMElement();
  render(<UQNotebookElement element={{ type: "custom", props: { reportUrl: "/r" } }} />);
  expect(screen.getByTitle("UQ analysis")).toHaveAttribute("src", "/r");
});

test("a UQ artifact whose producer attached no report shows only the notebook download", () => {
  render(<ElementList elements={[artifactToElement(uqArtifact({ has_report: false }))]} />);
  expect(screen.queryByTitle("uq_bank_worth.ipynb")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Download uq_bank_worth.ipynb notebook" })).toHaveAttribute(
    "href",
    "/api/artifacts/uq-7/content",
  );
});

test("a report that fails to load falls back to the notebook download", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 502 }));
  vi.stubGlobal("fetch", fetchMock);
  render(<ElementList elements={[artifactToElement(uqArtifact())]} />);

  fireEvent.load(screen.getByTitle("uq_bank_worth.ipynb"));

  expect(await screen.findByRole("status")).toHaveTextContent("The report could not be loaded.");
  expect(fetchMock).toHaveBeenCalledWith("/api/artifacts/uq-7/report", expect.objectContaining({ credentials: "same-origin" }));
  expect(screen.queryByTitle("uq_bank_worth.ipynb")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Download uq_bank_worth.ipynb notebook" })).toHaveAttribute(
    "href",
    "/api/artifacts/uq-7/content",
  );
});

test("a report that loads keeps the frame", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response("<html></html>", { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  render(<ElementList elements={[artifactToElement(uqArtifact())]} />);

  fireEvent.load(screen.getByTitle("uq_bank_worth.ipynb"));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  expect(screen.getByTitle("uq_bank_worth.ipynb").tagName).toBe("IFRAME");
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

test("a network error on the report check also falls back", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  render(<UQNotebookElement element={{ type: "custom", props: { reportUrl: "/r" } }} />);

  fireEvent.load(screen.getByTitle("UQ analysis"));

  expect(await screen.findByRole("status")).toHaveTextContent("The report could not be loaded.");
});

test("a report check aborted by unmounting is ignored", async () => {
  let signal: AbortSignal | undefined;
  let rejectFetch!: (e: unknown) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn((_url: string, init: RequestInit) => {
      signal = init.signal ?? undefined;
      return new Promise((_res, rej) => {
        rejectFetch = rej;
      });
    }),
  );
  const { unmount } = render(<UQNotebookElement element={{ type: "custom", props: { reportUrl: "/r" } }} />);
  fireEvent.load(screen.getByTitle("UQ analysis"));
  unmount();
  expect(signal?.aborted).toBe(true);
  const errors = vi.spyOn(console, "error").mockImplementation(() => {});
  rejectFetch(new DOMException("aborted", "AbortError"));
  await new Promise((r) => setTimeout(r, 0));
  expect(errors).not.toHaveBeenCalled(); // no state update after unmount
  errors.mockRestore();
});
