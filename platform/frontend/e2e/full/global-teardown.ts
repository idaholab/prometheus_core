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

/* Runs once after the full-stack tests: deletes the session global-setup.ts
 * saved, so no live session cookie is left on disk. It leaves the run's folder:
 * a failed test's trace and screenshot are in it, and Playwright writes its own
 * .last-run.json there after this runs. */
import { rmSync } from "node:fs";
import { dirname } from "node:path";
import type { FullConfig } from "@playwright/test";

export default function globalTeardown(config: FullConfig) {
  rmSync(dirname(config.projects[0].use.storageState as string), { recursive: true, force: true });
}
