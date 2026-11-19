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

import { useRef, type KeyboardEvent } from "react";

export interface Tab<T extends string = string> {
  id: T;
  label: string;
}

interface TabsProps<T extends string> {
  tabs: Tab<T>[];
  selected: T;
  onChange: (id: T) => void;
  /** Accessible name for the tab list, e.g. "Checkpoint details". */
  label: string;
  /** id of the tabpanel the tabs control. */
  panelId?: string;
  /**
   * - `underline`: tabs on a faint full-width rule, the selected one underlined
   *   in primary (Figma E.1).
   * - `pill`: no rule, the selected tab filled, for a toolbar, e.g. the
   *   Builder's Canvas and History (PPLT-409 D.2a to D.2c).
   */
  variant?: "underline" | "pill";
  /** Layout only (margins, alignment); styling comes from `variant`. */
  className?: string;
}

const TAB_CLASSES = {
  underline: {
    tab: "border-b-2 pb-2.5 pt-1",
    selected: "border-primary font-medium text-base-content",
    unselected: "border-transparent text-base-content/60 hover:text-base-content",
  },
  pill: {
    tab: "rounded-md px-3 py-1.5",
    selected: "bg-base-content/10 font-medium text-base-content",
    unselected: "text-base-content/60 hover:bg-base-content/5 hover:text-base-content",
  },
} as const;

/**
 * Tab row, underlined (Figma E.1) or as pills (PPLT-409 D.2a). Props only: `selected` decides the active tab and
 * `onChange` reports a click or arrow key. The caller renders the panel.
 *
 * Follows the WAI-ARIA tabs pattern: only the selected tab is in the Tab order,
 * and Left/Right/Home/End move between tabs. When the tabs don't fit, the row
 * scrolls sideways rather than widening the page.
 */
export function Tabs<T extends string>({
  tabs,
  selected,
  onChange,
  label,
  panelId,
  variant = "underline",
  className = "",
}: TabsProps<T>) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const classes = TAB_CLASSES[variant];

  const handleKeyDown = (event: KeyboardEvent, index: number) => {
    const last = tabs.length - 1;
    const next =
      event.key === "ArrowRight"
        ? index === last ? 0 : index + 1
        : event.key === "ArrowLeft"
          ? index === 0 ? last : index - 1
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? last
              : null;
    if (next === null) return;
    event.preventDefault();
    refs.current[next]?.focus();
    onChange(tabs[next].id);
  };

  // The rule is a positioned pseudo-element on the wrapper; the scroller is
  // positioned too and comes later, so the selected tab's underline paints over it.
  const rule =
    variant === "underline" ? "before:absolute before:inset-x-0 before:bottom-0 before:h-px before:bg-base-content/10" : "";
  return (
    <div className={`relative min-w-0 ${rule} ${className}`}>
      <div
        role="tablist"
        aria-label={label}
        className={`relative flex overflow-x-auto ${variant === "underline" ? "gap-6" : "gap-1"}`}
      >
        {tabs.map((tab, index) => {
          const isSelected = tab.id === selected;
          return (
            <button
              key={tab.id}
              ref={(el) => {
                refs.current[index] = el;
              }}
              type="button"
              role="tab"
              aria-selected={isSelected}
              aria-controls={panelId}
              tabIndex={isSelected ? 0 : -1}
              onClick={() => onChange(tab.id)}
              onKeyDown={(event) => handleKeyDown(event, index)}
              className={`shrink-0 cursor-pointer whitespace-nowrap text-[13px] transition-colors ${classes.tab} ${
                isSelected ? classes.selected : classes.unselected
              }`}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
