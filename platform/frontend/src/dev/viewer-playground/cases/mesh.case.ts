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

import jsonBody from "@viewer-samples/mesh/json_body.json";
import surfaceT0000 from "@viewer-samples/mesh/surface_t0000.vtp?url";
import type { ViewerCase } from "@/dev/viewer-playground/viewerCase";

// The sample asset for each file name that the manifest lists.
const samples: Record<string, string> = {
  "surface_t0000.vtp": surfaceT0000,
};

const meshCase: ViewerCase = {
  title: "Mesh (STL via the backend conversion)",
  note: "An STL converted by the backend mesh service; MeshViewer loads the VTP that its manifest lists.",
  viewer: "MeshViewer",
  artifact: {
    artifact_id: "sample-mesh",
    name: "part.stl",
    mime_type: "model/stl",
    description: "Sample part (STL)",
    tags: ["mesh", "stl"],
    json_body: jsonBody,
    render_hint: "mesh",
  },
  files: Object.fromEntries(
    jsonBody.manifest.files.map((file) => [`${jsonBody.baseUrl}/${file.filename}`, samples[file.filename]]),
  ),
};

export default meshCase;
