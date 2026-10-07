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
 * The MIME / extension / file name → language tables live in `./language.ts`, which
 * deliberately does not import this module (and so not highlight.js).
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
// ~100ms per 4k lines. Skip highlighting past this many characters (`String.length`, i.e.
// UTF-16 code units, not bytes) rather than freeze the UI on a huge pasted/generated file.
const MAX_HIGHLIGHT_CHARS = 200_000;

/**
 * Highlight `code` as `language`, returning an HTML string (hljs escapes the source, so
 * it's safe for `dangerouslySetInnerHTML`) or `null` when the language isn't registered,
 * `code` is empty/oversized, or highlighting throws.
 */
export function highlightToHtml(code: string, language: string | undefined): string | null {
  if (!language || !code || code.length > MAX_HIGHLIGHT_CHARS) return null;
  if (!hljs.getLanguage(language)) return null;
  try {
    return hljs.highlight(code, { language, ignoreIllegals: true }).value;
  } catch {
    return null;
  }
}
