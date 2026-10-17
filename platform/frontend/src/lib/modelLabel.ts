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

import type { ConfigResponse } from "./api/types.ts";

/** The composer label for the active LLM model, or null when the model is unknown. */
export function modelLabel(config: ConfigResponse | null): string | null {
  const model = config?.llm_model?.trim();
  return model ? `Model: ${model}` : null;
}
