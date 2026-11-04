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

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { Button } from "./Button.tsx";
import { SplitButton, type SplitButtonOption } from "./SplitButton.tsx";

/** Modify Plan with its alternatives, recording what was picked. */
function setup(options?: Partial<SplitButtonOption>[]) {
  const picked: string[] = [];
  const items: SplitButtonOption[] = (
    options ?? [{ label: "Edit the template" }, { label: "Duplicate plan", disabled: true }, { label: "Export plan" }]
  ).map((o) => ({ label: o.label!, disabled: o.disabled, onClick: () => picked.push(o.label!) }));
  const main = vi.fn();
  render(<SplitButton label="Modify Plan" onClick={main} options={items} variant="primary" outline size="sm" />);
  return { main, picked, user: userEvent.setup(), arrow: () => screen.getByRole("button", { name: "More Modify Plan options" }) };
}

test("the main half runs the main action and leaves the menu closed", async () => {
  const { main, picked, user } = setup();
  await user.click(screen.getByRole("button", { name: "Modify Plan" }));
  expect(main).toHaveBeenCalledOnce();
  expect(picked).toEqual([]);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});

test("the arrow opens a menu of options, and picking one runs it and closes the menu", async () => {
  const { main, picked, user, arrow } = setup();
  expect(arrow()).toHaveAttribute("aria-haspopup", "menu");
  expect(arrow()).toHaveAttribute("aria-expanded", "false");

  await user.click(arrow());
  expect(arrow()).toHaveAttribute("aria-expanded", "true");
  const menu = screen.getByRole("menu", { name: "More Modify Plan options" });
  expect(screen.getAllByRole("menuitem").map((item) => item.textContent)).toEqual([
    "Edit the template",
    "Duplicate plan",
    "Export plan",
  ]);
  expect(menu).toContainElement(document.activeElement as HTMLElement);

  await user.click(screen.getByRole("menuitem", { name: "Export plan" }));
  expect(picked).toEqual(["Export plan"]);
  expect(main).not.toHaveBeenCalled();
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(arrow()).toHaveFocus();
});

test("a disabled option is announced as disabled and does nothing when clicked", async () => {
  const { picked, user, arrow } = setup();
  await user.click(arrow());
  const duplicate = screen.getByRole("menuitem", { name: "Duplicate plan" });
  expect(duplicate).toHaveAttribute("aria-disabled", "true");

  await user.click(duplicate);
  expect(picked).toEqual([]);
  expect(screen.getByRole("menu")).toBeInTheDocument();
});

test("the keyboard opens the menu, moves past disabled options, picks one, and Escape closes it", async () => {
  const { picked, user, arrow } = setup();
  arrow().focus();

  await user.keyboard("{Enter}");
  expect(screen.getByRole("menuitem", { name: "Edit the template" })).toHaveFocus();
  await user.keyboard("{ArrowDown}");
  expect(screen.getByRole("menuitem", { name: "Export plan" })).toHaveFocus();
  await user.keyboard("{ArrowDown}");
  expect(screen.getByRole("menuitem", { name: "Edit the template" })).toHaveFocus();
  await user.keyboard("{ArrowUp}");
  expect(screen.getByRole("menuitem", { name: "Export plan" })).toHaveFocus();
  await user.keyboard("{Home}");
  expect(screen.getByRole("menuitem", { name: "Edit the template" })).toHaveFocus();

  await user.keyboard("{Escape}");
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(arrow()).toHaveFocus();
  expect(picked).toEqual([]);

  await user.keyboard("{ArrowUp}");
  expect(screen.getByRole("menuitem", { name: "Export plan" })).toHaveFocus();
  await user.keyboard(" ");
  expect(picked).toEqual(["Export plan"]);
  expect(arrow()).toHaveFocus();
});

test("a click outside closes the menu without picking anything", async () => {
  const { picked, user, arrow } = setup();
  await user.click(arrow());
  await user.click(document.body);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(picked).toEqual([]);
});

test("disabled disables both halves", () => {
  render(<SplitButton label="Modify Plan" onClick={() => {}} options={[{ label: "Edit", onClick: () => {} }]} disabled />);
  expect(screen.getByRole("button", { name: "Modify Plan" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "More Modify Plan options" })).toBeDisabled();
});

test("each half has the same classes as a Button with the same style props", () => {
  render(
    <>
      <SplitButton label="Modify Plan" onClick={() => {}} options={[{ label: "Edit", onClick: () => {} }]} variant="primary" outline size="sm" />
      <Button label="Plain" variant="primary" outline size="sm" />
    </>,
  );
  const plain = screen.getByRole("button", { name: "Plain" }).className.split(" ");
  for (const name of ["Modify Plan", "More Modify Plan options"]) {
    const classes = screen.getByRole("button", { name }).className.split(" ");
    expect(classes).toEqual(expect.arrayContaining(plain));
    expect(classes).toContain("join-item");
  }
});
