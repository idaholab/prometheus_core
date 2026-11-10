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

import { Fragment } from "react";
import { Bell, ChevronDown, LogOut, Moon, Settings, Sun } from "lucide-react";
import { usePageHeaderOverride } from "../lib/store/pageHeader";
import { useTheme } from "../lib/useTheme";
import { useCurrentUser } from "@/features/auth/store/session";
import { Button } from "@/components/ui/Button";

interface Props {
  /** Active section label. Drives the breadcrumb and page title unless the
   * page overrides them with `usePageHeader`. */
  title: string;
  onLogout: () => void;
  onToggleSettings?: () => void;
}

function initials(identifier?: string): string {
  if (!identifier) return "?";
  const base = identifier.split("@")[0];
  const parts = base.split(/[.\-_ ]+/).filter(Boolean);
  const chars = parts.length >= 2 ? parts[0][0] + parts[1][0] : base.slice(0, 2);
  return chars.toUpperCase();
}

/**
 * App header (Figma): breadcrumb + page title on the left; notifications and a
 * user-profile dropdown on the right. Theme toggle, settings, and logout —
 * previously standalone icon buttons — are preserved inside the dropdown.
 */
export function Header({ title, onLogout, onToggleSettings }: Props) {
  const [theme, setTheme] = useTheme();
  const nextTheme = theme === "light" ? "dark" : "light";
  const user = useCurrentUser();
  const override = usePageHeaderOverride();

  const crumbs = [title, ...(override?.trail ?? [])];
  const pageTitle = override?.title ?? crumbs[crumbs.length - 1];

  return (
    <header className="flex h-16 shrink-0 items-center justify-between gap-3 border-b border-base-300 bg-base-200 px-6">
      {/* min-w-0 lets a long title truncate on narrow screens instead of
          wrapping out of the fixed-height bar. */}
      <div className="flex min-w-0 flex-col gap-0.5">
        <nav aria-label="Breadcrumb">
          <ol className="flex min-w-0 items-center gap-1 overflow-hidden whitespace-nowrap text-[10px] text-base-content/40">
            <li>INL / Prometheus</li>
            {crumbs.map((crumb, i) => {
              const current = i === crumbs.length - 1;
              return (
                <Fragment key={i}>
                  <li aria-hidden="true">/</li>
                  <li className={current ? "text-primary" : undefined} aria-current={current ? "page" : undefined}>
                    {crumb}
                  </li>
                </Fragment>
              );
            })}
          </ol>
        </nav>
        <h1 className="m-0 truncate text-lg font-bold text-base-content" title={pageTitle}>
          {pageTitle}
        </h1>
      </div>

      <div className="flex shrink-0 items-center gap-3">
        <Button variant="ghost" size="sm" icon={<Bell />} ariaLabel="Notifications" tooltipPlacement="bottom" muted={false} />
        <div className="h-6 w-px bg-base-300" />
        <div className="dropdown dropdown-end">
          <div
            tabIndex={0}
            role="button"
            className="flex items-center gap-2 rounded-md p-1.5 transition-colors hover:bg-base-300 cursor-pointer"
          >
            <div className="flex size-8 items-center justify-center rounded-full bg-primary/20 text-xs font-semibold text-primary">
              {initials(user?.identifier)}
            </div>
            <div className="hidden flex-col text-left sm:flex">
              <span className="text-[13px] font-semibold leading-tight text-base-content">
                {user?.identifier ?? "User"}
              </span>
              {user?.role && (
                <span className="text-[10px] uppercase leading-tight text-base-content/50">
                  {user.role}
                </span>
              )}
            </div>
            <ChevronDown size={14} className="text-base-content/50" />
          </div>
          <ul
            tabIndex={0}
            className="menu menu-panel dropdown-content z-10 mt-2 w-48 p-2"
          >
            <li>
              <button onClick={() => setTheme(nextTheme)}>
                {theme === "light" ? <Moon size={16} /> : <Sun size={16} />}
                {theme === "light" ? "Dark theme" : "Light theme"}
              </button>
            </li>
            {onToggleSettings && (
              <li>
                <button onClick={onToggleSettings}>
                  <Settings size={16} />
                  Settings
                </button>
              </li>
            )}
            <li>
              <button onClick={onLogout}>
                <LogOut size={16} />
                Log out
              </button>
            </li>
          </ul>
        </div>
      </div>
    </header>
  );
}
