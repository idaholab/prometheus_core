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

/**
 * Pure metric formatters for the agent registry card, free of React
 * (so `node --test` can load them).
 */

/** An uptime percentage as `99.8%`. */
export function formatUptime(p: number): string {
  return `${p}%`;
}

/** A latency in milliseconds as `42ms`. */
export function formatLatency(ms: number): string {
  return `${ms}ms`;
}

/** A version string as `V1.4`. */
export function formatVersion(v: string): string {
  return `V${v}`;
}
