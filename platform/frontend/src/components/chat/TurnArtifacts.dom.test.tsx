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

/* The chat transcript folds a turn's per-sample artifacts the same way the
 * Artifacts tab does: results render as viewers, the rest in one closed list. */
import { render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import type { ArtifactMeta } from "@/lib/api/types";
import { TurnArtifacts } from "./TurnArtifacts.tsx";

vi.mock("@/lib/api/client", () => ({
  api: { artifactContentUrl: (id: string) => `/api/artifacts/${id}/content` },
}));
// The real ElementList pulls in every viewer (three.js and all); a stand-in that
// lists the elements it is handed is enough to see what the turn renders inline.
vi.mock("../ElementRenderer", () => ({
  ElementList: ({ elements }: { elements?: { id: string; name?: string }[] }) => (
    <ul aria-label="inline viewers">
      {(elements ?? []).map((e) => (
        <li key={e.id}>{e.name}</li>
      ))}
    </ul>
  ),
}));

function fileArtifact(artifact_id: string, name: string, tags: string[]): ArtifactMeta {
  return {
    artifact_id,
    name,
    mime_type: "application/octet-stream",
    json_type: null,
    description: "",
    uri: null,
    tags,
    json_body: null,
    render_hint: "file",
    citation: null,
    producer_agent_id: null,
    created_at: null,
  } as ArtifactMeta;
}

const RESULT = fileArtifact("res-1", "bank_worth_summary.bin", ["uq"]);
const SAMPLES = [
  fileArtifact("cfg-1", "sample_001.yaml", ["uq-sample"]),
  fileArtifact("zdo-1", "sample_001.zdo", ["zdo"]),
  fileArtifact("log-1", "sample_002_failure.log", ["failure", "diagnostics"]),
];

test("per-sample artifacts fold under the turn's results", () => {
  render(<TurnArtifacts artifacts={[SAMPLES[0], RESULT, ...SAMPLES.slice(1)]} />);

  const perSample = screen.getByText("3 per-sample files (configs, ZDOs, logs)").closest("details")!;
  expect(perSample).not.toHaveAttribute("open");
  for (const a of SAMPLES) {
    expect(within(perSample).getByRole("link", { name: a.name })).toHaveAttribute(
      "href",
      `/api/artifacts/${a.artifact_id}/content`,
    );
  }
  // Only the result reaches the inline viewers.
  const inline = screen.getByRole("list", { name: "inline viewers" });
  expect(within(inline).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
    "bank_worth_summary.bin",
  ]);
});

test("a turn with no per-sample artifacts shows no fold", () => {
  render(<TurnArtifacts artifacts={[RESULT]} />);
  expect(within(screen.getByRole("list", { name: "inline viewers" })).getByText("bank_worth_summary.bin")).toBeInTheDocument();
  expect(screen.queryByText(/per-sample files/)).not.toBeInTheDocument();
});
