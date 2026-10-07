import assert from "node:assert/strict";
import test from "node:test";

import { languageFor, languageForArtifact } from "./language.ts";

test("MIME wins over the file name", () => {
  assert.equal(languageFor("notes.txt", "text/x-python"), "python");
  assert.equal(languageFor("sample", "application/toml; charset=utf-8"), "ini");
  assert.equal(languageFor("sample", "application/yaml"), "yaml");
  assert.equal(languageFor("sample", "text/x-moose"), "moose");
});

test("file name routes by extension, case-insensitively", () => {
  assert.equal(languageFor("solver.py", null), "python");
  assert.equal(languageFor("kernel.F90", undefined), "fortran");
  assert.equal(languageFor("mesh.xdmf", ""), "xml");
  assert.equal(languageFor("pyproject.toml", "text/plain"), "ini");
  // The routes this PR started with.
  assert.equal(languageFor("input.i", null), "moose");
  assert.equal(languageFor("config.YML", null), "yaml");
  assert.equal(languageFor("config.yaml", "text/plain"), "yaml");
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

test("languageForArtifact checks the uri before the name, like the backend", () => {
  // Routed to `code` by the uri's suffix; the display name has none.
  assert.equal(languageForArtifact({ name: "MOOSE input", uri: "deeplynx://x/items/1/input.i" }), "moose");
  assert.equal(languageForArtifact({ name: "Build file", uri: "file:///tmp/Dockerfile" }), "dockerfile");
  // The uri wins over a conflicting name; the name is the fallback.
  assert.equal(languageForArtifact({ name: "a.sql", uri: "file:///tmp/b.py" }), "python");
  assert.equal(languageForArtifact({ name: "solver.py", uri: "deeplynx://x/items/1" }), "python");
  assert.equal(languageForArtifact({ name: "x", uri: null }), undefined);
});

test("languageForArtifact: MIME first, and generic .txt/.log do not override a text MIME", () => {
  assert.equal(languageForArtifact({ name: "a.sql", uri: null, mime_type: "text/x-python" }), "python");
  // text/plain + a .txt uri falls through to the name, as the backend does.
  assert.equal(
    languageForArtifact({ name: "solver.py", uri: "file:///tmp/artifact.txt", mime_type: "text/plain" }),
    "python",
  );
  assert.equal(languageForArtifact({ name: "artifact.txt", uri: null, mime_type: "text/plain" }), undefined);
  // With no text MIME, .txt/.log still map to plaintext.
  assert.equal(languageForArtifact({ name: "run.log", uri: null }), "plaintext");
  assert.equal(languageForArtifact({ name: "run.log", uri: null, mime_type: "application/octet-stream" }), "plaintext");
});
