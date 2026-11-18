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

import { useId, type FormEvent, type InputHTMLAttributes, type ReactNode } from "react";

interface AuthLayoutProps {
  title: string;
  subtitle?: ReactNode;
  onSubmit: () => void;
  children: ReactNode;
}

/**
 * Shared shell for the pre-auth screens (<Login>, <SetupWizard>).
 * Page background + brand lockup on the left, form card on the right.
 * Stacks vertically below `lg`, side-by-side at `lg` and up.
 */
export function AuthLayout({ title, subtitle, onSubmit, children }: AuthLayoutProps) {
  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    onSubmit();
  };

  return (
    <div className="relative min-h-dvh bg-base-100 overflow-x-hidden">
      {/* Background: radial glow + grid overlay */}
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_60%_50%,rgba(79,70,229,0.15),transparent_70%)]" />
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_20%_80%,rgba(99,102,241,0.08),transparent_60%)]" />
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.02)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.02)_1px,transparent_1px)] bg-size-[64px_64px]" />

      <div className="relative mx-auto grid min-h-dvh w-full max-w-6xl items-center gap-10 px-6 py-12 lg:grid-cols-2 lg:gap-16 lg:px-12">
        {/* Brand lockup */}
        <div className="flex justify-center lg:justify-start">
          <div className="flex w-fit flex-col items-center text-center ">
            <img
              src="/logo_dark.png"
              alt="Prometheus"
              className="w-72 max-w-full sm:w-96 lg:w-md"
            />
            <span className="-mt-4.5 text-base text-base-content/50 sm:text-lg">
              AI orchestration for nuclear engineering
            </span>
          </div>
        </div>

        {/* Form card */}
        <div className="w-full max-w-md justify-self-center lg:justify-self-end">
          <form
            onSubmit={handleSubmit}
            noValidate
            className="card bg-base-200 rounded-box border border-base-300 p-6 sm:p-8 space-y-5 shadow-2xl shadow-black/70"
          >
            <div className="space-y-1">
              <h1 className="text-xl font-semibold text-base-content">{title}</h1>
              {subtitle && <p className="text-sm text-base-content/60">{subtitle}</p>}
            </div>
            {children}
          </form>
        </div>
      </div>
    </div>
  );
}

interface AuthFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "id" | "className"> {
  label: string;
}

/** Label + input pair with consistent spacing and styling. */
export function AuthField({ label, ...inputProps }: AuthFieldProps) {
  const id = useId();
  return (
    <div className="space-y-2">
      <label htmlFor={id} className="label">
        <span className="label-text text-xs uppercase tracking-wider text-base-content">{label}</span>
      </label>
      <input id={id} className="input input-bordered w-full" {...inputProps} />
    </div>
  );
}

/** Inline error banner; renders nothing when `message` is empty. */
export function AuthError({ message }: { message: string }) {
  if (!message) return null;
  return (
    <div role="alert" className="alert alert-error text-xs">
      {message}
    </div>
  );
}