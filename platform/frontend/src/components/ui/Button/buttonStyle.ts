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

/* The shared button look: Button and SplitButton both style themselves with
 * buttonClassName, so they can't drift apart. Kept out of Button.tsx so that
 * file exports only components, which Fast Refresh needs. */

export type ButtonVariant =
  | "neutral"
  | "primary"
  | "secondary"
  | "accent"
  | "info"
  | "success"
  | "warning"
  | "error"
  | "ghost";

export type ButtonSize = "xs" | "sm" | "md" | "lg";

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  neutral: "btn-neutral",
  primary: "btn-primary",
  secondary: "btn-secondary",
  accent: "btn-accent",
  info: "btn-info",
  success: "btn-success",
  warning: "btn-warning",
  error: "btn-error",
  ghost: "btn-ghost",
};

const SIZE_CLASSES: Record<ButtonSize, string> = {
  xs: "btn-xs",
  sm: "btn-sm",
  md: "btn-md",
  lg: "btn-lg",
};

/** The props that set how a button looks, shared by Button and SplitButton. */
export interface ButtonStyle {
  /** Omit for DaisyUI's default (base) button. */
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Selected/pressed state, e.g. the current tab in a rail. */
  active?: boolean;
  /** Full width of the container. */
  wide?: boolean;
  soft?: boolean;
  outline?: boolean;
  /**
   * With `outline` and no `variant`: a faint border and dimmed text that
   * brighten on hover, for secondary actions that shouldn't compete with the
   * page, e.g. Request Revision and the preview toolbar (Figma E.1).
   */
  subtle?: boolean;
}

/**
 * The DaisyUI classes for a button with this style. Button and SplitButton
 * both use it, so a control built from it looks the same as a Button with the
 * same props. `shape` takes classes that size or pad the button itself (icon
 * squares, icon-side padding), and `state` replaces the default `btn-active`,
 * e.g. for the ghost rail style; both stay with the caller.
 */
export function buttonClassName(
  { variant, size = "md", active = false, wide = false, soft = false, outline = false, subtle = false }: ButtonStyle,
  { shape, state }: { shape?: string | false | null; state?: string } = {},
): string {
  return [
    "btn",
    variant && VARIANT_CLASSES[variant],
    SIZE_CLASSES[size],
    shape,
    soft && "btn-soft",
    outline && "btn-outline",
    // DaisyUI's btn hover fills with base-200 darkened and sets the border to
    // match, which on the dark theme turns a neutral outline button into a
    // dark block with no outline. Keep the border and use a faint tint of the
    // text color instead. Utilities outrank DaisyUI's layer.
    outline && !variant && !subtle && "hover:border-base-content hover:bg-base-content/8",
    // Same faint border as cards and Tag, brightening on hover
    outline &&
      subtle &&
      !variant &&
      "border-base-content/15 text-base-content/70 hover:border-base-content/30 hover:bg-base-content/8 hover:text-base-content",
    wide && "btn-block",
    state ?? (active && "btn-active"),
  ]
    .filter(Boolean)
    .join(" ");
}
