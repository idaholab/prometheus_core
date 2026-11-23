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

/* Feature: viewing an agent's artifacts in chat.
 *
 * When an agent's reply carries a mesh, an IFC building model, a Mermaid
 * diagram or a JSON file, the chat opens it in that kind of viewer, right
 * under the reply.
 * These tests open each viewer the way a user gets one, by asking in chat, and
 * check that the viewer drew the artifact, not only that its frame appeared.
 * They stand in for that feature's behavior spec until the platform has one
 * (TESTING.md, "Rules for every test").
 *
 * The stub agent (platform/e2e/stub-client-agent) answers a prompt naming
 * "mesh", "ifc", "diagram" or "json" with that viewer sample from
 * e2e/samples/, the same files the viewer playground shows. The mesh, IFC
 * model and JSON travel the way a real agent's files do: the agent gives the
 * backend a URL, and the backend fetches the file. The diagram travels inline
 * in the reply.
 *
 * Why end-to-end: the viewers are WebGL and SVG drawn from files the backend
 * converts or proxies, so jsdom component tests can't show they draw. These
 * tests catch a dependency or React upgrade that breaks a viewer.
 *
 * The IFC viewer loads web-ifc and its worker from unpkg, so its test needs
 * network access (PPLT-406 will serve them ourselves).
 *
 * Every test starts signed in as the e2e admin (global-setup.ts). */
import type { Locator, Page } from "@playwright/test";
import { expect, test } from "./fixtures";

/** Sends `prompt` from Home, waits for the stub's `answer`, and returns the
 * transcript area, where the artifact's viewer opens. */
async function ask(page: Page, prompt: string, answer: string): Promise<Locator> {
  await page.goto("/");
  const main = page.getByRole("main");
  await main.getByRole("textbox", { name: "Message" }).fill(prompt);
  await main.getByRole("textbox", { name: "Message" }).press("Enter");
  await expect(main.getByText(answer, { exact: true })).toBeVisible({ timeout: 30_000 });
  return main;
}

/**
 * How many sampled pixels of a viewer's canvas differ from its background, as
 * it shows on screen. A viewer that mounted but drew nothing reads 0. It works
 * from a screenshot, because a WebGL canvas can't be read back once the frame is
 * shown (VTK.js doesn't keep its drawing buffer). The page decodes the PNG; the
 * background is the color most of the top and bottom edges agree on, which a
 * centered model doesn't reach.
 */
async function paintedPixels(page: Page, canvas: Locator): Promise<number> {
  const png = (await canvas.screenshot()).toString("base64");
  return page.evaluate(async (base64) => {
    const image = new Image();
    image.src = `data:image/png;base64,${base64}`;
    await image.decode();
    const copy = document.createElement("canvas");
    copy.width = image.width;
    copy.height = image.height;
    const ctx = copy.getContext("2d")!;
    ctx.drawImage(image, 0, 0);
    const data = ctx.getImageData(0, 0, copy.width, copy.height).data;
    const rgb = (i: number) => [data[i], data[i + 1], data[i + 2]];
    const differs = (a: number[], b: number[]) =>
      Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]) + Math.abs(a[2] - b[2]) > 30;

    const edge: number[][] = [];
    for (let x = 0; x < copy.width; x += 8) {
      edge.push(rgb(x * 4), rgb(((copy.height - 1) * copy.width + x) * 4));
    }
    const background = edge.reduce((best, color) =>
      edge.filter((c) => !differs(c, color)).length > edge.filter((c) => !differs(c, best)).length
        ? color
        : best,
    );

    let painted = 0;
    for (let i = 0; i < data.length; i += 4 * 16) if (differs(rgb(i), background)) painted++;
    return painted;
  }, png);
}

/**
 * Behavior: a mesh in an agent's reply opens in the mesh viewer and draws.
 * - Given a signed-in user on Home,
 * - when an agent replies with an STL mesh (the sample part.stl),
 * - then the backend converts it to the viewer's VTP surface, and the browser
 *   loads that surface from the backend,
 * - and the mesh viewer opens under the reply with the file's name and its
 *   camera controls,
 * - and its canvas shows the part, not an empty background.
 */
test("a mesh in a reply opens in the mesh viewer and draws", async ({ page }) => {
  // The surface comes from the backend's conversion, not from the agent
  const surface = page.waitForResponse((response) =>
    /\/api\/artifacts\/mesh\/[^/]+\/[^/]+\.vtp$/.test(new URL(response.url()).pathname),
  );
  const main = await ask(page, "show me the mesh", "Here is the mesh.");

  expect((await surface).status(), "the converted surface the browser loads").toBe(200);
  await expect(main.getByText("part.stl")).toBeVisible();
  await expect(main.getByRole("button", { name: "Reset camera" })).toBeVisible();
  const canvas = main.locator("canvas").first();
  await expect(canvas).toBeVisible();
  await expect.poll(() => paintedPixels(page, canvas), { timeout: 30_000 }).toBeGreaterThan(100);
});

/**
 * Behavior: an IFC model in an agent's reply opens in the IFC viewer, draws,
 * and lists what the building holds.
 * - Given a signed-in user on Home,
 * - when an agent replies with an IFC building model (the sample model.ifc),
 * - then the browser loads the file through the backend's artifact content
 *   route,
 * - and the IFC viewer opens under the reply, with a panel listing the
 *   model's kinds of building element, its pipe runs and its equipment,
 * - and a link to download the IFC file,
 * - and its canvas shows the building, not an empty background.
 */
test("an IFC model in a reply opens in the IFC viewer, draws, and lists its elements", async ({ page }) => {
  const content = page.waitForResponse((response) =>
    /\/api\/artifacts\/[^/]+\/content$/.test(new URL(response.url()).pathname),
  );
  const main = await ask(page, "open the ifc model", "Here is the IFC model.");

  expect((await content).status(), "the IFC file the browser loads").toBe(200);
  // What the sample holds (e2e/samples/README.md): walls, a floor slab, columns,
  // a beam, a door, a window, a roof, two pipe segments and a pump
  for (const element of ["Walls", "Floors", "Columns", "Beams", "Doors", "Windows", "Roof"]) {
    await expect(
      main.getByRole("button", { name: element, exact: true }),
      `the ${element} toggle`,
    ).toBeVisible({ timeout: 60_000 });
  }
  await expect(main.getByRole("button", { name: "Pipe run 1 (1 segments)" })).toBeVisible();
  await expect(main.getByRole("button", { name: "Pump P-101" })).toBeVisible();
  await expect(main.getByRole("link", { name: "Download IFC" })).toBeVisible();
  const canvas = main.locator("canvas").first();
  await expect.poll(() => paintedPixels(page, canvas), { timeout: 60_000 }).toBeGreaterThan(100);
});

/**
 * Behavior: a Mermaid diagram in an agent's reply opens in the diagram viewer
 * with every node drawn.
 * - Given a signed-in user on Home,
 * - when an agent replies with a Mermaid flowchart (the sample diagram.mmd),
 * - then the diagram viewer opens under the reply, on its Diagram tab,
 * - and the drawn diagram shows every step of the flowchart.
 */
test("a Mermaid diagram in a reply opens in the diagram viewer with every node", async ({ page }) => {
  const main = await ask(page, "draw the diagram", "Here is the diagram.");

  await expect(main.getByRole("tab", { name: "Diagram" })).toBeVisible();
  const diagram = main.locator("svg[id^='mermaid']").first();
  await expect(diagram).toBeVisible();
  const nodes = [
    "Start",
    "Material data available?",
    "Run thermal analysis",
    "Fetch material data",
    "Status acceptable?",
    "Synthesize report",
    "Flag for review",
    "Done",
  ];
  for (const node of nodes) {
    await expect(diagram.getByText(node, { exact: true }), `the "${node}" node`).toBeVisible();
  }
});

/**
 * Behavior: a JSON file in an agent's reply opens in the JSON viewer with its
 * content, even when the reply carries only the file and not the JSON itself.
 * - Given a signed-in user on Home,
 * - when an agent replies with a JSON file by URL, with no inline copy (the
 *   sample results.json),
 * - then the browser loads the file through the backend's artifact content
 *   route,
 * - and the JSON viewer opens under the reply with its line count and a Copy
 *   button,
 * - and it shows the file's content, parsed: no "unparsed" badge.
 *
 * Why this case: a stored JSON file once opened as an empty viewer showing
 * "1 lines" and "unparsed" (PPLT-374), because the viewer read only inline JSON.
 */
test("a JSON file in a reply opens in the JSON viewer with its content", async ({ page }) => {
  const content = page.waitForResponse((response) =>
    /\/api\/artifacts\/[^/]+\/content$/.test(new URL(response.url()).pathname),
  );
  const main = await ask(page, "show me the json results", "Here are the results.");

  expect((await content).status(), "the JSON file the browser loads").toBe(200);
  // The viewer pretty-prints the JSON itself: results.json comes to 37 lines.
  // Its header doesn't show the file's name yet, so this doesn't check it (PPLT-467)
  await expect(main.getByRole("button", { name: /\b37 lines$/ })).toBeVisible();
  await expect(main.getByText("unparsed", { exact: true })).toHaveCount(0);
  await expect(main.getByRole("button", { name: "Copy JSON" })).toBeVisible();
  // Values from deep in the file, so a viewer that shows only its first line fails
  for (const text of ['"Sample bracket"', '"max_von_mises_mpa"', '"Stress limit"']) {
    await expect(main.getByText(text, { exact: true }).first(), `the ${text} value`).toBeVisible();
  }
});
