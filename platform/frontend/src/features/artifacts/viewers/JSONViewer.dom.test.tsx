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

/* The JSON viewer renders an inline `json_body` as it is, and fetches a file-backed
 * JSON artifact from its content URL; both need a live React tree to check. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { JSONViewer } from "./JSONViewer.tsx";

/** Render the viewer for the element the artifact adapter builds for a JSON artifact. */
const renderJsonViewer = (props: Record<string, unknown>) =>
  render(<JSONViewer element={{ type: "custom", name: "CollapsibleJson", props }} />);

/** Stub `fetch` with a call that stays pending until the test answers it. */
function stubFetch() {
  let answer: (res: Response) => void = () => {};
  const fetchMock = vi.fn<typeof fetch>(
    () =>
      new Promise<Response>((resolve) => {
        answer = resolve;
      }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, respond: (body: string, init?: ResponseInit) => answer(new Response(body, init)) };
}

/** Stub `navigator.clipboard.writeText`, which jsdom does not provide. */
function stubClipboard() {
  const writeText = vi.fn<(text: string) => Promise<void>>(() => Promise.resolve());
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  return writeText;
}

afterEach(() => {
  vi.unstubAllGlobals();
  Reflect.deleteProperty(navigator, "clipboard");
});

describe("json_viewer_shows_inline_and_fetched_json", () => {
  const CONTENT_URL = "/api/artifacts/X/content";
  const PRETTY = ["{", '  "a": 1,', '  "b": [', "    true,", "    null", "  ]", "}"].join("\n");

  test("inline data renders highlighted without a network call, and Copy writes the pretty text", async () => {
    const { fetchMock } = stubFetch();
    const writeText = stubClipboard();
    renderJsonViewer({ data: { a: 1, b: [true, null] }, url: CONTENT_URL });

    expect(screen.getByText("7 lines")).toBeInTheDocument();
    expect(screen.getByText('"a"')).toHaveClass("text-primary");
    expect(screen.queryByText("unparsed")).not.toBeInTheDocument();
    expect(screen.queryByText("Loading…")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Copy JSON" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(PRETTY));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test("null data fetches the content URL, shows Loading… first, then the same body", async () => {
    const { fetchMock, respond } = stubFetch();
    const writeText = stubClipboard();
    renderJsonViewer({ data: null, url: CONTENT_URL });

    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(screen.queryByText("7 lines")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copy JSON" })).not.toBeInTheDocument();

    respond('{"a":1,"b":[true,null]}');
    expect(await screen.findByText("7 lines")).toBeInTheDocument();
    expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
    expect(screen.getByText('"a"')).toHaveClass("text-primary");
    expect(screen.queryByText("unparsed")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledWith(CONTENT_URL, { credentials: "include" });

    fireEvent.click(screen.getByRole("button", { name: "Copy JSON" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(PRETTY));
  });
});

describe("json_viewer_shows_fetch_error_and_raw_text", () => {
  const CONTENT_URL = "/api/artifacts/X/content";

  test("a failed fetch shows the error row, with no lines, no badge and no Copy button", async () => {
    const { respond } = stubFetch();
    renderJsonViewer({ data: null, url: CONTENT_URL });

    respond("bad gateway", { status: 502 });
    const error = await screen.findByText("Couldn't load this file.");
    expect(error.querySelector("svg")).not.toBeNull();
    expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
    expect(screen.queryByText(/ lines$/)).not.toBeInTheDocument();
    expect(screen.queryByText("1")).not.toBeInTheDocument();
    expect(screen.queryByText("Empty file")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copy JSON" })).not.toBeInTheDocument();
  });

  test("fetched text that is not JSON renders raw on one line with the unparsed badge", async () => {
    const { respond } = stubFetch();
    const writeText = stubClipboard();
    renderJsonViewer({ data: null, url: CONTENT_URL });

    respond("not json {");
    expect(await screen.findByText("1 lines")).toBeInTheDocument();
    expect(screen.getByText("unparsed")).toBeInTheDocument();
    const line = screen.getByText("not json {");
    expect(line.children).toHaveLength(0);
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.queryByText("Couldn't load this file.")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Copy JSON" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("not json {"));
  });

  test("an empty fetched body shows the Empty file row, with no badge and no Copy button", async () => {
    const { respond } = stubFetch();
    renderJsonViewer({ data: null, url: CONTENT_URL });

    respond("");
    expect(await screen.findByText("Empty file")).toBeInTheDocument();
    expect(screen.queryByText(/ lines$/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copy JSON" })).not.toBeInTheDocument();
  });
});

describe("json_viewer_keeps_collapse_and_height", () => {
  const CONTENT_URL = "/api/artifacts/X/content";
  const header = () => screen.getByRole("button", { name: /CollapsibleJson/ });
  const body = () => screen.getByText('"a"').closest(".overflow-y-auto");

  test("defaultCollapsed still fetches, hides the lines until one header click, and keeps maxHeight", async () => {
    const { fetchMock, respond } = stubFetch();
    renderJsonViewer({ data: null, url: CONTENT_URL, defaultCollapsed: true, maxHeight: 120 });

    expect(header()).toHaveAttribute("aria-expanded", "false");
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledWith(CONTENT_URL, { credentials: "include" });

    respond('{"a":1,"b":[true,null]}');
    expect(await screen.findByText("7 lines")).toBeInTheDocument();
    expect(screen.queryByText('"a"')).not.toBeInTheDocument();
    expect(screen.queryByText("7")).not.toBeInTheDocument();

    fireEvent.click(header());
    expect(header()).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText('"a"')).toHaveClass("text-primary");
    expect(body()).toHaveStyle({ maxHeight: "120px" });
  });

  test("inline data starts expanded at the 400px default height and collapses on a header click", () => {
    stubFetch();
    renderJsonViewer({ data: { a: 1, b: [true, null] } });

    expect(header()).toHaveAttribute("aria-expanded", "true");
    expect(body()).toHaveStyle({ maxHeight: "400px" });

    fireEvent.click(header());
    expect(header()).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText('"a"')).not.toBeInTheDocument();
    expect(screen.queryByText("7")).not.toBeInTheDocument();
  });

  test("valid JSON over the highlight cap renders its lines as plain text, with the badge and Copy kept", () => {
    stubFetch();
    // Three 400,000-char strings: about 1.2M pretty chars, above MAX_HIGHLIGHT_CHARS (1,000,000) in JSONViewer.tsx.
    const long = "x".repeat(400_000);
    const { container } = renderJsonViewer({ data: [long, long, long] });

    expect(screen.getByText("5 lines")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getAllByText(`"${long}",`, { normalizer: (t) => t.trim() })).toHaveLength(2);
    expect(container.querySelector(".text-primary, .text-success, .text-info")).toBeNull();
    expect(screen.queryByText("unparsed")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy JSON" })).toBeInTheDocument();
  });
});
