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

import { useEffect, useState } from "react";
import { Provider } from "react-redux";
import { RouterProvider } from "react-router";
import { endSession } from "@/app/endSession";
import { loginPathFor, PATHS } from "@/app/paths";
import { createAppRouter } from "@/app/router";
import { onUnauthorized } from "@/lib/api/baseApi";
import { appStore } from "@/lib/api/store";

type AppRouter = ReturnType<typeof createAppRouter>;

/** A request found the session gone: end it, then Login, and back to this page after. */
function sendToLogin(router: AppRouter): void {
  const { pathname, search } = router.state.location;
  // Already there (several requests can 401 at once): nothing more to do
  if (pathname === PATHS.login) return;
  void endSession("lost", () => router.navigate(loginPathFor(pathname + search), { replace: true }));
}

/**
 * The app: every screen is a route (app/router.tsx). Sign-in, first-run setup
 * and the admin check are route guards (app/guards.ts), which replaced the
 * boot state machine that used to live here.
 *
 * Server data goes through the Redux store's RTK Query cache (lib/api). A 401
 * from any of its requests means the session is gone: forget the user and go to
 * Login, then back to this page after signing in, as a lost chat session does.
 */
export default function App() {
  // Created once, on first render, so importing this module has no side effects.
  const [router] = useState(createAppRouter);

  useEffect(() => {
    onUnauthorized(() => sendToLogin(router));
    return () => onUnauthorized(null);
  }, [router]);

  return (
    <Provider store={appStore}>
      <RouterProvider router={router} />
    </Provider>
  );
}
