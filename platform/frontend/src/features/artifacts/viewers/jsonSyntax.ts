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
 * Minimal JSON syntax tokenizer for read-only, code-block-style rendering.
 * No external highlighting library — JSON is the only language we need here,
 * so a small hand-rolled scanner keeps the bundle light and lets us map
 * token types onto the app's own DaisyUI semantic colors instead of a
 * generic code-editor palette.
 */

export type JsonTokenType =
  | "key"
  | "string"
  | "number"
  | "boolean"
  | "null"
  | "punct"
  | "space"
  | "text"; // fallback for lines that aren't valid JSON

export interface JsonToken {
  type: JsonTokenType;
  value: string;
}

// Order matters: "key" must be checked before generic "string".
const PATTERNS: Array<{ type: JsonTokenType; regex: RegExp }> = [
  { type: "key", regex: /^"(?:\\.|[^"\\])*"(?=\s*:)/ },
  { type: "string", regex: /^"(?:\\.|[^"\\])*"/ },
  { type: "number", regex: /^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/ },
  { type: "boolean", regex: /^(?:true|false)/ },
  { type: "null", regex: /^null/ },
  { type: "punct", regex: /^[{}[\],:]/ },
  { type: "space", regex: /^\s+/ },
];

/**
 * Tokenizes a single line of pretty-printed JSON. Assumes no token spans
 * multiple lines, which holds for JSON.stringify(x, null, 2) output since
 * real newlines inside string values are escaped as literal "\n".
 */
export function tokenizeJsonLine(line: string): JsonToken[] {
  const tokens: JsonToken[] = [];
  let rest = line;

  while (rest.length > 0) {
    let matched = false;
    for (const { type, regex } of PATTERNS) {
      const m = regex.exec(rest);
      if (m && m[0].length > 0) {
        tokens.push({ type, value: m[0] });
        rest = rest.slice(m[0].length);
        matched = true;
        break;
      }
    }
    if (!matched) {
      // Unexpected character — consume it as plain text so we never loop forever.
      tokens.push({ type: "text", value: rest[0] });
      rest = rest.slice(1);
    }
  }

  return tokens;
}

/**
 * Normalizes arbitrary agent output into pretty-printed JSON text.
 * Accepts an already-parsed object/array, or a raw JSON string.
 * Falls back to displaying the raw input as plain text if it isn't
 * parseable, rather than throwing.
 */
export function toPrettyJson(input: unknown): { text: string; valid: boolean } {
  if (input === undefined) {
    return { text: "", valid: false };
  }

  if (typeof input === "string") {
    try {
      const parsed = JSON.parse(input);
      return { text: JSON.stringify(parsed, null, 2), valid: true };
    } catch {
      return { text: input, valid: false };
    }
  }

  try {
    const stringified = JSON.stringify(input, null, 2);
    if (stringified === undefined) {
      // e.g. input was a function or symbol
      return { text: String(input), valid: false };
    }
    return { text: stringified, valid: true };
  } catch {
    return { text: String(input), valid: false };
  }
}
