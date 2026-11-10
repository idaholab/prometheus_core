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
import { buttonClassName, type ButtonSize, type ButtonStyle } from "./buttonStyle";

export type { ButtonSize, ButtonStyle, ButtonVariant } from "./buttonStyle";

/** Icon and spinner box per button size. The icon's SVG is stretched to fill
 * it (a class beats lucide's width/height attributes), so callers needn't
 * pass `size` to the icon. */
const ICON_SIZE_CLASSES: Record<ButtonSize, string> = {
  xs: "size-3",
  sm: "size-4.5",
  md: "size-5",
  lg: "size-6",
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

interface ButtonCommonProps extends ButtonStyle {
  onClick?: () => void;
  /**
   * Route to open on click. Not wired yet: until the router lands, buttons
   * that navigate should pass `onClick` instead.
   */
  navTo?: string;
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
  muted?: never;
}

interface IconButtonProps extends ButtonCommonProps {
  label?: never;
  icon: ReactNode;
  iconPosition?: never;
  /** Accessible name, also shown as the hover/focus tooltip. */
  ariaLabel: string;
  shape?: "square" | "circle";
  tooltipPlacement?: keyof typeof TOOLTIP_PLACEMENT_CLASSES;
  /**
   * Ghost only: dim the icon to 60% until hover (default). Pass `false` for a
   * one-off button outside an icon toolbar, e.g. the header bell.
   */
  muted?: boolean;
}

type ButtonProps = TextButtonProps | IconButtonProps;

/**
 * App-wide button on DaisyUI's `btn`. Pass `label` for a text button (with an
 * optional `icon`), or `icon` + `ariaLabel` for an icon-only one, which gets
 * a tooltip so its meaning isn't hidden from sighted users.
 *
 * Ghost icon buttons follow the rail style: muted until hovered (unless
 * `muted={false}`), primary only when `active`.
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

  // Ghost icon buttons use the rail style in place of btn-active
  const ghostState =
    iconOnly && variant === "ghost"
      ? active
        ? "bg-primary/15 text-primary"
        : props.muted === false
          ? ""
          : "text-base-content/60 hover:text-base-content"
      : undefined;

  const shape = iconOnly
    ? props.shape === "circle"
      ? "btn-circle"
      : "btn-square"
    : iconSlot && ICON_SIDE_PADDING_CLASSES[size][props.iconPosition ?? "left"];

  const classes = [buttonClassName(props, { shape, state: ghostState }), className].filter(Boolean).join(" ");

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
