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
 * Dev-only review page for the Builder's Node Inspector: its selected state
 * (Figma D.2) and empty state (D.3) side by side, at the Builder column's
 * width, with a theme toggle. The Builder page itself only shows D.2.
 *
 * Open http://localhost:5150/?harness=node-inspector under `npm run dev`.
 * main.tsx loads this only in dev, so it never reaches the production build.
 */
import { NodeInspector, type InspectedNode } from "../components/workflows/NodeInspector";
import { useTheme } from "../lib/useTheme";

const RADIATION_DAMAGE: InspectedNode = {
  name: "Radiation Damage",
  tone: "analysis",
  skillId: "analyze_radiation_damage",
  inputs: [
    { name: "material_id", value: "from input.material_id" },
    { name: "neutron_flux" },
    { name: "temperature_c", value: "from input.context" },
  ],
  outputs: [{ name: "to_context", value: "radiation" }],
};

const STATES = [
  { label: "Selected (D.2)", node: RADIATION_DAMAGE },
  { label: "Empty (D.3)", node: null },
];

export function NodeInspectorHarness() {
  const [theme, setTheme] = useTheme();
  return (
    <div className="flex min-h-screen flex-col gap-6 bg-base-100 p-6 text-base-content">
      <div className="flex items-center gap-4">
        <h1 className="m-0 text-lg font-bold">Node Inspector states (dev)</h1>
        <button type="button" className="btn btn-sm" onClick={() => setTheme(theme === "light" ? "dark" : "light")}>
          {theme === "light" ? "Dark theme" : "Light theme"}
        </button>
      </div>
      <div className="flex flex-wrap gap-6">
        {STATES.map(({ label, node }) => (
          <figure key={label} className="m-0 flex flex-col gap-2">
            <figcaption className="text-xs text-base-content/60">{label}</figcaption>
            <aside
              aria-label={`Node inspector, ${label}`}
              className="h-[640px] w-[280px] overflow-y-auto border border-base-content/10 bg-base-200 p-4"
            >
              <NodeInspector node={node} />
            </aside>
          </figure>
        ))}
      </div>
    </div>
  );
}
