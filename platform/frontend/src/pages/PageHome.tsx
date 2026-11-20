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
import { LayoutHome } from "@/features/dashboard";

/**
 * Home page: owns the status rail state. LayoutApp keeps it mounted while
 * another section is showing, so Chat keeps its scroll position and any
 * streaming reply. That is also why it must not call `usePageHeader`.
 */
export function PageHome() {
  const [statusCollapsed, setStatusCollapsed] = useState(false);
  return <LayoutHome statusCollapsed={statusCollapsed} onStatusCollapsedChange={setStatusCollapsed} />;
}
