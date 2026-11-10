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

import { useCallback, useMemo, useState } from "react";
import { Check, ChevronDown, ChevronRight, Copy, FileJson } from "lucide-react";
import { toPrettyJson, tokenizeJsonLine, type JsonToken } from "./jsonSyntax";
import type { ViewerProps } from "@/features/artifacts/elements";

const TOKEN_CLASS: Record<JsonToken["type"], string> = {
  key: "text-primary",
  string: "text-success",
  number: "text-info",
  boolean: "text-warning",
  null: "text-base-content/50 italic",
  punct: "text-base-content/60",
  space: "",
  text: "text-base-content/80",
};

export function JSONViewer({ element }: ViewerProps) {
  // TODO: confirm the actual prop key the backend sends for the
  // `CollapsibleJson` element in the Agent Output Contract — this assumes
  // `data`, matching the pattern used elsewhere in elements.ts. Same
  // unconfirmed-name situation as IFCViewer. Adjust the fallback chain below
  // once confirmed instead of guessing multiple keys indefinitely.
  const props = element.props ?? {};
  const data = props.data ?? props.json ?? props.content;
  const name = element.name ?? "JSON";
  const defaultCollapsed = Boolean(props.defaultCollapsed);
  const maxHeight = typeof props.maxHeight === "number" ? props.maxHeight : 400;

  const [expanded, setExpanded] = useState(!defaultCollapsed);
  const [copied, setCopied] = useState(false);

  const { text, valid } = useMemo(() => toPrettyJson(data), [data]);
  const lines = useMemo(() => text.split("\n"), [text]);
  const lineTokens = useMemo(
    () => (valid ? lines.map((line) => tokenizeJsonLine(line)) : null),
    [lines, valid],
  );

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard can fail (permissions, insecure context) — fail quietly.
    }
  }, [text]);

  return (
    <div className="rounded-box border border-base-300 bg-base-200 overflow-hidden text-sm">
      <div className="flex items-center justify-between gap-2 px-3 py-2 bg-base-300/40">
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          aria-expanded={expanded}
          className="flex items-center gap-1.5 text-base-content/80 hover:text-base-content focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-primary rounded"
        >
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <FileJson size={14} className="text-base-content/50" />
          <span className="font-medium">{name}</span>
          <span className="badge badge-sm badge-ghost">{lines.length} lines</span>
          {!valid && (
            <span className="badge badge-sm badge-warning badge-outline">unparsed</span>
          )}
        </button>
        <button
          type="button"
          onClick={handleCopy}
          className="btn btn-ghost btn-xs gap-1"
          aria-label="Copy JSON"
        >
          {copied ? <Check size={14} className="text-success" /> : <Copy size={14} />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>

      {expanded && (
        <div className="overflow-y-auto overflow-x-hidden font-mono leading-relaxed" style={{ maxHeight }}>
          {lines.map((line, i) => (
            <div key={i} className="flex items-start px-3 hover:bg-base-300/20">
              <span className="w-8 shrink-0 text-right pr-3 pt-px text-base-content/30 select-none">
                {i + 1}
              </span>
              <span className="whitespace-pre-wrap wrap-break-word min-w-0">
                {lineTokens
                  ? lineTokens[i].map((tok, j) => (
                      <span key={j} className={TOKEN_CLASS[tok.type]}>
                        {tok.value}
                      </span>
                    ))
                  : line}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
