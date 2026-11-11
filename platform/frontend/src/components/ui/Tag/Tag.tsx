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

import type { LucideIcon } from "lucide-react";

interface TagProps {
  label: string;
  /** Tells tags of one kind apart without colour, e.g. Shield for admin roles, User for the rest. */
  icon?: LucideIcon;
  /** Monospace, for identifiers such as source types or IDs rather than words. */
  mono?: boolean;
  /** Layout only (margins, alignment); styling is fixed. */
  className?: string;
}

/**
 * Outlined label for what something is (a role, a type), as opposed to StatusPill,
 * which says how something is doing. No fill or dot, so it never reads as a status.
 * Same height and radius as StatusPill so the two line up in a row.
 * Casing is applied with CSS, so pass ordinary text.
 */
export function Tag({ label, icon: Icon, mono = false, className = "" }: TagProps) {
  // border-base-300 is darker than the page in dark theme and draws a near-black line;
  // a faint base-content border is lighter than the page in both themes (Figma border/default).
  // Padding is 1px less than Figma's because CSS borders sit outside the padding.
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded border border-base-content/10 px-[5px] py-px text-[10px] uppercase leading-3 tracking-[0.02em] text-base-content/70 ${mono ? "font-mono" : ""} ${className}`}
    >
      {Icon && <Icon aria-hidden="true" size={10} strokeWidth={2} className="shrink-0" />}
      {label}
    </span>
  );
}
