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

import type { ArtifactMeta } from "@/lib/api/types";
import { splitPerSample } from "@/lib/artifacts/perSample";
import { artifactsToElements } from "@/lib/elements/artifactAdapter";
import { ElementList } from "../ElementRenderer";
import { PerSampleList } from "../PerSampleList";

/** One assistant turn's artifacts: results render inline as viewers, while
 * per-sample plumbing (configs, ZDOs, failure logs of a UQ run) folds into one
 * closed list, the same split as the Artifacts tab. */
export function TurnArtifacts({
  artifacts,
  onSend,
}: {
  artifacts: ArtifactMeta[];
  onSend?: (text: string) => void;
}) {
  const { main, perSample } = splitPerSample(artifacts);
  return (
    <>
      <ElementList elements={artifactsToElements(main)} onSend={onSend} />
      <PerSampleList artifacts={perSample} />
    </>
  );
}
