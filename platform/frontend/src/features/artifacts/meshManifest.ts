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

/** The MeshViewer props in a mesh body, or null when it can't render.
 *
 * The viewer needs `baseUrl` and a manifest naming at least one VTP file; anything
 * less (an error page parsed as JSON, an empty object, a manifest without files)
 * would mount a viewer with nothing to show. Used for inline `json_body`s and for the
 * props fetched from `mesh_url`. */
export function meshManifestProps(body: unknown): Record<string, unknown> | null {
  if (!body || typeof body !== "object") return null;
  const o = body as Record<string, unknown>;
  const manifest = o.manifest as { files?: unknown } | undefined;
  const files = manifest && typeof manifest === "object" ? manifest.files : undefined;
  if (typeof o.baseUrl !== "string" || !o.baseUrl || !Array.isArray(files) || files.length === 0) return null;
  return o;
}
