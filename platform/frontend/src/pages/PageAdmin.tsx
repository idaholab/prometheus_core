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
import { LayoutAdmin, type AdminSubTab } from "@/features/admin";

/**
 * Admin page: owns which sub-tab is showing. The admin guard on its route
 * keeps everyone else out. The sub-tabs get their own URLs in PPLT-240.
 */
export function PageAdmin() {
  const [subTab, setSubTab] = useState<AdminSubTab>("users");
  return <LayoutAdmin subTab={subTab} onSubTabChange={setSubTab} />;
}
