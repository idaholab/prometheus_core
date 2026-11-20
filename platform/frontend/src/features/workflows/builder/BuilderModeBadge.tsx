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

import { Check, ChevronDown } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { buttonClassName } from "@/components/ui/Button";
import { BUILDER_MODES, type BuilderMode } from "@/features/workflows/builderMode";

/** The badge's tone. Text stays base-content so it passes AA on the tint in both themes. */
const TONE_CLASSES = {
  info: { badge: "border-info/60 bg-info/10 hover:border-info hover:bg-info/20", dot: "bg-info" },
  warning: { badge: "border-warning/60 bg-warning/10 hover:border-warning hover:bg-warning/20", dot: "bg-warning" },
} as const;

const MODES: BuilderMode[] = ["run", "template"];

interface BuilderModeBadgeProps {
  mode: BuilderMode;
  /** Shown under the "the template" option, e.g. "Change Comprehensive Material Analysis for everyone". */
  workflowName: string;
  onChange?: (mode: BuilderMode) => void;
}

/**
 * The Builder's mode badge (Figma PPLT-409 D.2a, D.2b), which is also the
 * switch: "Changing: this run" in the info tone or "Changing: the template"
 * in the warning tone, opening a menu of both modes.
 *
 * Follows the WAI-ARIA menu button pattern, like SplitButton: the menu takes
 * focus on the current mode; Up/Down move, Enter or Space picks, Escape or a
 * click outside closes it and Escape returns focus to the badge, Tab closes
 * it. Picking a mode calls `onChange`; LayoutWorkflowBuilder asks first before
 * leaving unsaved template changes (D.2d).
 */
export function BuilderModeBadge({ mode, workflowName, onChange }: BuilderModeBadgeProps) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const badgeRef = useRef<HTMLButtonElement>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const menuId = useId();
  const { badge, tone } = BUILDER_MODES[mode];

  const close = (refocus: boolean) => {
    setOpen(false);
    if (refocus) badgeRef.current?.focus();
  };

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  useEffect(() => {
    if (open) itemRefs.current[active]?.focus();
  }, [open, active]);

  const openMenu = () => {
    setActive(MODES.indexOf(mode));
    setOpen(true);
  };

  const pick = (option: BuilderMode) => {
    close(true);
    if (option !== mode) onChange?.(option);
  };

  const onMenuKeyDown = (event: KeyboardEvent) => {
    if (event.key === "Tab") {
      close(false);
      return;
    }
    const step = event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : 0;
    if (step) {
      event.preventDefault();
      setActive((active + step + MODES.length) % MODES.length);
    } else if (event.key === "Escape") {
      event.preventDefault();
      close(true);
    }
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={badgeRef}
        type="button"
        className={buttonClassName({ size: "sm" }, { shape: `gap-2 font-normal ${TONE_CLASSES[tone].badge}` })}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => (open ? close(true) : openMenu())}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            openMenu();
          }
        }}
      >
        <span aria-hidden="true" className={`size-1.5 shrink-0 rounded-full ${TONE_CLASSES[tone].dot}`} />
        {/* Sizes go on each span: the base layer sets span font-size, so it isn't inherited. */}
        <span className="text-xs text-base-content/70">Changing:</span>
        <span className="-ml-1 text-xs font-semibold text-base-content">{badge}</span>
        <ChevronDown aria-hidden className={`size-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <ul
          id={menuId}
          role="menu"
          aria-label="Builder mode"
          onKeyDown={onMenuKeyDown}
          className="menu menu-panel absolute top-full left-0 z-20 mt-1 w-72 p-1"
        >
          {MODES.map((option, i) => {
            const copy = BUILDER_MODES[option];
            const descriptionId = `${menuId}-description-${i}`;
            return (
              <li key={option} role="none">
                <button
                  ref={(element) => {
                    itemRefs.current[i] = element;
                  }}
                  type="button"
                  role="menuitemradio"
                  aria-checked={option === mode}
                  aria-describedby={descriptionId}
                  tabIndex={i === active ? 0 : -1}
                  onClick={() => pick(option)}
                  onMouseEnter={() => setActive(i)}
                  // Same highlight and focus ring as SplitButton's options
                  className={[
                    // DaisyUI lays menu items out in columns; grid-flow-row puts the description under the label
                    "grid grid-flow-row grid-cols-[1fr_auto] items-start gap-x-2 gap-y-0",
                    "focus-visible:outline-solid focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-base-content",
                    "hover:bg-primary/15 hover:text-base-content focus-visible:bg-primary/15 focus-visible:text-base-content",
                  ].join(" ")}
                >
                  {copy.option}
                  {option === mode ? <Check aria-hidden className="size-4 text-base-content" /> : <span />}
                  <span id={descriptionId} className="col-span-2 text-xs text-base-content/60">
                    {copy.description(workflowName)}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
