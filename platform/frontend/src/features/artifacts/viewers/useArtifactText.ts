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
 * src/viewers/useArtifactText.ts
 *
 * Shared text loading for the inline-text viewers (`CodeElement`, `TableElement`,
 * `ReportElement`): use the inline `source` when the element carries one, otherwise
 * fetch the body from the artifact content proxy (`GET /api/artifacts/{id}/content`)
 * with the session cookie. A fetch failure surfaces as `loadState === "error"` so the
 * viewer can degrade to a "couldn't load" line (the download link still works) instead
 * of dropping the artifact.
 */

import { useEffect, useState } from "react";

export type LoadState = "idle" | "loading" | "error";

export function useArtifactText(source: string, url: string): { text: string; loadState: LoadState } {
  const [text, setText] = useState(source);
  const [loadState, setLoadState] = useState<LoadState>(source || !url ? "idle" : "loading");

  useEffect(() => {
    if (source || !url) return;
    let cancelled = false;
    setLoadState("loading");
    fetch(url, { credentials: "include" })
      .then((res) => (res.ok ? res.text() : Promise.reject(new Error(`HTTP ${res.status}`))))
      .then((body) => {
        if (cancelled) return;
        setText(body);
        setLoadState("idle");
      })
      .catch(() => {
        if (!cancelled) setLoadState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [source, url]);

  return { text, loadState };
}
