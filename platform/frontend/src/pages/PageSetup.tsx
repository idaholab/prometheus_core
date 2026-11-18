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

import { useNavigate } from "react-router";
import { PATHS } from "@/app/paths";
import { SetupWizard } from "@/features/auth";

/** First-run setup page: creates the first admin, then opens Home. */
export function PageSetup() {
  const navigate = useNavigate();
  return <SetupWizard onSuccess={() => navigate(PATHS.home, { replace: true })} />;
}
