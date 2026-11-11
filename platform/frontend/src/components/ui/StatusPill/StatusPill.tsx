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
 * - `success`: healthy or live, e.g. online, connected, active (Figma C.1, G.1, F.1).
 * - `info`: informational, nothing to act on, e.g. invited (F.1).
 * - `progress`: work under way, e.g. syncing (G.1).
 * - `warning`: needs attention soon.
 * - `error`: failed, blocked or urgent, e.g. disconnected, suspended, urgent (G.1, F.1, E.1).
 * - `neutral`: inactive or default, e.g. offline, standard (C.1, E.1).
 */
export type StatusPillTone = "success" | "info" | "progress" | "warning" | "error" | "neutral";

/** Tinted background plus a dot in the tone colour. Text stays base-content so it passes AA in both themes. */
const TONE_CLASSES: Record<StatusPillTone, { pill: string; dot: string }> = {
  success: { pill: "bg-success/10", dot: "bg-success" },
  info: { pill: "bg-info/10", dot: "bg-info" },
  progress: { pill: "bg-primary/15", dot: "bg-primary" },
  warning: { pill: "bg-warning/10", dot: "bg-warning" },
  error: { pill: "bg-error/10", dot: "bg-error" },
  neutral: { pill: "bg-base-content/10", dot: "bg-base-content/40" },
};

interface StatusPillProps {
  label: string;
  tone: StatusPillTone;
  /** Layout only (margins, alignment); styling comes from `tone`. */
  className?: string;
}

/**
 * Small status label with a coloured dot. Casing is applied with CSS, so pass ordinary text.
 * The label carries the meaning; the dot is decorative, so colour is never the only signal.
 */
export function StatusPill({ label, tone, className = "" }: StatusPillProps) {
  const classes = TONE_CLASSES[tone];
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded px-2 py-0.5 text-[10px] uppercase leading-3 text-base-content ${classes.pill} ${className}`}
    >
      <span aria-hidden="true" className={`size-1.5 shrink-0 rounded-full ${classes.dot}`} />
      {label}
    </span>
  );
}
