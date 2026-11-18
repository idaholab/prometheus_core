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
import { expect, test, vi } from "vitest";
import { VERSION_DETAILS } from "@/features/workflows/builder/builderPlaceholders";
import { VersionDetail } from "./VersionDetail.tsx";

const [V120] = VERSION_DETAILS;

test("the header shows the version, where it came from and Restore", () => {
  render(<VersionDetail detail={V120} />);

  expect(screen.getByRole("heading", { level: 2, name: "v1.2.0" })).toBeInTheDocument();
  expect(screen.getByText("comprehensive_material_analysis · derived from v1.1.0")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Restore this version" })).toBeInTheDocument();
});

test("each change reads with its kind, and the invalidation is shown", () => {
  render(<VersionDetail detail={V120} />);

  const changes = within(screen.getByRole("region", { name: "Changes in this version" })).getAllByRole("listitem");
  expect(changes.map((item) => item.textContent)).toEqual([
    "+Added: Added QA Gate checkpoint after the parallel analyses",
    "~Changed: SME Review moved below the new QA Gate",
  ]);
  expect(screen.getByRole("region", { name: "Invalidated by this change" })).toHaveTextContent(
    "3 cached runs of 'Synthesize Report' invalidated — downstream of the new checkpoint. Re-run required for provenance.",
  );
});

test("run history has a stat card for each figure, and the projects it ran in", () => {
  render(<VersionDetail detail={V120} />);

  const runs = screen.getByRole("region", { name: "Run history" });
  const cards = within(runs).getAllByRole("article");
  expect(cards.map((card) => card.textContent)).toEqual([
    "Total runs12since 2 days ago",
    "Last run4h agoThermal Analysis RC-7",
    "StatusActivecurrent latest",
  ]);
  const projects = within(within(runs).getByRole("list", { name: "Run in" })).getAllByRole("listitem");
  expect(projects.map((item) => item.textContent)).toEqual(["MARVEL Reactor Project9 runs", "Fuel Assembly QA — RC-73 runs"]);
});

test("Restore this version does nothing yet and logs no errors", async () => {
  const error = vi.spyOn(console, "error").mockImplementation(() => {});
  const user = userEvent.setup();
  render(<VersionDetail detail={V120} />);

  await user.click(screen.getByRole("button", { name: "Restore this version" }));

  expect(screen.getByRole("heading", { level: 2, name: "v1.2.0" })).toBeInTheDocument();
  expect(error).not.toHaveBeenCalled();
  error.mockRestore();
});
