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
 * src/viewers/MermaidElement.tsx
 *
 * Renders cl.CustomElement(name="MermaidViewer") payloads.
 *
 * Wire contract (backend: mermaid plugin __init__.py):
 *   props: {
 *     diagram: string   // raw mermaid diagram source
 *     title: string     // artifact name, may be empty
 *   }
 *
 * Uses the npm `mermaid` package via dynamic import (same lazy-chunk pattern
 * as IFCViewerElement / MeshViewerElement in elements.ts) rather than the
 * CDN <script> injection the original plugin used. CDN loading is reserved
 * for cases with no real npm package available — mermaid has one, so it
 * follows the same convention as the other heavy viewers.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import type { ViewerProps } from "@/features/artifacts/elements";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface MermaidProps {
  diagram?: string;
  title?: string;
}

type RenderStatus = "idle" | "loading" | "ready" | "error";
type ViewMode = "diagram" | "code";

// ---------------------------------------------------------------------------
// Theme detection
//
// NOTE: duplicated here from the same pattern used in the pre-DaisyUI-port
// ThermalAnalysisViewer. Both viewers need mermaid/library-level theme
// strings ("dark" | "default"), not just DaisyUI classes, since mermaid
// renders raw SVG with its own internal color config. Worth extracting to a
// shared `useLibraryTheme()` hook in the viewer toolkit rather than
// duplicating a third time on the next viewer that needs it.
// ---------------------------------------------------------------------------

function detectTheme(): "dark" | "default" {
  if (typeof document !== "undefined") {
    const html = document.documentElement;
    if (html.getAttribute("data-theme") === "dark") return "dark";
    if (html.classList.contains("dark")) return "dark";
  }
  if (typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches) {
    return "dark";
  }
  return "default";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MermaidElement({ element }: ViewerProps) {
  const { diagram = "", title = "" } = (element.props ?? {}) as MermaidProps;

  const containerRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<RenderStatus>("idle");
  const [error, setError] = useState("");
  const [view, setView] = useState<ViewMode>("diagram");
  const [copied, setCopied] = useState(false);
  const [downloadError, setDownloadError] = useState("");

  const theme = useMemo(() => detectTheme(), []);

  useEffect(() => {
    let cancelled = false;

    async function renderDiagram() {
      if (!diagram || !containerRef.current) {
        setStatus("error");
        setError("No Mermaid diagram provided.");
        return;
      }

      setStatus("loading");
      setError("");
      containerRef.current.innerHTML = "";

      try {
        const { default: mermaid } = await import("mermaid");
        if (cancelled) return;

        mermaid.initialize({ startOnLoad: false, theme });

        const id = `mermaid-${Math.random().toString(36).slice(2)}`;
        const { svg, bindFunctions } = await mermaid.render(id, diagram);
        if (cancelled || !containerRef.current) return;

        containerRef.current.innerHTML = svg;
        bindFunctions?.(containerRef.current);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        setStatus("error");
        setError(err instanceof Error ? err.message : String(err));
        setView("code");
      }
    }

    renderDiagram();

    return () => {
      cancelled = true;
    };
  }, [diagram, theme]);

  const downloadSvg = () => {
    const svg = containerRef.current?.querySelector("svg");
    if (!svg) {
      setDownloadError("Diagram is not ready yet.");
      return;
    }
    setDownloadError("");

    let svgText = new XMLSerializer().serializeToString(svg);
    if (!svgText.includes("http://www.w3.org/2000/svg")) {
      svgText = svgText.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"');
    }

    const url = URL.createObjectURL(new Blob([svgText], { type: "image/svg+xml;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "mermaid-diagram.svg";
    link.click();
    URL.revokeObjectURL(url);
  };

  const copyCode = async () => {
    if (!diagram) return;
    try {
      await navigator.clipboard.writeText(diagram);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="w-full py-2">
      {title ? <div className="mb-2 text-sm font-semibold text-base-content/80">{title}</div> : null}

      <div className="mb-2 flex items-center gap-1.5">
        <div role="tablist" className="tabs tabs-boxed tabs-xs">
          <button
            type="button"
            role="tab"
            className={`tab ${view === "diagram" ? "tab-active" : ""}`}
            onClick={() => setView("diagram")}
          >
            Diagram
          </button>
          <button
            type="button"
            role="tab"
            className={`tab ${view === "code" ? "tab-active" : ""}`}
            onClick={() => setView("code")}
          >
            Code
          </button>
        </div>

        {view === "diagram" && (
          <div className="ml-auto flex gap-1.5">
            <button type="button" className="btn btn-ghost btn-xs" onClick={downloadSvg}>
              Download SVG
            </button>
          </div>
        )}
      </div>

      <div className={view === "diagram" ? "block" : "hidden"}>
        {status === "loading" && <div className="mb-2 text-xs text-base-content/60">Rendering diagram...</div>}
        {status === "error" && <div className="mb-2 text-xs text-error">Mermaid render failed: {error}</div>}
        {downloadError && <div className="mb-2 text-xs text-error">{downloadError}</div>}

        <div className="overflow-auto rounded-lg border border-base-300 bg-base-200 p-3">
          <div ref={containerRef} />
        </div>
      </div>

      <div className={view === "code" ? "relative block" : "hidden"}>
        <button type="button" className="btn btn-ghost btn-xs absolute right-2 top-2 z-10" onClick={copyCode}>
          {copied ? "Copied" : "Copy"}
        </button>
        <pre className="wrap-break-word overflow-x-auto rounded-lg border border-base-300 bg-base-200 p-3 pt-8 text-xs">
          {diagram}
        </pre>
      </div>
    </div>
  );
}

export default MermaidElement;
