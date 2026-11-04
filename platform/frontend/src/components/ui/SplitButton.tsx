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

import { ChevronDown } from "lucide-react";
import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { buttonClassName, type ButtonStyle } from "./buttonStyle";

export interface SplitButtonOption {
  label: string;
  onClick: () => void;
  disabled?: boolean;
}

interface SplitButtonProps extends Omit<ButtonStyle, "active"> {
  /** The main action's visible text, which is also its accessible name. */
  label: string;
  onClick: () => void;
  /** The alternatives in the dropdown. */
  options: SplitButtonOption[];
  /** Accessible name for the arrow; defaults to "More <label> options". */
  menuLabel?: string;
  /** Disables both halves. */
  disabled?: boolean;
  /** Layout only (margins, positioning); styling comes from the props above. */
  className?: string;
}

const ARROW_SIZE_CLASSES = { xs: "size-3", sm: "size-3.5", md: "size-4", lg: "size-5" } as const;

/**
 * A main action joined to a dropdown of alternatives, e.g. Modify Plan with
 * "Edit the template" in the menu. Both halves use buttonClassName, so it
 * looks the same as a Button with the same props.
 *
 * Follows the WAI-ARIA menu button pattern: the arrow opens a menu, which
 * takes focus. Up/Down/Home/End move between options, skipping disabled
 * ones; Enter or Space picks one; Escape or Tab closes the menu. Escape
 * returns focus to the arrow. A click outside closes it too.
 */
export function SplitButton({
  label,
  onClick,
  options,
  menuLabel,
  disabled = false,
  className = "",
  ...style
}: SplitButtonProps) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  // Which way the menu opens, so it stays inside the viewport
  const [placement, setPlacement] = useState({ up: false, start: false });
  const rootRef = useRef<HTMLDivElement>(null);
  const arrowRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLUListElement>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const menuId = useId();

  const enabled = options.flatMap((option, i) => (option.disabled ? [] : [i]));

  const close = (refocus: boolean) => {
    setOpen(false);
    if (refocus) arrowRef.current?.focus();
  };

  const openAt = (index: number) => {
    setActive(index);
    setOpen(true);
  };

  // Close on a click or tap outside the control
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  // Flip the menu up or to the left when there's no room below or to the right
  useLayoutEffect(() => {
    if (!open || !rootRef.current || !menuRef.current) return;
    const root = rootRef.current.getBoundingClientRect();
    const menu = menuRef.current.getBoundingClientRect();
    setPlacement({
      up: root.bottom + menu.height > window.innerHeight && root.top > menu.height,
      start: root.left + menu.width > window.innerWidth,
    });
  }, [open]);

  // The menu takes focus when it opens, and focus follows the active option
  useEffect(() => {
    if (open) itemRefs.current[active]?.focus();
  }, [open, active]);

  const move = (from: number, step: 1 | -1) => {
    if (enabled.length === 0) return;
    const at = enabled.indexOf(from);
    const next = at === -1 ? (step === 1 ? 0 : enabled.length - 1) : (at + step + enabled.length) % enabled.length;
    setActive(enabled[next]);
  };

  const pick = (option: SplitButtonOption) => {
    if (option.disabled) return;
    close(true);
    option.onClick();
  };

  const onArrowKeyDown = (event: KeyboardEvent) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (enabled.length) openAt(event.key === "ArrowDown" ? enabled[0] : enabled[enabled.length - 1]);
    }
  };

  const onMenuKeyDown = (event: KeyboardEvent) => {
    const keys: Record<string, () => void> = {
      ArrowDown: () => move(active, 1),
      ArrowUp: () => move(active, -1),
      Home: () => enabled.length && setActive(enabled[0]),
      End: () => enabled.length && setActive(enabled[enabled.length - 1]),
      Escape: () => close(true),
    };
    if (event.key === "Tab") {
      close(false);
      return;
    }
    const action = keys[event.key];
    if (!action) return;
    event.preventDefault();
    action();
  };

  const size = style.size ?? "md";
  const half = (shape: string) => buttonClassName(style, { shape: `join-item ${shape}` });

  return (
    <div
      ref={rootRef}
      className={`relative inline-flex ${style.wide ? "w-full" : ""} ${className}`.trim()}
    >
      <div className={`join ${style.wide ? "w-full" : ""}`}>
        <button
          type="button"
          className={half(style.wide ? "flex-1" : "")}
          onClick={onClick}
          disabled={disabled}
        >
          {label}
        </button>
        <button
          ref={arrowRef}
          type="button"
          className={half("btn-square")}
          aria-label={menuLabel ?? `More ${label} options`}
          aria-haspopup="menu"
          aria-expanded={open}
          aria-controls={open ? menuId : undefined}
          disabled={disabled || options.length === 0}
          onClick={() => (open ? close(true) : enabled.length && openAt(enabled[0]))}
          onKeyDown={onArrowKeyDown}
        >
          <ChevronDown
            aria-hidden
            className={`${ARROW_SIZE_CLASSES[size]} transition-transform ${open ? "rotate-180" : ""}`}
          />
        </button>
      </div>
      {open && (
        <ul
          ref={menuRef}
          id={menuId}
          role="menu"
          aria-label={menuLabel ?? `More ${label} options`}
          onKeyDown={onMenuKeyDown}
          className={[
            "menu menu-panel absolute z-20 min-w-full w-max p-1",
            placement.up ? "bottom-full mb-1" : "top-full mt-1",
            placement.start ? "right-0" : "left-0",
          ].join(" ")}
        >
          {options.map((option, i) => (
            <li key={option.label} role="none" className={option.disabled ? "menu-disabled" : undefined}>
              <button
                ref={(element) => {
                  itemRefs.current[i] = element;
                }}
                type="button"
                role="menuitem"
                tabIndex={i === active ? 0 : -1}
                aria-disabled={option.disabled || undefined}
                onClick={() => pick(option)}
                onMouseEnter={() => !option.disabled && setActive(i)}
                // The sidebar's active-item style for the highlighted option, a
                // primary tint with base-content text, so the menu reads as a
                // pick-one list like the rail. Primary text or a primary focus
                // ring on it falls below AA contrast on the dark theme (2.5:1),
                // so text and ring use base-content. DaisyUI's menu sets
                // outline-style: none on focus, which outline-2 alone doesn't
                // undo, so keyboard focus sets the style as well
                className={
                  option.disabled
                    ? "whitespace-nowrap"
                    : "whitespace-nowrap hover:bg-primary/15 hover:text-base-content focus-visible:bg-primary/15 focus-visible:text-base-content focus-visible:outline-solid focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-base-content"
                }
              >
                {option.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
