import assert from "node:assert/strict";
import test from "node:test";

import { highlightToHtml } from "./index.ts";

const SAMPLES: Record<string, string> = {
  bash: "#!/bin/bash\necho \"hi\"\n",
  c: "#include <stdio.h>\nint main(void) { return 0; }\n",
  cmake: "cmake_minimum_required(VERSION 3.20)\nproject(demo)\n",
  cpp: "#include <vector>\nclass A { public: int x; };\n",
  diff: "--- a\n+++ b\n@@ -1 +1 @@\n-old\n+new\n",
  dockerfile: "FROM python:3.13\nRUN echo hi\n",
  fortran: "program demo\n  print *, 'hi'\nend program demo\n",
  ini: "[section]\nkey = \"value\"\n",
  javascript: "const x = () => 1;\n",
  json: "{\"a\": [1, 2, true]}\n",
  makefile: "all:\n\techo hi\n",
  moose: "[Mesh]\n  type = GeneratedMesh\n[]\n",
  plaintext: "just some text\n",
  python: "def f(x):\n    return x + 1\n",
  sql: "SELECT a FROM t WHERE b = 1;\n",
  typescript: "const x: number = 1;\n",
  xml: "<a b=\"1\"><c/></a>\n",
  yaml: "a:\n  - 1\n  - b\n",
};

test("every registered language highlights", () => {
  for (const [language, code] of Object.entries(SAMPLES)) {
    const html = highlightToHtml(code, language);
    assert.notEqual(html, null, `${language} should highlight`);
    // A grammar that matches nothing still returns a string (escaped text), so also
    // require at least one token span. plaintext has no tokens by design.
    if (language !== "plaintext") {
      assert.match(html ?? "", /<span class="hljs-/, `${language} should emit tokens`);
    }
  }
});

test("unregistered, empty and oversized input is not highlighted", () => {
  assert.equal(highlightToHtml("x", "cobol"), null);
  assert.equal(highlightToHtml("x", undefined), null);
  assert.equal(highlightToHtml("", "python"), null);
  assert.equal(highlightToHtml("x".repeat(200_001), "python"), null);
  // The cutoff is exact: 200,000 characters still highlight, one more does not.
  assert.notEqual(highlightToHtml("x".repeat(200_000), "python"), null);
});
