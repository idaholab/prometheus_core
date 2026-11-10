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

// Category key must match IFCViewerEngine.CATEGORY_IFC_CLASSES / CATEGORY_NAME_PATTERNS.
export const VISIBILITY_TOGGLES = [
  { key: "walls",   label: "Walls" },
  { key: "floors",  label: "Floors" },
  { key: "columns", label: "Columns" },
  { key: "beams",   label: "Beams" },
  { key: "doors",   label: "Doors" },
  { key: "windows", label: "Windows" },
  { key: "roofs",   label: "Roof" },
] as const;

export type VisibilityCategory = typeof VISIBILITY_TOGGLES[number]["key"];
