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

/* The Home layout's status rail width: collapsed, the card list, and wider while
 * an artifact viewer is open. Chat and the panel are stubbed; the stub panel
 * exposes the callbacks the layout passes it. */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { LayoutHome } from "./LayoutHome.tsx";

vi.mock("@/features/chat", () => ({ Chat: () => <div>chat</div> }));
vi.mock("./StatusPanel", () => ({
  StatusPanel: (props: {
    onCollapse: () => void;
    onExpand: () => void;
    onViewerOpenChange: (open: boolean) => void;
  }) => (
    <div>
      <button onClick={props.onCollapse}>collapse</button>
      <button onClick={props.onExpand}>expand</button>
      <button onClick={() => props.onViewerOpenChange(true)}>open viewer</button>
      <button onClick={() => props.onViewerOpenChange(false)}>close viewer</button>
    </div>
  ),
}));

const rail = () => screen.getByRole("complementary");

test("the rail is narrow for the card list and about half the width with a viewer open", async () => {
  const user = userEvent.setup();
  render(<LayoutHome statusCollapsed={false} onStatusCollapsedChange={() => {}} />);
  expect(rail()).toHaveClass("lg:w-96");

  await user.click(screen.getByText("open viewer"));
  expect(rail()).toHaveClass("lg:w-1/2");
  expect(rail()).not.toHaveClass("lg:w-96");

  await user.click(screen.getByText("close viewer"));
  expect(rail()).toHaveClass("lg:w-96");
});

test("a collapsed rail stays the icon strip, and the panel's toggles reach the page", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  render(<LayoutHome statusCollapsed onStatusCollapsedChange={onChange} />);
  expect(rail()).toHaveClass("w-16");

  await user.click(screen.getByText("collapse"));
  await user.click(screen.getByText("expand"));
  expect(onChange.mock.calls).toEqual([[true], [false]]);
});
