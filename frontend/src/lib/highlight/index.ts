/**
 * Syntax highlighting for the `code` artifact viewer (`CodeElement.tsx`).
 *
 * Wraps the highlight.js *core* build (no bundled languages) and registers only the
 * languages this app needs, so the rest of highlight.js's ~190 grammars never ship.
 * See `syntax-highlighter-comparison.md` (repo root, Oct 2026) for why highlight.js was
 * chosen over Prism/refractor, Shiki, lowlight, and react-syntax-highlighter: smallest
 * synchronous (no WASM) option, class-based output that themes against daisyUI
 * variables with no JS theme-switching, and the easiest custom-grammar story — needed
 * for the MOOSE input grammar below.
 */

import hljs from "highlight.js/lib/core";
import yaml from "highlight.js/lib/languages/yaml";
import moose from "./moose";

hljs.registerLanguage("yaml", yaml);
// `moose` takes no args (it needs nothing from the `hljs` instance), which is still a
// valid `LanguageFn` — TS allows a function with fewer params where more are expected.
hljs.registerLanguage("moose", moose);

// Perf guard: the ported MOOSE grammar leans on variable-length lookbehinds, which cost
// ~100ms per 4k lines (see the comparison doc). Skip highlighting past this size rather
// than freeze the UI on a huge pasted/generated file.
const MAX_HIGHLIGHT_BYTES = 200_000;

/**
 * Highlight `code` as `language`, returning an HTML string (hljs escapes the source, so
 * it's safe for `dangerouslySetInnerHTML`) or `null` when the language isn't registered,
 * `code` is empty/oversized, or highlighting throws.
 */
export function highlightToHtml(code: string, language: string | undefined): string | null {
  if (!language || !code || code.length > MAX_HIGHLIGHT_BYTES) return null;
  if (!hljs.getLanguage(language)) return null;
  try {
    return hljs.highlight(code, { language, ignoreIllegals: true }).value;
  } catch {
    return null;
  }
}

// MIME → language. Checked before the extension (an explicit MIME wins over a guessed
// one from the filename).
const MIME_LANGUAGES: Record<string, string> = {
  "application/yaml": "yaml",
  "application/x-yaml": "yaml",
  "text/yaml": "yaml",
  "text/x-yaml": "yaml",
  "text/x-moose": "moose", // vendor MIME; MOOSE input files have no registered IANA type
};

// Extension → language, mirroring the backend's _EXTENSION_HINTS "code" entries
// (backend/app/services/artifacts.py) so a `code` artifact without a recognized MIME
// still gets a grammar from its filename.
const EXTENSION_LANGUAGES: Record<string, string> = {
  ".yaml": "yaml",
  ".yml": "yaml",
  ".i": "moose",
};

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot).toLowerCase();
}

/** Best-effort language for a `code` artifact, from its MIME type then its filename. */
export function languageFor(
  name: string | null | undefined,
  mimeType: string | null | undefined,
): string | undefined {
  const mime = (mimeType ?? "").split(";", 1)[0].trim().toLowerCase();
  if (mime && MIME_LANGUAGES[mime]) return MIME_LANGUAGES[mime];
  if (name) return EXTENSION_LANGUAGES[extensionOf(name)];
  return undefined;
}
