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

import { Activity, Box, Database, FileText, Grid3x3, Shield, Thermometer, Wind, type LucideIcon } from "lucide-react";
import type { AgentIcon } from "./store/agents";

/** The lucide icon for each agent icon key of the store. */
export const AGENT_ICONS: Record<AgentIcon, LucideIcon> = {
  box: Box,
  grid: Grid3x3,
  activity: Activity,
  wind: Wind,
  thermometer: Thermometer,
  shield: Shield,
  database: Database,
  "file-text": FileText,
};
