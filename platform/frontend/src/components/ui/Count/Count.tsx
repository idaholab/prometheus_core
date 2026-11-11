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

interface CountProps {
  count: number;
  /** Singular noun, e.g. "member". */
  noun: string;
  /** Defaults to `${noun}s`. */
  plural?: string;
  /** Layout only (margins, alignment); styling is fixed. */
  className?: string;
}

/**
 * Small neutral count, e.g. "1 member" / "2 members" (Figma F.1).
 * Same height and radius as StatusPill and Tag. Sentence case, since it reads as a phrase.
 */
export function Count({ count, noun, plural = `${noun}s`, className = "" }: CountProps) {
  return (
    <span
      className={`inline-flex shrink-0 items-center whitespace-nowrap rounded bg-base-content/10 px-1.5 py-0.5 text-[10px] leading-3 text-base-content/70 ${className}`}
    >
      {count} {count === 1 ? noun : plural}
    </span>
  );
}
