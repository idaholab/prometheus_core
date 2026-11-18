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

import { isRouteErrorResponse, useRouteError } from "react-router";
import { Button } from "@/components/ui/Button";

/**
 * Shown in place of a route that threw while loading or rendering, so a crash
 * never leaves a blank screen. A full reload is the recovery, since the error
 * may have come from app state.
 */
export function PageError() {
  const error = useRouteError();
  if (import.meta.env.DEV) console.error(error);
  const detail = isRouteErrorResponse(error) ? `${error.status} ${error.statusText}` : null;
  return (
    <div role="alert" className="flex min-h-dvh flex-col items-center justify-center gap-3 bg-base-100 p-6 text-center">
      <h1 className="m-0 text-lg font-semibold text-base-content">Something went wrong</h1>
      <p className="m-0 text-sm text-base-content/60">Reload the page to try again.{detail ? ` (${detail})` : ""}</p>
      <Button variant="primary" size="sm" label="Reload" onClick={() => window.location.reload()} />
    </div>
  );
}
