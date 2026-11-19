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

import { Link } from "react-router";
import { PATHS } from "@/app/paths";

/** Shown inside the app shell for a URL no route matches. */
export function PageNotFound() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center">
      <h2 className="m-0 text-lg font-semibold text-base-content">This page does not exist</h2>
      <p className="m-0 text-sm text-base-content/60">Check the address, or go back to Home.</p>
      <Link to={PATHS.home} className="link link-primary text-sm">
        Go to Home
      </Link>
    </div>
  );
}
