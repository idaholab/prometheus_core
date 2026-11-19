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

import type { ArtifactMeta } from "@/lib/api/types";
import type { SampleRoutes } from "./sampleFetch";

/** One section of the viewer playground: a sample artifact and the files that answer its URLs. */
export interface ViewerCase {
  /** Section heading. */
  title: string;
  /** One line: what the case shows. */
  note: string;
  /** The custom element name the chat would mount, e.g. "MeshViewer". */
  viewer: string;
  /** What the backend sends in a chat turn. */
  artifact: ArtifactMeta;
  /** Backend URL path -> sample asset URL that answers it. */
  files: SampleRoutes;
}
