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

import { act, render, screen } from "@testing-library/react";
import { forwardRef, useImperativeHandle } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

const api = vi.hoisted(() => ({ meshProps: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ api, ApiError: class extends Error {} }));

// The real viewer needs WebGL; this one records the files it was asked to load.
const loaded = vi.hoisted(() => [] as string[]);
vi.mock("./MeshViewer", () => ({
  default: forwardRef(function FakeMeshViewer(_props, ref) {
    useImperativeHandle(ref, () => ({
      loadTimestep: (url: string) => {
        loaded.push(url);
        return Promise.resolve();
      },
      applyVariableColoring: () => [0, 1] as [number, number],
      clearVariableColoring: () => {},
      setColorPreset: () => {},
      setScalarRange: () => {},
      resetCamera: () => {},
      setBackground: () => {},
      setEdgeColor: () => {},
      getEngine: () => null,
    }));
    return <div data-testid="mesh-canvas" />;
  }),
}));

import type { AnyElement } from "@/features/artifacts/elements";
import { MeshViewerElement } from "./MeshViewerElement.tsx";

const files = [{ index: 0, timestep_index: 0, time_value: 0, filename: "surface_t0000.vtp" }];
const fetchedBody = {
  datasetId: "0123456789abcdef",
  baseUrl: "/api/artifacts/mesh/0123456789abcdef",
  manifest: { files, variables: { point: [], cell: [] }, array_ranges: {} },
  metadata: { num_timesteps: 1, time_values: [0] },
  title: "server title",
  height: "999px",
};

const element = (props: Record<string, unknown>): AnyElement =>
  ({ id: "m1", type: "custom", name: "MeshViewer", props }) as AnyElement;

beforeEach(() => {
  api.meshProps.mockReset();
  loaded.length = 0;
  vi.stubGlobal("IntersectionObserver", undefined); // load at once
});
afterEach(() => vi.unstubAllGlobals());

test("an inline manifest renders directly, with no fetch", async () => {
  render(<MeshViewerElement element={element({ ...fetchedBody, meshUrl: "/api/m" })} />);

  expect(await screen.findByTestId("mesh-canvas")).toBeInTheDocument();
  expect(api.meshProps).not.toHaveBeenCalled();
});

test("a mesh_url-only element fetches once and keeps its own title and height", async () => {
  api.meshProps.mockResolvedValue(fetchedBody);
  render(<MeshViewerElement element={element({ meshUrl: "/api/m", title: "out.e", height: "300px" })} />);

  expect(await screen.findByTestId("mesh-canvas")).toBeInTheDocument();
  expect(api.meshProps).toHaveBeenCalledTimes(1);
  // The fetched data reached the viewer...
  await act(async () => {});
  expect(loaded).toEqual(["/api/artifacts/mesh/0123456789abcdef/surface_t0000.vtp"]);
  // ...but the element's own title and height, not the server's.
  expect(screen.getByText("out.e")).toBeInTheDocument();
  expect(screen.queryByText("server title")).not.toBeInTheDocument();
  expect(screen.getByTestId("mesh-canvas").parentElement).toHaveStyle({ height: "300px" });
});

test("a different mesh_url starts over instead of showing the old mesh", async () => {
  api.meshProps.mockResolvedValue(fetchedBody);
  const { rerender } = render(<MeshViewerElement element={element({ meshUrl: "/api/m1", title: "one" })} />);
  expect(await screen.findByTestId("mesh-canvas")).toBeInTheDocument();

  vi.stubGlobal(
    "IntersectionObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  rerender(<MeshViewerElement element={element({ meshUrl: "/api/m2", title: "two" })} />);

  // Re-keyed: back to waiting for the new mesh to come into view, not the old viewer.
  expect(screen.queryByTestId("mesh-canvas")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Load mesh" })).toBeInTheDocument();
  expect(api.meshProps).toHaveBeenCalledTimes(1);
});
