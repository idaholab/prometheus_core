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

/* DataTable.test.ts checks what the table draws; this checks that clicking a
 * header re-sorts it, which only happens with a live React tree. */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import { DataTable } from "./DataTable.tsx";

type Person = { id: string; name: string; seen: string | null };
const PEOPLE: Person[] = [
  { id: "1", name: "Sarah Chen", seen: "2026-10-03" },
  { id: "2", name: "Aris Thorne", seen: null },
  { id: "3", name: "Elena Rostova", seen: "2026-10-05" },
];
const COLUMNS = [
  { id: "name", header: "Name", value: (p: Person) => p.name, sortable: true },
  { id: "seen", header: "Seen", value: (p: Person) => p.seen, sortable: true },
];

/** The name in each body row, top to bottom. */
const names = () =>
  screen
    .getAllByRole("row")
    .slice(1)
    .map((row) => within(row).getAllByRole("cell")[0].textContent);

test("clicking a sortable header sorts by it, then reverses, then clears", async () => {
  const user = userEvent.setup();
  render(<DataTable data={PEOPLE} columns={COLUMNS} rowId={(p) => p.id} label="People" />);
  const name = screen.getByRole("columnheader", { name: "Name" });

  expect(names()).toEqual(["Sarah Chen", "Aris Thorne", "Elena Rostova"]);
  expect(name).not.toHaveAttribute("aria-sort");

  await user.click(screen.getByRole("button", { name: "Name" }));
  expect(name).toHaveAttribute("aria-sort", "ascending");
  expect(names()).toEqual(["Aris Thorne", "Elena Rostova", "Sarah Chen"]);

  await user.click(screen.getByRole("button", { name: "Name" }));
  expect(name).toHaveAttribute("aria-sort", "descending");
  expect(names()).toEqual(["Sarah Chen", "Elena Rostova", "Aris Thorne"]);

  await user.click(screen.getByRole("button", { name: "Name" }));
  expect(name).not.toHaveAttribute("aria-sort");
  expect(names()).toEqual(["Sarah Chen", "Aris Thorne", "Elena Rostova"]);
});

test("sorting a column with an empty value keeps that row last", async () => {
  const user = userEvent.setup();
  render(<DataTable data={PEOPLE} columns={COLUMNS} rowId={(p) => p.id} label="People" />);

  await user.click(screen.getByRole("button", { name: "Seen" }));
  expect(names()).toEqual(["Sarah Chen", "Elena Rostova", "Aris Thorne"]);
});
