/**
 * Syntax highlighting for the `code` artifact viewer (`CodeElement.tsx`).
 *
 * Wraps the highlight.js *core* build (no bundled languages) and registers only the
 * languages this app needs, so the rest of highlight.js's ~190 grammars never ship.
 * highlight.js was chosen over Prism/refractor, Shiki, lowlight, and
 * react-syntax-highlighter because it is the smallest synchronous (no WASM) option,
 * emits class-based output that themes against daisyUI variables with no JS
 * theme-switching, and has the easiest custom-grammar story — needed for the MOOSE
 * input grammar below.
 *
 * The routing tables further down (MIME / extension / file name → language) mirror the
 * backend's `code` render-hint tables in `backend/app/services/artifacts.py`; keep the
 * two in step when adding a language.
 */

import hljs from "highlight.js/lib/core";
import bash from "highlight.js/lib/languages/bash";
import c from "highlight.js/lib/languages/c";
import cmake from "highlight.js/lib/languages/cmake";
import cpp from "highlight.js/lib/languages/cpp";
import diff from "highlight.js/lib/languages/diff";
import dockerfile from "highlight.js/lib/languages/dockerfile";
import fortran from "highlight.js/lib/languages/fortran";
import ini from "highlight.js/lib/languages/ini";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import makefile from "highlight.js/lib/languages/makefile";
import plaintext from "highlight.js/lib/languages/plaintext";
import python from "highlight.js/lib/languages/python";
import sql from "highlight.js/lib/languages/sql";
import typescript from "highlight.js/lib/languages/typescript";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";
import moose from "./moose.ts";

hljs.registerLanguage("bash", bash);
hljs.registerLanguage("c", c);
hljs.registerLanguage("cmake", cmake);
hljs.registerLanguage("cpp", cpp);
hljs.registerLanguage("diff", diff);
hljs.registerLanguage("dockerfile", dockerfile);
hljs.registerLanguage("fortran", fortran);
hljs.registerLanguage("ini", ini); // also covers TOML
hljs.registerLanguage("javascript", javascript);
hljs.registerLanguage("json", json);
hljs.registerLanguage("makefile", makefile);
hljs.registerLanguage("plaintext", plaintext);
hljs.registerLanguage("python", python);
hljs.registerLanguage("sql", sql);
hljs.registerLanguage("typescript", typescript);
hljs.registerLanguage("xml", xml);
hljs.registerLanguage("yaml", yaml);
// `moose` takes no args (it needs nothing from the `hljs` instance), which is still a
// valid `LanguageFn` — TS allows a function with fewer params where more are expected.
hljs.registerLanguage("moose", moose);

// Perf guard: the ported MOOSE grammar leans on variable-length lookbehinds, which cost
// ~100ms per 4k lines. Skip highlighting past this size rather
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

// MIME → language. Checked before the file name (an explicit MIME wins over a guessed
// one from the filename). `application/json` is deliberately absent: JSON artifacts use
// the interactive JSON viewer, and only reach this one as `.jsonc` by extension.
const MIME_LANGUAGES: Record<string, string> = {
  "application/yaml": "yaml",
  "application/x-yaml": "yaml",
  "text/yaml": "yaml",
  "text/x-yaml": "yaml",
  "text/x-moose": "moose", // vendor MIME; MOOSE input files have no registered IANA type
  "application/toml": "ini",
  "application/xml": "xml",
  "text/xml": "xml",
  "text/x-python": "python",
  "text/x-script.python": "python",
  "application/x-python": "python",
  "text/x-c": "c",
  "text/x-csrc": "c",
  "text/x-chdr": "c",
  "text/x-c++src": "cpp",
  "text/x-c++hdr": "cpp",
  "text/x-fortran": "fortran",
  "text/x-cmake": "cmake",
  "text/x-makefile": "makefile",
  "application/x-sh": "bash",
  "text/x-shellscript": "bash",
  "text/x-dockerfile": "dockerfile",
  "application/sql": "sql",
  "text/x-sql": "sql",
  "text/javascript": "javascript",
  "application/javascript": "javascript",
  "application/typescript": "typescript",
  "text/x-typescript": "typescript",
  "text/x-diff": "diff",
  "text/x-patch": "diff",
};

// Whole file name → language, for files with no (useful) extension. Checked before the
// extension so `CMakeLists.txt` is cmake rather than plain text.
const BASENAME_LANGUAGES: Record<string, string> = {
  Dockerfile: "dockerfile",
  Containerfile: "dockerfile",
  Makefile: "makefile",
  makefile: "makefile",
  GNUmakefile: "makefile",
  "CMakeLists.txt": "cmake",
};

// Extension → language, mirroring the backend's _EXTENSION_HINTS "code" entries
// (backend/app/services/artifacts.py) so a `code` artifact without a recognized MIME
// still gets a grammar from its filename.
const EXTENSION_LANGUAGES: Record<string, string> = {
  ".yaml": "yaml",
  ".yml": "yaml",
  ".i": "moose",
  ".jsonc": "json",
  ".toml": "ini",
  ".ini": "ini",
  ".cfg": "ini",
  ".conf": "ini",
  ".xml": "xml",
  ".xsd": "xml",
  ".xdmf": "xml",
  ".xmf": "xml",
  ".py": "python",
  ".pyi": "python",
  ".c": "c",
  ".h": "c",
  ".cpp": "cpp",
  ".cc": "cpp",
  ".cxx": "cpp",
  ".hpp": "cpp",
  ".hh": "cpp",
  ".hxx": "cpp",
  ".f": "fortran",
  ".f90": "fortran",
  ".f95": "fortran",
  ".f03": "fortran",
  ".f08": "fortran",
  ".for": "fortran",
  ".cmake": "cmake",
  ".mk": "makefile",
  ".dockerfile": "dockerfile",
  ".sh": "bash",
  ".bash": "bash",
  ".zsh": "bash",
  ".sql": "sql",
  ".js": "javascript",
  ".mjs": "javascript",
  ".cjs": "javascript",
  ".jsx": "javascript",
  ".ts": "typescript",
  ".tsx": "typescript",
  ".mts": "typescript",
  ".diff": "diff",
  ".patch": "diff",
  ".txt": "plaintext",
  ".log": "plaintext",
};

/** Last path segment, so a dot in a directory name isn't mistaken for an extension. */
function basenameOf(name: string): string {
  return name.split(/[\\/]/).pop() ?? name;
}

function extensionOf(base: string): string {
  const dot = base.lastIndexOf(".");
  return dot === -1 ? "" : base.slice(dot).toLowerCase();
}

/**
 * Best-effort language for a `code` artifact: its MIME type, then its whole file name
 * (`Dockerfile`), then its extension.
 */
export function languageFor(
  name: string | null | undefined,
  mimeType: string | null | undefined,
): string | undefined {
  const mime = (mimeType ?? "").split(";", 1)[0].trim().toLowerCase();
  if (mime && MIME_LANGUAGES[mime]) return MIME_LANGUAGES[mime];
  if (name) {
    const base = basenameOf(name);
    return BASENAME_LANGUAGES[base] ?? EXTENSION_LANGUAGES[extensionOf(base)];
  }
  return undefined;
}
