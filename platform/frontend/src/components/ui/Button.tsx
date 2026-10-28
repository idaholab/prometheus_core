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

/** Icon and spinner box per button size. The icon's SVG is stretched to fill
 * it (a class beats lucide's width/height attributes), so callers needn't
 * pass `size` to the icon. */
const ICON_SIZE_CLASSES: Record<ButtonSize, string> = {
  xs: "size-3",
  sm: "size-4",
  md: "size-4",
  lg: "size-5",
};

/** Padding on the icon side of an icon-and-text button, about 3/4 of DaisyUI's
 * `--btn-p`. Even padding looks wider next to an icon than next to text, since
 * the icon is lighter and its SVG has empty space at its edges. */
const ICON_SIDE_PADDING_CLASSES: Record<ButtonSize, { left: string; right: string }> = {
  xs: { left: "ps-1.5", right: "pe-1.5" },
  sm: { left: "ps-2.5", right: "pe-2.5" },
  md: { left: "ps-3", right: "pe-3" },
  lg: { left: "ps-4", right: "pe-4" },
};

const TOOLTIP_PLACEMENT_CLASSES = {
  top: "tooltip-top",
  bottom: "tooltip-bottom",
  left: "tooltip-left",
  right: "tooltip-right",
} as const;

interface ButtonCommonProps {
  /** Omit for DaisyUI's default (base) button. */
  variant?: ButtonVariant;
  size?: ButtonSize;
  onClick?: () => void;
  /**
   * Route to open on click. Not wired yet: until the router lands, buttons
   * that navigate should pass `onClick` instead.
   */
  navTo?: string;
  /** Selected/pressed state, e.g. the current tab in a rail. */
  active?: boolean;
  /** Full width of the container. */
  wide?: boolean;
  soft?: boolean;
  outline?: boolean;
  disabled?: boolean;
  /** Swaps the icon (or, with no icon, leads the label) for a spinner. */
  loading?: boolean;
  type?: "button" | "submit" | "reset";
  /** Layout only (margins, positioning); styling comes from the props above. */
  className?: string;
}

interface TextButtonProps extends ButtonCommonProps {
  /** Visible text, which is also the accessible name. */
  label: string;
  icon?: ReactNode;
  iconPosition?: "left" | "right";
  ariaLabel?: never;
  shape?: never;
  tooltipPlacement?: never;
}

interface IconButtonProps extends ButtonCommonProps {
  label?: never;
  icon: ReactNode;
  iconPosition?: never;
  /** Accessible name, also shown as the hover/focus tooltip. */
  ariaLabel: string;
  shape?: "square" | "circle";
  tooltipPlacement?: keyof typeof TOOLTIP_PLACEMENT_CLASSES;
}

type ButtonProps = TextButtonProps | IconButtonProps;

/**
 * App-wide button on DaisyUI's `btn`. Pass `label` for a text button (with an
 * optional `icon`), or `icon` + `ariaLabel` for an icon-only one, which gets
 * a tooltip so its meaning isn't hidden from sighted users.
 *
 * Ghost icon buttons follow the rail style: muted until hovered, primary only
 * when `active`.
 */
export function Button(props: ButtonProps) {
  const {
    label,
    icon,
    variant,
    size = "md",
    onClick,
    active = false,
    wide = false,
    soft = false,
    outline = false,
    disabled = false,
    loading = false,
    type = "button",
    className = "",
  } = props;
  const iconOnly = label === undefined;

  // TODO(router): wire up navTo once the router lands; until then, buttons
  // that navigate pass onClick.
  // const navigate = useNavigate();
  const handleClick = () => {
    onClick?.();
    // if (!onClick && props.navTo) navigate(props.navTo);
  };

  const iconSize = ICON_SIZE_CLASSES[size];
  const iconSlot = loading ? (
    <span className={`loading loading-spinner ${iconSize}`} aria-hidden />
  ) : icon ? (
    <span className={`flex shrink-0 [&>svg]:size-full ${iconSize}`} aria-hidden>
      {icon}
    </span>
  ) : null;

  const ghostIcon = iconOnly && variant === "ghost";
  const stateClass = ghostIcon
    ? active
      ? "bg-primary/15 text-primary"
      : "text-base-content/60 hover:text-base-content"
    : active
      ? "btn-active"
      : "";

  const classes = [
    "btn",
    variant && VARIANT_CLASSES[variant],
    SIZE_CLASSES[size],
    iconOnly && (props.shape === "circle" ? "btn-circle" : "btn-square"),
    !iconOnly && iconSlot && ICON_SIDE_PADDING_CLASSES[size][props.iconPosition ?? "left"],
    soft && "btn-soft",
    outline && "btn-outline",
    wide && "btn-block",
    stateClass,
    className,
  ]
    .filter(Boolean)
    .join(" ");

  const button = (
    <button
      type={type}
      className={classes}
      onClick={handleClick}
      disabled={disabled || loading}
      aria-label={iconOnly ? props.ariaLabel : undefined}
      aria-pressed={active || undefined}
      aria-busy={loading || undefined}
    >
      {props.iconPosition === "right" ? (
        <>
          {label}
          {iconSlot}
        </>
      ) : (
        <>
          {iconSlot}
          {label}
        </>
      )}
    </button>
  );

  if (!iconOnly) return button;

  // The tooltip lives on a wrapper: DaisyUI shows it on hover or when anything
  // inside has keyboard focus, and a disabled button gets no hover of its own.
  return (
    <span
      className={`tooltip ${TOOLTIP_PLACEMENT_CLASSES[props.tooltipPlacement ?? "top"]} ${wide ? "w-full" : ""}`}
      data-tip={props.ariaLabel}
    >
      {button}
    </span>
  );
}
