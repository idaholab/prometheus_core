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

import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { Button } from "@/components/ui/Button";
import { SplitButton, type SplitButtonOption } from "./SplitButton.tsx";

/** Modify Plan with its alternatives, recording what was picked. */
function setup(options?: Partial<SplitButtonOption>[]) {
  const picked: string[] = [];
  const items: SplitButtonOption[] = (
    options ?? [{ label: "Edit the template" }, { label: "Duplicate plan", disabled: true }, { label: "Export plan" }]
  ).map((o) => ({ ...o, label: o.label!, onClick: () => picked.push(o.label!) }));
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

test("End jumps to the last enabled option, and Tab closes the menu without refocusing the arrow", async () => {
  const { user, arrow } = setup([{ label: "Edit the template" }, { label: "Export plan" }, { label: "Archive plan", disabled: true }]);
  await user.click(arrow());

  await user.keyboard("{End}");
  expect(screen.getByRole("menuitem", { name: "Export plan" })).toHaveFocus();

  await user.keyboard("{Tab}");
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(arrow()).not.toHaveFocus();
});

/** A DOMRect for jsdom, which doesn't lay anything out. */
const rect = (left: number, top: number, width: number, height: number) =>
  ({ left, top, width, height, right: left + width, bottom: top + height, x: left, y: top, toJSON: () => ({}) }) as DOMRect;

test("the menu opens up and to the left when it would leave the viewport", async () => {
  // A 400x300 window with the button in its bottom-right corner, and a
  // 200x120 menu, which fits neither below nor to the right
  vi.stubGlobal("innerWidth", 400);
  vi.stubGlobal("innerHeight", 300);
  const measure = vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    return this.getAttribute("role") === "menu" ? rect(0, 0, 200, 120) : rect(300, 250, 90, 32);
  });
  try {
    const { user, arrow } = setup();
    await user.click(arrow());
    expect(screen.getByRole("menu")).toHaveClass("bottom-full", "right-0");

    // Back in the top-left corner, it opens down and to the right
    await user.keyboard("{Escape}");
    measure.mockImplementation(function (this: HTMLElement) {
      return this.getAttribute("role") === "menu" ? rect(0, 0, 200, 120) : rect(10, 10, 90, 32);
    });
    await user.click(arrow());
    expect(screen.getByRole("menu")).toHaveClass("top-full", "left-0");
  } finally {
    measure.mockRestore();
    vi.unstubAllGlobals();
  }
});

test("clicking the arrow again closes the menu, and wide stretches the main half", async () => {
  const user = userEvent.setup();
  render(<SplitButton label="Modify Plan" onClick={() => {}} options={[{ label: "Edit", onClick: () => {} }]} wide />);
  const arrow = screen.getByRole("button", { name: "More Modify Plan options" });

  await user.click(arrow);
  expect(screen.getByRole("menu")).toBeInTheDocument();
  await user.click(arrow);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(arrow).toHaveFocus();

  expect(screen.getByRole("button", { name: "Modify Plan" })).toHaveClass("flex-1", "btn-block");
});

test("with every option disabled, the menu still opens and keys move through the options, but none runs", async () => {
  const { picked, main, user, arrow } = setup([
    { label: "Edit the template", disabled: true },
    { label: "Export plan", disabled: true },
  ]);
  expect(arrow()).toBeEnabled();

  await user.click(arrow());
  expect(screen.getByRole("menu")).toBeInTheDocument();
  expect(screen.getByRole("menuitem", { name: "Edit the template" })).toHaveFocus();

  await user.keyboard("{ArrowDown}");
  expect(screen.getByRole("menuitem", { name: "Export plan" })).toHaveFocus();
  await user.keyboard("{Enter}");
  await user.click(screen.getByRole("menuitem", { name: "Edit the template" }));
  expect(picked).toEqual([]);
  expect(main).not.toHaveBeenCalled();
  expect(screen.getByRole("menu")).toBeInTheDocument();

  // From the keyboard too, Up opens it on the last option
  await user.keyboard("{Escape}");
  await user.keyboard("{ArrowUp}");
  expect(screen.getByRole("menuitem", { name: "Export plan" })).toHaveFocus();
});

test("a disabled option's reason is shown under it and read out with it", async () => {
  const { user, arrow } = setup([
    { label: "Edit the template" },
    { label: "Propose new version", disabled: true, disabledReason: "Approve the plan first" },
  ]);
  await user.click(arrow());

  const option = screen.getByRole("menuitem", { name: /Propose new version/ });
  expect(option).toHaveAccessibleDescription("Approve the plan first");
  expect(screen.getByText("Approve the plan first")).toBeVisible();
  // An enabled option has no description
  expect(screen.getByRole("menuitem", { name: "Edit the template" })).not.toHaveAccessibleDescription();
});

test("an enabled option ignores disabledReason", async () => {
  const { user, arrow } = setup([{ label: "Edit the template", disabledReason: "Not shown" }]);
  await user.click(arrow());
  expect(screen.queryByText("Not shown")).not.toBeInTheDocument();
  expect(screen.getByRole("menuitem", { name: "Edit the template" })).not.toHaveAccessibleDescription();
});

test("with no options, the arrow is disabled and its keys open nothing", () => {
  render(<SplitButton label="Modify Plan" onClick={() => {}} options={[]} />);
  const arrow = screen.getByRole("button", { name: "More Modify Plan options" });
  expect(arrow).toBeDisabled();
  expect(screen.getByRole("button", { name: "Modify Plan" })).toBeEnabled();

  // A disabled button can't be focused or clicked by a person, so fire the
  // key events at it directly: the guards behind the arrow must still hold
  fireEvent.keyDown(arrow, { key: "ArrowDown" });
  fireEvent.keyDown(arrow, { key: "ArrowUp" });
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});

test("if every option is removed while the menu is open, the keys do nothing", async () => {
  const user = userEvent.setup();
  const one: SplitButtonOption[] = [{ label: "Edit the template", onClick: () => {} }];
  const { rerender } = render(<SplitButton label="Modify Plan" onClick={() => {}} options={one} />);
  await user.click(screen.getByRole("button", { name: "More Modify Plan options" }));
  const menu = screen.getByRole("menu");

  rerender(<SplitButton label="Modify Plan" onClick={() => {}} options={[]} />);
  for (const key of ["ArrowDown", "ArrowUp", "Home", "End"]) fireEvent.keyDown(menu, { key });
  expect(screen.getByRole("menu")).toBeInTheDocument();
  expect(screen.queryAllByRole("menuitem")).toEqual([]);

  // The keys left the focused position alone, so when the option comes back
  // it is the one in the Tab order again
  rerender(<SplitButton label="Modify Plan" onClick={() => {}} options={one} />);
  expect(screen.getByRole("menuitem", { name: "Edit the template" })).toHaveAttribute("tabindex", "0");
});

test("if the focused option becomes disabled while the menu is open, the keys move to the enabled ones", async () => {
  const user = userEvent.setup();
  const options = (firstDisabled: boolean): SplitButtonOption[] => [
    { label: "Edit the template", onClick: () => {}, disabled: firstDisabled },
    { label: "Duplicate plan", onClick: () => {} },
    { label: "Export plan", onClick: () => {} },
  ];
  const { rerender } = render(<SplitButton label="Modify Plan" onClick={() => {}} options={options(false)} />);
  await user.click(screen.getByRole("button", { name: "More Modify Plan options" }));
  expect(screen.getByRole("menuitem", { name: "Edit the template" })).toHaveFocus();

  // The focused option turns disabled, e.g. after a permission change
  rerender(<SplitButton label="Modify Plan" onClick={() => {}} options={options(true)} />);
  await user.keyboard("{ArrowDown}");
  expect(screen.getByRole("menuitem", { name: "Duplicate plan" })).toHaveFocus();

  rerender(<SplitButton label="Modify Plan" onClick={() => {}} options={options(false)} />);
  await user.keyboard("{Home}");
  rerender(<SplitButton label="Modify Plan" onClick={() => {}} options={options(true)} />);
  await user.keyboard("{ArrowUp}");
  expect(screen.getByRole("menuitem", { name: "Export plan" })).toHaveFocus();
});

test("Down on the arrow opens the menu on the first enabled option", async () => {
  const { user, arrow } = setup([{ label: "Duplicate plan", disabled: true }, { label: "Edit the template" }, { label: "Export plan" }]);
  arrow().focus();
  await user.keyboard("{ArrowDown}");
  expect(screen.getByRole("menuitem", { name: "Edit the template" })).toHaveFocus();
});
