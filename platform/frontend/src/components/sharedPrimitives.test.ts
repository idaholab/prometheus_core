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

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "vitest";

// Reads the screens as text; no .tsx module is imported.
const COMPONENTS_DIR = fileURLToPath(new URL(".", import.meta.url));

const IN_SCOPE_FILES = [
  "Header.tsx",
  "LeftPanel.tsx",
  "Login.tsx",
  "SetupWizard.tsx",
  "Chat.tsx",
  "chat/FollowupForm.tsx",
  "SettingsPanel.tsx",
  "dashboard/StatusPanel.tsx",
  "chat/WelcomeScreen.tsx",
];

const LEFTOVER_CLASS = /className=.*[^A-Za-z0-9_-](btn|badge)([^A-Za-z0-9_]|$)/;
const HEX_COLOUR = /#[0-9a-fA-F]{3,8}\b/;
const STRING_LITERAL = /"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`/g;
const SHARED_UI_IMPORT = /from\s+["'](@\/components\/ui\/|\.\/ui\/)/;
const BUTTON_IMPORT = /import\s*\{[^}]*\bButton\b[^}]*\}\s*from\s+["'](@\/components\/ui\/Button|\.\/ui\/Button)["']/;

/**
 * The only raw `<button>` elements allowed in the in-scope files. None has a
 * `btn` class, and none is a site in the blueprint's site table. Each entry
 * names a stable attribute of the element and how many elements carry it in
 * that file; any other raw `<button>` fails the test.
 */
const RAW_BUTTON_ALLOWLIST: ReadonlyArray<{ file: string; marker: string; count: number; why: string }> = [
  { file: "Chat.tsx", marker: "aria-label={`Remove ", count: 1, why: "attachment remove (blueprint Out of scope)" },
  { file: "dashboard/StatusPanel.tsx", marker: "aria-label={label}", count: 1, why: "rail button (blueprint Out of scope)" },
  { file: "dashboard/StatusPanel.tsx", marker: 'role="tab"', count: 2, why: "Jobs and Artifacts tabs (blueprint Out of scope)" },
  { file: "Chat.tsx", marker: "onClick={() => setOpen((v) => !v)}", count: 1, why: "tool-call history toggle, not a site" },
  { file: "LeftPanel.tsx", marker: "aria-current=", count: 1, why: "NavButton rail item, not a site" },
  { file: "Header.tsx", marker: "onClick={() => setTheme(nextTheme)}", count: 1, why: "user menu item, not a site" },
  { file: "Header.tsx", marker: "onClick={onToggleSettings}", count: 1, why: "user menu item, not a site" },
  { file: "Header.tsx", marker: "onClick={onLogout}", count: 1, why: "user menu item, not a site" },
];

/** Skips a quoted literal that opens at `start`; returns the index after it. */
function skipQuoted(source: string, start: number): number {
  const quote = source[start];
  let i = start + 1;
  while (i < source.length && source[i] !== quote) {
    i += source[i] === "\\" ? 2 : 1;
  }
  return i + 1;
}

interface JsxElement {
  line: number;
  /** The element's attribute text as written. */
  attributes: string;
  /** The element's attributes with every `{...}` expression blanked out. */
  topLevelAttributes: string;
}

/**
 * Finds each `<tag` JSX element (case-sensitive) and scans to its closing `/>` or `>`,
 * tracking brace depth and skipping quoted literals and comments, so `=>` and
 * nested JSX inside `{...}` props (e.g. `icon={<Bell />}`) do not end the
 * element early.
 */
function jsxElements(source: string, tag: string): JsxElement[] {
  const elements: JsxElement[] = [];
  const opener = new RegExp(`<${tag}(?=[\\s/>])`, "g");
  for (let match = opener.exec(source); match; match = opener.exec(source)) {
    let i = match.index + match[0].length;
    let depth = 0;
    let topLevel = "";
    while (i < source.length) {
      const ch = source[i];
      if (ch === '"' || ch === "'" || ch === "`") {
        const end = skipQuoted(source, i);
        if (depth === 0) topLevel += source.slice(i, end);
        i = end;
        continue;
      }
      // A comment between attributes may hold a quote ("session's"); skip it.
      if (source.startsWith("//", i)) {
        const end = source.indexOf("\n", i);
        i = end === -1 ? source.length : end;
        continue;
      }
      if (source.startsWith("/*", i)) {
        const end = source.indexOf("*/", i + 2);
        i = end === -1 ? source.length : end + 2;
        continue;
      }
      if (ch === "{") {
        depth += 1;
      } else if (ch === "}") {
        depth -= 1;
      } else if (depth === 0 && (ch === ">" || source.startsWith("/>", i))) {
        break;
      } else if (depth === 0) {
        topLevel += ch;
      }
      i += 1;
    }
    assert.ok(i < source.length, `unterminated <${tag} at offset ${match.index}`);
    elements.push({
      line: source.slice(0, match.index).split("\n").length,
      attributes: source.slice(match.index + match[0].length, i),
      topLevelAttributes: topLevel,
    });
    opener.lastIndex = i;
  }
  return elements;
}

test("in_scope_screens_use_shared_primitives", () => {
  const violations: string[] = [];

  for (const file of IN_SCOPE_FILES) {
    const source = readFileSync(join(COMPONENTS_DIR, file), "utf8");

    source.split("\n").forEach((text, index) => {
      if (LEFTOVER_CLASS.test(text)) {
        violations.push(`${file}:${index + 1}: raw btn/badge class: ${text.trim()}`);
      }
    });

    for (const literal of source.matchAll(STRING_LITERAL)) {
      if (HEX_COLOUR.test(literal[0])) {
        const line = source.slice(0, literal.index).split("\n").length;
        violations.push(`${file}:${line}: hard-coded hex colour in ${literal[0]}`);
      }
    }

    const buttons = jsxElements(source, "Button");
    if (BUTTON_IMPORT.test(source)) {
      assert.ok(buttons.length > 0, `${file} imports Button but no <Button element was found`);
    } else if (buttons.length > 0) {
      violations.push(`${file}: renders <Button> without importing it from @/components/ui/Button or ./ui/Button`);
    }
    for (const button of buttons) {
      const attrs = button.topLevelAttributes;
      const iconOnly = /\bicon=/.test(attrs) && !/\blabel=/.test(attrs);
      if (iconOnly && !/\bariaLabel=/.test(attrs)) {
        violations.push(`${file}:${button.line}: icon-only <Button> without ariaLabel`);
      }
    }

    const allowed = RAW_BUTTON_ALLOWLIST.filter((entry) => entry.file === file);
    const seen = new Map(allowed.map((entry) => [entry, 0]));
    for (const raw of jsxElements(source, "button")) {
      const entry = allowed.find((candidate) => raw.attributes.includes(candidate.marker));
      if (entry) {
        seen.set(entry, (seen.get(entry) ?? 0) + 1);
      } else {
        violations.push(`${file}:${raw.line}: raw <button> outside the allowlist; use Button`);
      }
    }
    for (const [entry, count] of seen) {
      if (count !== entry.count) {
        violations.push(`${file}: ${count} raw <button> with ${entry.marker}, allowlist expects ${entry.count}`);
      }
    }

    if (!SHARED_UI_IMPORT.test(source)) {
      violations.push(`${file}: no import from @/components/ui/ or ./ui/`);
    }
  }

  assert.deepEqual(violations, []);
});
