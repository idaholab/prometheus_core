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

import type { ReactNode } from "react";

/**
 * - `default`: section heading on content screens, including info panels,
 *   e.g. "CONNECTED DATA SOURCES" (Figma G.1, F.1, E.1).
 * - `panel`: small mono heading in the Builder's tool panels, e.g. "SKILL LIBRARY" (D.2).
 */
export type SectionLabelVariant = "default" | "panel";

const VARIANT_CLASSES: Record<SectionLabelVariant, string> = {
  default: "text-xs text-base-content/60",
  panel: "font-mono text-[9px] tracking-[0.04em] text-base-content/50",
};

interface SectionLabelProps {
  children: ReactNode;
  variant?: SectionLabelVariant;
  /** Heading level for the page outline. Header owns the h1. */
  as?: "h2" | "h3" | "h4";
  /** Layout only (margins, alignment); styling comes from `variant`. */
  className?: string;
}

/**
 * Uppercase section heading. Casing is applied with CSS, so pass ordinary text:
 * screen readers then read it as words instead of spelling out capitals.
 */
export function SectionLabel({
  children,
  variant = "default",
  as: Heading = "h2",
  className = "",
}: SectionLabelProps) {
  return (
    <Heading
      className={`m-0 font-normal uppercase leading-normal ${VARIANT_CLASSES[variant]} ${className}`}
    >
      {children}
    </Heading>
  );
}
