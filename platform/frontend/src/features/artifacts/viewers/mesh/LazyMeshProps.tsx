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
 * Fetches a mesh artifact's viewer props from `meshUrl` once the viewer comes near the
 * viewport, then renders `children` with them.
 *
 * The backend converts the Exodus/STL source on that first request, which can take
 * seconds, so this shows progress meanwhile; on failure it shows the reason, a retry
 * and a link to the raw file. A mesh far down a long conversation never converts until
 * someone scrolls to it.
 */

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { meshManifestProps } from "@/features/artifacts/meshManifest";
import { Button, buttonClassName } from "@/components/ui/Button";
import { api } from "@/lib/api/client";
import { MESH_FETCH_TIMEOUT_MS, meshFailureMessage } from "./meshFailure";
import { MeshCrashBoundary } from "./MeshCrashBoundary";
import { useNearViewport } from "./useNearViewport";

type Props = {
  meshUrl: string;
  downloadUrl?: string;
  title: string;
  height: string;
  children: (props: Record<string, unknown>) => ReactNode;
};

type State =
  | { kind: "waiting" }
  | { kind: "loading" }
  | { kind: "ready"; props: Record<string, unknown> }
  | { kind: "failed"; message: string };

export function LazyMeshProps({ meshUrl, downloadUrl, title, height, children }: Props) {
  const placeholderRef = useRef<HTMLDivElement>(null);
  const inView = useNearViewport(placeholderRef);
  // The observer's root is the page viewport while the chat scrolls in its own
  // container (until 5d passes that container), so a visible viewer can still be
  // "waiting": the user can start it themselves.
  const [requested, setRequested] = useState(false);
  const near = inView || requested;
  const [state, setState] = useState<State>({ kind: "waiting" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!near) return;
    let live = true;
    let timedOut = false;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, MESH_FETCH_TIMEOUT_MS);
    setState({ kind: "loading" });
    api.meshProps(meshUrl, controller.signal).then(
      (body) => {
        if (!live) return;
        const props = meshManifestProps(body);
        setState(
          props ? { kind: "ready", props } : { kind: "failed", message: "The server returned no mesh data." },
        );
      },
      (err: unknown) => live && setState({ kind: "failed", message: meshFailureMessage(err, timedOut) }),
    );
    return () => {
      live = false;
      clearTimeout(timer);
      // The backend finishes the conversion anyway (it is shared and shielded).
      controller.abort();
    };
  }, [near, meshUrl, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  const download = downloadUrl && (
    <a className={buttonClassName({ variant: "ghost", size: "xs" })} href={downloadUrl} download>
      Download original file
    </a>
  );

  if (state.kind === "ready") {
    return (
      <MeshCrashBoundary
        fallback={
          <div className="my-2 flex w-full flex-col items-center gap-2 rounded-lg border border-base-300 p-4 text-sm">
            <span role="alert" className="text-error/80">
              The mesh viewer crashed.
            </span>
            {download}
          </div>
        }
      >
        {children(state.props)}
      </MeshCrashBoundary>
    );
  }

  return (
    <div
      ref={placeholderRef}
      className="my-2 flex w-full flex-col items-center justify-center gap-2 rounded-lg border border-base-300 bg-base-200/40 p-4 text-sm"
      style={{ minHeight: height }}
      aria-busy={state.kind === "loading"}
    >
      <span className="font-medium text-base-content">{title}</span>
      {state.kind === "failed" && (
        <>
          <span role="alert" className="text-error/80">
            {state.message}
          </span>
          <span className="flex gap-2">
            <Button label="Retry" size="xs" outline onClick={retry} />
            {download}
          </span>
          {downloadUrl && (
            <span className="text-xs text-base-content/50">
              The original file opens in a mesh tool such as ParaView.
            </span>
          )}
        </>
      )}
      {state.kind === "loading" && (
        <span className="flex items-center gap-2 text-base-content/60">
          <span className="loading loading-spinner loading-xs" />
          Preparing mesh… the first view can take a minute.
        </span>
      )}
      {state.kind === "waiting" && (
        <Button label="Load mesh" size="xs" outline onClick={() => setRequested(true)} />
      )}
    </div>
  );
}
