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
 * src/viewers/ThermalAnalysisElement.tsx
 *
 * Renders cl.CustomElement(name="ThermalAnalysisViewer") payloads.
 *
 * Wire contract (backend: thermal analysis plugin __init__.py):
 *   props: {
 *     name: string
 *     description: string
 *     analysis: Record<string, unknown>  // arbitrary nested JSON, no fixed schema
 *   }
 *
 * `analysis` has no strict schema beyond a handful of conventionally-present
 * keys (material_id, status, operating_temperature_c, thermal_stress_mpa,
 * thermal_fatigue_usage_factor, confidence, cycle_categories,
 * fatigue_analysis, creep_analysis, recommendations). Anything else nested
 * inside falls through to the recursive ValueTree renderer, same as the
 * original plugin.
 */

import type { ViewerProps } from "@/features/artifacts/elements";

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function formatLabel(key: string): string {
  return String(key || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Not provided";
  if (typeof value === "number") {
    if (value !== 0 && Math.abs(value) < 0.001) return value.toExponential(2);
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// ---------------------------------------------------------------------------
// Recursive value renderer
// ---------------------------------------------------------------------------

function ValueTree({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    return (
      <ul className="ml-4 mt-2 list-disc space-y-1.5">
        {value.map((item, index) => (
          <li key={index}>
            {isPlainObject(item) || Array.isArray(item) ? (
              <ValueTree value={item} />
            ) : (
              formatValue(item)
            )}
          </li>
        ))}
      </ul>
    );
  }

  if (isPlainObject(value)) {
    return (
      <ul className="ml-4 mt-2 list-disc space-y-1.5">
        {Object.entries(value).map(([key, nestedValue]) => (
          <li key={key}>
            <span className="font-semibold">{formatLabel(key)}:</span>{" "}
            {isPlainObject(nestedValue) || Array.isArray(nestedValue) ? (
              <ValueTree value={nestedValue} />
            ) : (
              formatValue(nestedValue)
            )}
          </li>
        ))}
      </ul>
    );
  }

  return <span>{formatValue(value)}</span>;
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

function statusBadgeClass(status: string): string {
  const normalized = status.toLowerCase();
  if (normalized === "acceptable") return "badge-success";
  if (normalized === "critical") return "badge-error";
  return "badge-warning";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface ThermalAnalysisProps {
  name?: string;
  description?: string;
  analysis?: Record<string, unknown>;
}

export function ThermalAnalysisElement({ element }: ViewerProps) {
  const {
    name = "thermal_analysis",
    description = "",
    analysis = {},
  } = (element.props ?? {}) as ThermalAnalysisProps;

  // Backend agent calls (e.g. the AI interpretation/analysis step) can fail
  // upstream and still return a 200 with a dict shaped as { error: string }
  // instead of the expected analysis fields. Surface that explicitly rather
  // than silently rendering an empty card with no headline items or sections.
  if (typeof analysis.error === "string" && analysis.error) {
    return (
      <div className="card bg-base-200 border border-error/30 shadow-sm">
        <div className="card-body p-5">
          <div className="text-xs font-semibold uppercase tracking-wide text-error">
            Thermal Analysis — Failed
          </div>
          <div className="text-lg font-bold">{name}</div>
          {description ? (
            <div className="mt-1 text-sm text-base-content/70">{description}</div>
          ) : null}
          <div className="mt-3 rounded-lg bg-error/10 p-4 text-sm text-error">
            {analysis.error}
          </div>
        </div>
      </div>
    );
  }

  const status = String(analysis.status ?? "unknown");

  const headlineItems = (
    [
      ["Material", analysis.material_id],
      ["Status", analysis.status],
      ["Operating Temperature", analysis.operating_temperature_c],
      ["Thermal Stress (MPa)", analysis.thermal_stress_mpa],
      ["Fatigue Usage Factor", analysis.thermal_fatigue_usage_factor],
      ["Confidence", analysis.confidence],
    ] as [string, unknown][]
  ).filter(([, value]) => value !== null && value !== undefined && value !== "");

  const sections = (
    [
      ["Cycle Categories", analysis.cycle_categories],
      ["Fatigue Analysis", analysis.fatigue_analysis],
      ["Creep Analysis", analysis.creep_analysis],
      ["Recommendations", analysis.recommendations],
    ] as [string, unknown][]
  ).filter(([, value]) => {
    if (!value) return false;
    if (Array.isArray(value)) return value.length > 0;
    if (isPlainObject(value)) return Object.keys(value).length > 0;
    return true;
  });

  return (
    <div className="card bg-base-200 border border-base-300 shadow-sm">
      <div className="card-body p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-primary">
              Thermal Analysis
            </div>
            <div className="text-lg font-bold">
              {String(analysis.material_id ?? name)}
            </div>
            {description ? (
              <div className="mt-1 text-sm text-base-content/70">{description}</div>
            ) : null}
          </div>
          <div className={`badge ${statusBadgeClass(status)} badge-outline uppercase font-semibold`}>
            {status}
          </div>
        </div>

        {headlineItems.length > 0 && (
          <div className="mt-4 rounded-lg bg-base-100 p-4">
            <ul className="space-y-1.5">
              {headlineItems.map(([label, value]) => (
                <li key={label}>
                  <span className="font-semibold">{label}:</span> {formatValue(value)}
                </li>
              ))}
            </ul>
          </div>
        )}

        {sections.map(([title, value]) => (
          <div key={title} className="mt-4">
            <div className="text-sm font-bold">{title}</div>
            <div className="mt-2 rounded-lg bg-base-100 p-4">
              <ValueTree value={value} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default ThermalAnalysisElement;
