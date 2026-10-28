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
 * Renders a `needs_info` turn's `FormField[]` and submits `followup_answers`
 * (keyed by `FormField.id`) via the next `POST /api/chat/messages`.
 *
 * Replaces the Chainlit `askUserState`-driven DynamicForm: the form is just data now.
 */

import { useState } from "react";
import type { FormField } from "@/lib/api/types";
import { Button } from "@/components/ui/Button";

function initialValues(fields: FormField[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    if (f.default !== undefined && f.default !== null) {
      out[f.id] = f.default;
    } else if (f.input_type === "checkbox") {
      out[f.id] = false;
    } else if (f.input_type === "select") {
      out[f.id] = f.options?.[0]?.value ?? "";
    } else {
      out[f.id] = "";
    }
  }
  return out;
}

export function FollowupForm({
  fields,
  disabled,
  onSubmit,
}: {
  fields: FormField[];
  disabled?: boolean;
  onSubmit: (answers: Record<string, unknown>) => void;
}) {
  const [values, setValues] = useState<Record<string, unknown>>(() => initialValues(fields));

  const setValue = (id: string, v: unknown) => setValues((prev) => ({ ...prev, [id]: v }));

  const missingRequired = fields.some(
    (f) => f.required && (values[f.id] === "" || values[f.id] === undefined || values[f.id] === null),
  );

  const renderField = (f: FormField) => {
    const common = {
      id: f.id,
      disabled,
      className: "input input-bordered input-sm w-full",
      value: String(values[f.id] ?? ""),
      onChange: (e: React.ChangeEvent<HTMLInputElement>) => setValue(f.id, e.target.value),
    };
    switch (f.input_type) {
      case "textarea":
        return (
          <textarea
            id={f.id}
            disabled={disabled}
            rows={f.rows ?? 3}
            placeholder={f.placeholder ?? ""}
            className="textarea textarea-bordered textarea-sm w-full"
            value={String(values[f.id] ?? "")}
            onChange={(e) => setValue(f.id, e.target.value)}
          />
        );
      case "select":
        return (
          <select
            id={f.id}
            disabled={disabled}
            className="select select-bordered select-sm w-full"
            value={String(values[f.id] ?? "")}
            onChange={(e) => setValue(f.id, e.target.value)}
          >
            {(f.options ?? []).map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        );
      case "checkbox":
        return (
          <input
            id={f.id}
            type="checkbox"
            disabled={disabled}
            className="checkbox checkbox-sm"
            checked={Boolean(values[f.id])}
            onChange={(e) => setValue(f.id, e.target.checked)}
          />
        );
      case "number":
        return (
          <input
            {...common}
            type="number"
            placeholder={f.placeholder ?? ""}
            min={f.min ?? undefined}
            max={f.max ?? undefined}
            step={f.step ?? undefined}
            onChange={(e) => setValue(f.id, e.target.value === "" ? "" : Number(e.target.value))}
          />
        );
      default:
        return (
          <input
            {...common}
            type={f.input_type === "password" ? "password" : f.input_type === "email" ? "email" : f.input_type === "date" ? "date" : f.input_type === "datetime" ? "datetime-local" : "text"}
            placeholder={f.placeholder ?? ""}
          />
        );
    }
  };

  return (
    <form
      className="mt-2 space-y-3 rounded-xl border border-base-300 bg-base-200 p-4 max-w-xl"
      onSubmit={(e) => {
        e.preventDefault();
        if (!disabled && !missingRequired) onSubmit(values);
      }}
    >
      {fields.map((f) => (
        <div key={f.id} className="space-y-1">
          <label htmlFor={f.id} className="flex items-center gap-2 text-sm font-medium">
            {f.label}
            {f.required && <span className="text-error">*</span>}
          </label>
          {renderField(f)}
          {f.help && <p className="text-xs text-base-content/60">{f.help}</p>}
        </div>
      ))}
      <Button variant="primary" size="sm" type="submit" label="Submit" disabled={disabled || missingRequired} />
    </form>
  );
}
