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

import { useState } from "react";
import { RouterProvider } from "react-router";
import { createAppRouter } from "@/app/router";

/**
 * The app: every screen is a route (app/router.tsx). Sign-in, first-run setup
 * and the admin check are route guards (app/guards.ts), which replaced the
 * boot state machine that used to live here.
 */
export default function App() {
  // Created once, on first render, so importing this module has no side effects.
  const [router] = useState(createAppRouter);
  return <RouterProvider router={router} />;
}
