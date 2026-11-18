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

import { useNavigate, useSearchParams } from "react-router";
import { safeNextPath } from "@/app/paths";
import { Login } from "@/features/auth";

/** Login page: once signed in, opens the page the visitor asked for. */
export function PageLogin() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  return <Login onSuccess={() => navigate(safeNextPath(params.get("next")), { replace: true })} />;
}
