/**
 * Which highlight.js language a `code` artifact should use, from its MIME type, whole
 * file name or extension.
 *
 * Kept separate from `./index.ts` on purpose: this module imports nothing from
 * highlight.js, so the artifact adapter (part of the first-view bundle) can pick a
 * language without pulling in the grammars. They load with `CodeElement`, which is
 * lazy. The tables mirror the backend's `code` render-hint tables in
 * `backend/app/services/artifacts.py`; keep the two in step when adding a language.
 */

import { normalizeMime } from "../mime.ts";

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

/** Language from a file name or path alone: whole file name first, then extension. */
function languageForPath(path: string | null | undefined): string | undefined {
  if (!path) return undefined;
  const base = basenameOf(path);
  return BASENAME_LANGUAGES[base] ?? EXTENSION_LANGUAGES[extensionOf(base)];
}

/**
 * Best-effort language for a `code` artifact: its MIME type, then its whole file name
 * (`Dockerfile`), then its extension.
 */
export function languageFor(
  name: string | null | undefined,
  mimeType: string | null | undefined,
): string | undefined {
  const mime = normalizeMime(mimeType);
  if (mime && MIME_LANGUAGES[mime]) return MIME_LANGUAGES[mime];
  return languageForPath(name);
}

/**
 * Language for an artifact as the backend classifies it: the MIME type first, then the
 * file name of `uri`, then `name` (`_extension_hint` in `backend/app/services/artifacts.py`
 * checks them in that order). A `render_hint: "code"` artifact whose `uri` ends in `.i`
 * or is `Dockerfile` but whose display `name` has no such suffix still gets its grammar.
 *
 * Like the backend, a generic `.txt` / `.log` name does not count when the MIME type is
 * `text/plain` or `text/markdown`: agent text parts default to the name `artifact.txt`.
 */
export function languageForArtifact(artifact: {
  name?: string | null;
  uri?: string | null;
  mime_type?: string | null;
}): string | undefined {
  const mime = normalizeMime(artifact.mime_type);
  if (mime && MIME_LANGUAGES[mime]) return MIME_LANGUAGES[mime];
  const textMime = mime === "text/plain" || mime === "text/markdown";
  for (const path of [artifact.uri, artifact.name]) {
    const language = languageForPath(path);
    if (language === "plaintext" && textMime) continue;
    if (language) return language;
  }
  return undefined;
}
