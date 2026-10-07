/**
 * src/viewers/ArtifactTextCard.tsx
 *
 * The card shared by the inline-text viewers (`CodeElement`, `TableElement`): the
 * bordered shell and header (icon, name, optional badge and extra actions), the copy and
 * download buttons, and the Loading / "Couldn't load this file." / "Empty file" rows.
 * `children` is the body and renders only once the text has loaded and is non-empty.
 * Pair it with `useArtifactText`, which supplies `text` and `loadState`.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { AlertCircle, Check, Copy, FileDown, type LucideIcon } from "lucide-react";
import type { LoadState } from "./useArtifactText";

type CopyState = "idle" | "copied" | "failed";

const COPY_LABELS: Record<CopyState, string> = {
  idle: "Copy source",
  copied: "Copied",
  failed: "Copy failed",
};

/**
 * Copy `text` to the clipboard, tracking a short-lived copied / failed state. The write
 * can be refused (permission denied, or a non-secure context where `navigator.clipboard`
 * is undefined), so both outcomes are shown rather than left as an unhandled rejection.
 */
function useCopy(text: string) {
  const [state, setState] = useState<CopyState>("idle");
  const timer = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => () => clearTimeout(timer.current), []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
    }
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setState("idle"), 2000);
  };

  return { state, copy };
}

interface ArtifactTextCardProps {
  name: string;
  icon: LucideIcon;
  url: string;
  text: string;
  loadState: LoadState;
  /** Shown beside the name, e.g. a row count. */
  badge?: ReactNode;
  /** Extra header controls, placed before the copy button. */
  actions?: ReactNode;
  children: ReactNode;
}

export function ArtifactTextCard({
  name,
  icon: Icon,
  url,
  text,
  loadState,
  badge,
  actions,
  children,
}: ArtifactTextCardProps) {
  const { state: copyState, copy } = useCopy(text);
  const loaded = loadState === "idle" && text !== "";

  return (
    <div className="border border-base-300 rounded-lg overflow-hidden my-2 bg-base-200/40 max-w-3xl">
      <div className="flex items-center justify-between gap-3 px-3 py-2 border-b border-base-300 bg-base-200/60">
        <p className="text-sm font-medium text-base-content truncate flex items-center gap-1.5">
          <Icon size={13} className="text-base-content/50 shrink-0" />
          {name}
          {badge}
        </p>
        <div className="flex items-center gap-1 shrink-0">
          {loaded && actions}
          {loaded && (
            <button onClick={copy} className="btn btn-ghost btn-xs" aria-label={COPY_LABELS[copyState]}>
              {copyState === "copied" && <Check size={13} />}
              {copyState === "failed" && <AlertCircle size={13} className="text-error" />}
              {copyState === "idle" && <Copy size={13} />}
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
      {/* Announce the copy result to screen readers; a changed aria-label alone is not. */}
      <span className="sr-only" role="status">
        {copyState === "idle" ? "" : COPY_LABELS[copyState]}
      </span>

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
      {loadState === "idle" && text === "" && (
        <div className="bg-base-100 px-4 py-3 text-sm">
          <span className="text-xs text-base-content/50">Empty file</span>
        </div>
      )}
      {loaded && children}
    </div>
  );
}
