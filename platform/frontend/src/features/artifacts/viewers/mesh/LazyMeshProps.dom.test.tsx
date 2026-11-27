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

/* LazyMeshProps waits for the viewport, fetches once, and recovers from a failure. */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

const api = vi.hoisted(() => ({ meshProps: vi.fn() }));
const ApiError = vi.hoisted(
  () =>
    class ApiError extends Error {
      constructor(
        public status: number,
        message: string,
      ) {
        super(message);
      }
    },
);
vi.mock("@/lib/api/client", () => ({ api, ApiError }));

import { LazyMeshProps } from "./LazyMeshProps.tsx";
import { MESH_FETCH_TIMEOUT_MS } from "./meshFailure.ts";

/** A controllable IntersectionObserver: `enter()` reports every observed element visible. */
const observers: { cb: IntersectionObserverCallback; els: Element[] }[] = [];
class FakeObserver {
  els: Element[] = [];
  constructor(public cb: IntersectionObserverCallback) {
    observers.push(this);
  }
  observe(el: Element) {
    this.els.push(el);
  }
  disconnect() {
    this.els = [];
  }
}
const enter = () =>
  act(() => {
    for (const o of observers)
      o.cb(
        o.els.map((target) => ({ target, isIntersecting: true }) as IntersectionObserverEntry),
        o as unknown as IntersectionObserver,
      );
  });

beforeEach(() => {
  observers.length = 0;
  api.meshProps.mockReset();
  vi.stubGlobal("IntersectionObserver", FakeObserver);
});
afterEach(() => vi.unstubAllGlobals());

/** A body the viewer can render: a base URL and a manifest naming a VTP file. */
const mesh = (datasetId: string) => ({
  datasetId,
  baseUrl: `/api/artifacts/mesh/${datasetId}`,
  manifest: { files: [{ index: 0, timestep_index: 0, time_value: 0, filename: "surface_t0000.vtp" }] },
});

const renderLazy = () =>
  render(
    <LazyMeshProps meshUrl="/api/m" downloadUrl="/api/c" title="out.e" height="450px">
      {(props) => <div>viewer {String(props.datasetId)}</div>}
    </LazyMeshProps>,
  );

test("nothing is fetched until the viewer comes near the viewport", async () => {
  api.meshProps.mockResolvedValue(mesh("ds1"));
  renderLazy();

  expect(api.meshProps).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Load mesh" })).toBeInTheDocument();
  // Nothing is in flight yet, so the placeholder doesn't claim to be busy.
  expect(screen.getByRole("button", { name: "Load mesh" }).parentElement).toHaveAttribute(
    "aria-busy",
    "false",
  );

  enter();
  expect(await screen.findByText("viewer ds1")).toBeInTheDocument();
  expect(api.meshProps).toHaveBeenCalledTimes(1);
  expect(api.meshProps).toHaveBeenCalledWith("/api/m", expect.any(AbortSignal));
});

test("a failed conversion shows why, a download link, and retries on request", async () => {
  api.meshProps.mockRejectedValueOnce(new ApiError(422, "Could not convert out.e for viewing."));
  api.meshProps.mockResolvedValueOnce(mesh("ds1"));
  renderLazy();
  enter();

  expect(await screen.findByRole("alert")).toHaveTextContent("Could not convert out.e for viewing.");
  expect(screen.getByRole("link", { name: "Download original file" })).toHaveAttribute("href", "/api/c");

  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText("viewer ds1")).toBeInTheDocument();
  expect(api.meshProps).toHaveBeenCalledTimes(2);
});

test("without IntersectionObserver it loads at once", async () => {
  vi.stubGlobal("IntersectionObserver", undefined);
  api.meshProps.mockResolvedValue(mesh("ds2"));
  renderLazy();

  expect(await screen.findByText("viewer ds2")).toBeInTheDocument();
});

test("a successful response without mesh data shows the failure card", async () => {
  api.meshProps.mockResolvedValue({ datasetId: "ds3" });
  renderLazy();
  enter();

  expect(await screen.findByRole("alert")).toHaveTextContent("The server returned no mesh data.");
  expect(screen.queryByText(/viewer/)).not.toBeInTheDocument();
});

test("a request that never answers times out into the failure card", async () => {
  vi.useFakeTimers();
  try {
    let signal: AbortSignal | undefined;
    api.meshProps.mockImplementation(
      (_url: string, s: AbortSignal) =>
        new Promise((_resolve, reject) => {
          signal = s;
          s.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        }),
    );
    renderLazy();
    enter();
    expect(screen.getByText(/Preparing mesh/)).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(MESH_FETCH_TIMEOUT_MS);
    });

    expect(signal?.aborted).toBe(true);
    expect(screen.getByRole("alert")).toHaveTextContent("Preparing the mesh took too long.");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  } finally {
    vi.useRealTimers();
  }
});

test("unmounting aborts the request", () => {
  let signal: AbortSignal | undefined;
  api.meshProps.mockImplementation((_url: string, s: AbortSignal) => {
    signal = s;
    return new Promise(() => {});
  });
  const { unmount } = renderLazy();
  enter();

  unmount();

  expect(signal?.aborted).toBe(true);
});

test("the Load mesh button fetches a viewer the observer hasn't reported", async () => {
  api.meshProps.mockResolvedValue(mesh("ds4"));
  renderLazy();

  fireEvent.click(screen.getByRole("button", { name: "Load mesh" }));

  expect(await screen.findByText("viewer ds4")).toBeInTheDocument();
  expect(api.meshProps).toHaveBeenCalledTimes(1);
});

test("while loading the placeholder is busy and says the first view can take a while", () => {
  api.meshProps.mockReturnValue(new Promise(() => {}));
  renderLazy();
  enter();

  const progress = screen.getByText(/the first view can take a minute/);
  expect(progress.closest("[aria-busy]")).toHaveAttribute("aria-busy", "true");
  expect(screen.queryByRole("button", { name: "Load mesh" })).not.toBeInTheDocument();
});
