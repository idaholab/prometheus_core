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

/** A run time in seconds as `45s`, `5m 20s` or `1h 15m`; a zero lower unit is dropped. */
export function formatRunTime(s: number): string {
  if (s < 60) return `${s}s`;
  if (s < 3600) {
    const minutes = Math.floor(s / 60);
    const seconds = s % 60;
    return seconds === 0 ? `${minutes}m` : `${minutes}m ${seconds}s`;
  }
  const hours = Math.floor(s / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  return minutes === 0 ? `${hours}h` : `${hours}h ${minutes}m`;
}

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
