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

import { X } from "lucide-react";

interface ErrorToastProps {
  /** What went wrong, e.g. "Type mismatch: mesh → material_data". */
  message: string;
  /** Layout only (positioning, margins). */
  className?: string;
}

/**
 * Error notice (Figma D.6): a red-tinted box with an error mark and a mono
 * message. It's an alert, so screen readers announce it when it appears.
 * Display only: it has no close button or timeout yet.
 */
export function ErrorToast({ message, className = "" }: ErrorToastProps) {
  return (
    <div
      role="alert"
      className={`flex min-h-25 items-center gap-2.5 rounded-lg border border-error/70 bg-error/15 px-4 py-3 ${className}`}
    >
      <X size={14} aria-hidden="true" className="shrink-0 text-error" />
      <p className="m-0 font-mono text-[11px] text-base-content">{message}</p>
    </div>
  );
}
