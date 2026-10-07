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
 * (YAML, MOOSE, Python, XML, C/C++, ...); otherwise it renders as plain text. Copy
 * always copies the raw, unhighlighted source.
 */

import { useMemo } from "react";
import { FileText } from "lucide-react";
import type { ViewerProps } from "@/lib/elements/elements";
import { highlightToHtml } from "@/lib/highlight";
import { ArtifactTextCard } from "./ArtifactTextCard";
import { useArtifactText } from "./useArtifactText";
import "./code.css";

interface CodeProps {
  source?: string;
  title?: string;
  url?: string;
  language?: string;
}

export function CodeElement({ element }: ViewerProps) {
  const { source = "", title, url = "", language } = (element.props ?? {}) as CodeProps;
  const name = title || element.name || "Code";

  const { text, loadState } = useArtifactText(source, url);
  const highlighted = useMemo(() => highlightToHtml(text, language), [text, language]);

  return (
    <ArtifactTextCard name={name} icon={FileText} url={url} text={text} loadState={loadState}>
      {/* No padding/background here: the card's rounded-lg + overflow-hidden clips this to
          match, so the code block's own background (base-300 for highlighted code, see
          code.css; bg-base-100 for the plain-text fallback) sits flush against the card
          edges instead of showing as a mismatched inset box nested inside another one. */}
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
    </ArtifactTextCard>
  );
}

export default CodeElement;
