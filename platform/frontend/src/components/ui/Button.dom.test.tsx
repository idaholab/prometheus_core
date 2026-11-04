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

/* Button.test.ts pins what Button renders; this checks what a click does,
 * which needs a live React tree. */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Bell } from "lucide-react";
import { expect, test, vi } from "vitest";
import { Button } from "./Button.tsx";

test("a click calls onClick, for text and icon-only buttons", async () => {
  const user = userEvent.setup();
  const save = vi.fn();
  const notify = vi.fn();
  render(
    <>
      <Button label="Save" onClick={save} />
      <Button icon={<Bell />} ariaLabel="Notifications" onClick={notify} />
    </>,
  );

  await user.click(screen.getByRole("button", { name: "Save" }));
  await user.click(screen.getByRole("button", { name: "Notifications" }));
  expect(save).toHaveBeenCalledOnce();
  expect(notify).toHaveBeenCalledOnce();
});

test("a disabled or loading button ignores clicks", async () => {
  const user = userEvent.setup();
  const onClick = vi.fn();
  render(
    <>
      <Button label="Save" onClick={onClick} disabled />
      <Button label="Send" onClick={onClick} loading />
    </>,
  );

  await user.click(screen.getByRole("button", { name: "Save" }));
  await user.click(screen.getByRole("button", { name: "Send" }));
  expect(onClick).not.toHaveBeenCalled();
});

test("a button with no onClick can be clicked without error", async () => {
  const user = userEvent.setup();
  render(<Button label="Later" />);
  await user.click(screen.getByRole("button", { name: "Later" }));
  expect(screen.getByRole("button", { name: "Later" })).toBeEnabled();
});
