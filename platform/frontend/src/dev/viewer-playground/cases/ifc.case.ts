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

import modelIfc from "@viewer-samples/model.ifc?url";
import type { ViewerCase } from "@/dev/viewer-playground/viewerCase";

const ifcCase: ViewerCase = {
  title: "IFC model",
  note: "A stored IFC4 file; IFCViewer fetches it from the content URL and parses it with web-ifc.",
  viewer: "IFCViewer",
  artifact: {
    artifact_id: "sample-ifc",
    name: "model.ifc",
    mime_type: "model/ifc",
    description: "Sample building model (IFC4)",
    tags: ["ifc", "bim"],
    json_body: null,
    render_hint: "ifc",
  },
  files: {
    "/api/artifacts/sample-ifc/content": modelIfc,
  },
};

export default ifcCase;
