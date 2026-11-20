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
import { expect, test } from "vitest";
import { PageApprovalQueue } from "./PageApprovalQueue.tsx";

test("approval queue: lists the checkpoints and opens the first one", () => {
  render(<PageApprovalQueue />);

  const queue = within(screen.getByRole("region", { name: "Checkpoint queue" })).getAllByRole("list")[0];
  expect(within(queue).getAllByRole("listitem", { hidden: false }).filter((li) => li.parentElement === queue)).toHaveLength(4);
  expect(screen.getByRole("region", { name: "Checkpoint details" })).toHaveTextContent("Mesh Validation - Fuel Assembly RC-7");
});
