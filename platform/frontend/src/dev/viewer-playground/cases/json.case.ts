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

import results from "@viewer-samples/results.json?url";
import type { ViewerCase } from "@/dev/viewer-playground/viewerCase";

const jsonCase: ViewerCase = {
  title: "JSON (fetched from the content URL)",
  note: "A stored JSON file with no inline body; CollapsibleJson fetches it from the content URL (PPLT-374).",
  viewer: "CollapsibleJson",
  artifact: {
    artifact_id: "sample-json",
    name: "results.json",
    mime_type: "application/json",
    description: "Sample thermal analysis results",
    tags: ["json", "results"],
    json_body: null,
    render_hint: "json",
  },
  files: {
    "/api/artifacts/sample-json/content": results,
  },
};

export default jsonCase;
