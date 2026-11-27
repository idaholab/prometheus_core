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

import { ApiError } from "@/lib/api/client";

/** How long to wait for the backend before offering Retry. It converts on the first
 * request (up to two minutes per conversion, after any queue), so this is generous. */
export const MESH_FETCH_TIMEOUT_MS = 5 * 60 * 1000;

/** What a failed fetch tells the user: the backend's reason for a conversion failure,
 * and plain words for everything else (network errors, status texts, timeouts). */
export function meshFailureMessage(err: unknown, timedOut: boolean): string {
  if (timedOut) return "Preparing the mesh took too long. Try again, or download the file.";
  if (err instanceof ApiError) {
    if (err.status === 401) return "Your session has ended. Sign in again to view this mesh.";
    if (err.status === 422 && err.message) return err.message;
  }
  return "The mesh couldn't be prepared. Try again, or download the file.";
}
