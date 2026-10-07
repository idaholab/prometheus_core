import assert from "node:assert/strict";
import test from "node:test";

import { highlightToHtml, languageFor } from "./index.ts";

test("MIME wins over the file name", () => {
  assert.equal(languageFor("notes.txt", "text/x-python"), "python");
  assert.equal(languageFor("sample", "application/toml; charset=utf-8"), "ini");
});

test("file name routes by extension, case-insensitively", () => {
  assert.equal(languageFor("solver.py", null), "python");
  assert.equal(languageFor("kernel.F90", undefined), "fortran");
  assert.equal(languageFor("mesh.xdmf", ""), "xml");
  assert.equal(languageFor("pyproject.toml", "text/plain"), "ini");
});

test("whole file names beat the extension", () => {
  assert.equal(languageFor("CMakeLists.txt", null), "cmake");
  assert.equal(languageFor("Dockerfile", null), "dockerfile");
  assert.equal(languageFor("build/Makefile", null), "makefile");
  assert.equal(languageFor("notes.txt", null), "plaintext");
});

test("a dot in a directory name is not an extension", () => {
  assert.equal(languageFor("v1.2/Makefile", null), "makefile");
  assert.equal(languageFor("v1.2/README", null), undefined);
});

test("application/json is not routed here; .jsonc is", () => {
  assert.equal(languageFor("data.json", "application/json"), undefined);
  assert.equal(languageFor("settings.jsonc", null), "json");
});

test("unknown input has no language", () => {
  assert.equal(languageFor(null, null), undefined);
  assert.equal(languageFor("archive.zip", "application/zip"), undefined);
});

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
  }
});

test("unregistered, empty and oversized input is not highlighted", () => {
  assert.equal(highlightToHtml("x", "cobol"), null);
  assert.equal(highlightToHtml("x", undefined), null);
  assert.equal(highlightToHtml("", "python"), null);
  assert.equal(highlightToHtml("x".repeat(200_001), "python"), null);
});
