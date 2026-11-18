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

import diagram from "@viewer-samples/diagram.mmd?raw";
import type { ViewerCase } from "@/dev/viewer-playground/viewerCase";

const mermaidCase: ViewerCase = {
  title: "Mermaid diagram",
  note: "An inline Mermaid source in json_body; MermaidViewer draws it without a fetch.",
  viewer: "MermaidViewer",
  artifact: {
    artifact_id: "sample-mermaid",
    name: "workflow.mmd",
    mime_type: "text/mermaid",
    description: "Sample analysis workflow",
    tags: ["diagram", "mermaid"],
    json_body: diagram,
    render_hint: "mermaid",
  },
  files: {},
};

export default mermaidCase;
