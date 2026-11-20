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

/**
 * The route table (React Router data mode). Paths come from ./paths; access
 * comes from the loaders in ./guards, which run before a route renders. To add
 * a screen: add its path to PATHS, a pages/PageX.tsx, and an entry here.
 */
import { createBrowserRouter, type RouteObject } from "react-router";
import { LayoutApp } from "@/layouts/LayoutApp";
import { PageAdmin } from "@/pages/PageAdmin";
import { PageAgentRegistry } from "@/pages/PageAgentRegistry";
import { PageApprovalQueue } from "@/pages/PageApprovalQueue";
import { PageDataManagement } from "@/pages/PageDataManagement";
import { PageError } from "@/pages/PageError";
import { PageJobsConsole } from "@/pages/PageJobsConsole";
import { PageLogin } from "@/pages/PageLogin";
import { PageNotFound } from "@/pages/PageNotFound";
import { PageProjectManagement } from "@/pages/PageProjectManagement";
import { PageSetup } from "@/pages/PageSetup";
import { PageWorkflows } from "@/pages/PageWorkflows";
import { guestOnly, requireAdmin, requireUser, setupOnly } from "./guards";
import { PATHS } from "./paths";

/** Child paths are relative to the shell's "/". */
const child = (path: string) => path.slice(1);

export const routes: RouteObject[] = [
  {
    errorElement: <PageError />,
    // Nothing renders until the guards answer, as before the router.
    hydrateFallbackElement: null,
    children: [
      { path: PATHS.login, loader: guestOnly, element: <PageLogin /> },
      { path: PATHS.setup, loader: setupOnly, element: <PageSetup /> },
      {
        path: PATHS.home,
        loader: requireUser,
        element: <LayoutApp />,
        children: [
          // Home itself is rendered by LayoutApp, which keeps it mounted.
          { index: true, element: null },
          { path: child(PATHS.agentRegistry), element: <PageAgentRegistry /> },
          { path: child(PATHS.workflows), element: <PageWorkflows /> },
          { path: child(PATHS.approvalQueue), element: <PageApprovalQueue /> },
          { path: child(PATHS.projectManagement), element: <PageProjectManagement /> },
          { path: child(PATHS.dataManagement), element: <PageDataManagement /> },
          { path: child(PATHS.jobsConsole), element: <PageJobsConsole /> },
          { path: child(PATHS.admin), loader: requireAdmin, element: <PageAdmin /> },
          { path: "*", element: <PageNotFound /> },
        ],
      },
    ],
  },
];

export function createAppRouter() {
  return createBrowserRouter(routes);
}
