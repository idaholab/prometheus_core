/**
 * src/viewers/CodeElement.tsx
 *
 * Renders a `code` artifact (render_hint === "code") as plain source text — YAML and
 * similar config/source formats that would be mangled by the Markdown renderer
 * (`ReportElement.tsx`'s `#` comments reading as headings, indentation collapsing).
 * Mirrors `ReportElement.tsx`'s fetch-from-`url`-if-no-inline-source behavior: when no
 * inline `source` prop is present, the body is fetched from the content proxy
 * (`GET /api/artifacts/{id}/content`). A fetch failure degrades to a "couldn't load"
 * line + download link rather than dropping the artifact. The code block styling and
 * copy-button behavior mirror `CodeBlock` in `@/components/Markdown`.
 *
 * When `language` is recognized by `lib/highlight`, the body is syntax-highlighted
 * (currently YAML and MOOSE input files); otherwise it renders as plain text. Copy
 * always copies the raw, unhighlighted source.
 */

import { useEffect, useMemo, useState } from "react";
import { AlertCircle, Check, Copy, FileDown, FileText } from "lucide-react";
import type { ViewerProps } from "@/lib/elements/elements";
import { highlightToHtml } from "@/lib/highlight";
import "./code.css";

interface CodeProps {
  source?: string;
  title?: string;
  url?: string;
  language?: string;
}

type LoadState = "idle" | "loading" | "error";

export function CodeElement({ element }: ViewerProps) {
  const { source = "", title, url = "", language } = (element.props ?? {}) as CodeProps;
  const name = title || element.name || "Code";

  const [text, setText] = useState(source);
  const [loadState, setLoadState] = useState<LoadState>(source || !url ? "idle" : "loading");
  const [copied, setCopied] = useState(false);

  const highlighted = useMemo(() => highlightToHtml(text, language), [text, language]);

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

  const handleCopy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="border border-base-300 rounded-lg overflow-hidden my-2 bg-base-200/40 max-w-3xl">
      <div className="flex items-center justify-between gap-3 px-3 py-2 border-b border-base-300 bg-base-200/60">
        <p className="text-sm font-medium text-base-content truncate flex items-center gap-1.5">
          <FileText size={13} className="text-base-content/50 shrink-0" />
          {name}
        </p>
        <div className="flex items-center gap-1 shrink-0">
          {loadState === "idle" && text && (
            <button onClick={handleCopy} className="btn btn-ghost btn-xs" aria-label="Copy source">
              {copied ? <Check size={13} /> : <Copy size={13} />}
            </button>
          )}
          {url && (
            <a href={url} download={name} className="btn btn-ghost btn-xs" aria-label={`Download ${name}`}>
              <FileDown size={13} />
              Download
            </a>
          )}
        </div>
      </div>
      {loadState === "loading" && (
        <div className="bg-base-100 px-4 py-3 text-sm">
          <span className="text-xs text-base-content/50">Loading…</span>
        </div>
      )}
      {loadState === "error" && (
        <div className="bg-base-100 px-4 py-3 text-sm">
          <span className="text-xs text-error inline-flex items-center gap-1.5">
            <AlertCircle size={13} />
            Couldn't load this file.
          </span>
        </div>
      )}
      {loadState === "idle" && text && (
        // No padding/background here: the card's rounded-lg + overflow-hidden on the
        // outer div clips this to match, so the code block's own background (the vs/
        // vs2015 theme's white/#1E1E1E, or bg-base-100 for the plain-text fallback)
        // sits flush against the card edges instead of showing as a mismatched inset
        // box nested inside another background.
        <pre className="code-viewer m-0 overflow-x-auto max-h-96">
          {highlighted !== null ? (
            <code
              className={`hljs language-${language} whitespace-pre text-sm leading-5`}
              dangerouslySetInnerHTML={{ __html: highlighted }}
            />
          ) : (
            <code className="block bg-base-100 px-4 py-3 whitespace-pre text-sm leading-5">{text}</code>
          )}
        </pre>
      )}
    </div>
  );
}

export default CodeElement;
