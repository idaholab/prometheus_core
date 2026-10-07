import assert from "node:assert/strict";
import test from "node:test";

import { normalizeMime } from "./mime.ts";

test("strips parameters, whitespace and case", () => {
  assert.equal(normalizeMime("Text/CSV; charset=UTF-8"), "text/csv");
  assert.equal(normalizeMime("  application/json  "), "application/json");
});

test("missing input is an empty string", () => {
  assert.equal(normalizeMime(undefined), "");
  assert.equal(normalizeMime(null), "");
  assert.equal(normalizeMime(""), "");
});
