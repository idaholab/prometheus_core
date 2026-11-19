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
 * Dev-only page that mounts the artifact viewers with sample data, through the
 * same ElementList and artifactsToElements path the chat uses. Each case is a
 * file in cases/; main.tsx loads them and answers their backend URLs from the
 * samples, so the page needs no agent run and no backend.
 *
 * Open http://localhost:5150/dev/viewers/ under `npm run dev` (or `npm run playground`).
 * The app build reads index.html only, so the page never reaches it.
 */
import { FlaskConical } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { ElementList, artifactsToElements } from "@/features/artifacts";
import { useTheme } from "@/lib/useTheme";
import type { ViewerCase } from "./viewerCase";

export function ViewerPlayground({ cases }: { cases: ViewerCase[] }) {
  const [theme, setTheme] = useTheme();

  return (
    // index.css sets overflow: hidden on html, body and #root, so the page scrolls itself.
    <div className="flex h-screen flex-col overflow-y-auto bg-base-100 text-base-content">
      <div className="flex flex-wrap items-center gap-3 border-b border-base-content/10 px-6 py-3">
        <h1 className="m-0 mr-2 text-sm font-bold">Viewer playground</h1>
        <span className="text-sm text-base-content/70">Developer page. Not part of the Prometheus app.</span>
        <Button
          label={theme === "light" ? "Dark theme" : "Light theme"}
          size="sm"
          className="ml-auto"
          onClick={() => setTheme(theme === "light" ? "dark" : "light")}
        />
      </div>
      {cases.length === 0 ? (
        <EmptyState
          icon={<FlaskConical size={24} />}
          title="No viewer cases found."
          hint="Add a file to src/dev/viewer-playground/cases/."
        />
      ) : (
        cases.map((c) => (
          <section key={c.title} className="flex flex-col gap-2 border-b border-base-content/10 px-6 py-4">
            <h2 className="m-0 text-base font-semibold">{c.title}</h2>
            <p className="m-0 text-sm text-base-content/70">{c.note}</p>
            <ElementList elements={artifactsToElements([c.artifact])} />
          </section>
        ))
      )}
    </div>
  );
}
