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

/* Each viewer playground case becomes, through the chat's adapter, the custom element its
 * `viewer` names, and its `files` answer every URL that element fetches. The test imports
 * `./artifactAdapter.ts` like its sibling: the feature's `index.ts` loads every viewer, which Node cannot do. */
import assert from "node:assert/strict";
import { describe, test } from "vitest";

import type { ViewerCase } from "@/dev/viewer-playground/viewerCase";
import type { AnyElement } from "./elements";
import { artifactToElement } from "./artifactAdapter.ts";

const modules = import.meta.glob<{ default: ViewerCase }>("@/dev/viewer-playground/cases/*.case.ts", {
  eager: true,
});
const cases = Object.entries(modules).map(([path, mod]) => [path.split("/").pop() ?? path, mod.default] as const);

function caseNamed(file: string): ViewerCase {
  const found = cases.find(([name]) => name === file);
  assert.ok(found, `${file} is not among the loaded cases`);
  return found[1];
}

/** The manifest file names of a mesh element's props, or [] when it carries none. */
function manifestFilenames(props: Record<string, unknown>): string[] {
  const manifest = props.manifest as { files?: { filename?: unknown }[] } | undefined;
  return (manifest?.files ?? []).map((file) => String(file.filename));
}

/** Every URL the viewer of this element fetches: fileUrl, url, and each mesh manifest file. */
function fetchedUrls(element: AnyElement): string[] {
  const props = element.props ?? {};
  const urls: string[] = [];
  for (const key of ["fileUrl", "url"]) {
    if (typeof props[key] === "string") urls.push(props[key] as string);
  }
  for (const filename of manifestFilenames(props)) urls.push(`${String(props.baseUrl)}/${filename}`);
  return urls;
}

test("the glob loads the mesh, IFC, Mermaid and JSON cases", () => {
  const names = cases.map(([name]) => name);
  for (const expected of ["ifc.case.ts", "json.case.ts", "mermaid.case.ts", "mesh.case.ts"]) {
    assert.ok(names.includes(expected), `${expected} missing from ${JSON.stringify(names)}`);
  }
});

describe.each(cases)("%s", (_file, c) => {
  test("the adapter turns the artifact into the custom element the case names", () => {
    const element = artifactToElement(c.artifact);

    assert.equal(element.type, "custom");
    assert.equal(element.name, c.viewer);
  });

  test("every URL the element fetches has an entry in files", () => {
    const keys = Object.keys(c.files);
    const urls = fetchedUrls(artifactToElement(c.artifact));

    // A case that maps files must yield an element that fetches at least one of them
    if (keys.length > 0) assert.ok(urls.length > 0, `the element fetches none of ${JSON.stringify(keys)}`);
    for (const url of urls) {
      assert.ok(keys.includes(url), `${url} is not a key of files ${JSON.stringify(keys)}`);
    }
  });

  test("every files entry maps to a non-empty sample URL", () => {
    for (const [key, value] of Object.entries(c.files)) {
      assert.equal(typeof value, "string", `files[${key}] is not a string`);
      assert.ok(value.length > 0, `files[${key}] is empty`);
    }
  });
});

test("the JSON case element carries the content URL that CollapsibleJson fetches", () => {
  const c = caseNamed("json.case.ts");
  const props = artifactToElement(c.artifact).props ?? {};

  assert.equal(props.data, null);
  assert.equal(typeof props.url, "string");
  assert.ok(Object.keys(c.files).includes(props.url as string));
});

test("the IFC case element carries the file URL that IFCViewer fetches", () => {
  const c = caseNamed("ifc.case.ts");
  const props = artifactToElement(c.artifact).props ?? {};

  assert.equal(typeof props.fileUrl, "string");
  assert.ok(Object.keys(c.files).includes(props.fileUrl as string));
});

test("the mesh case element carries a manifest with at least one file", () => {
  const c = caseNamed("mesh.case.ts");
  const props = artifactToElement(c.artifact).props ?? {};

  assert.ok(manifestFilenames(props).length > 0, "the mesh props carry no manifest files");
});
