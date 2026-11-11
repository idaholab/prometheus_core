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

type ArtifactFileElement = {
  name?: string;
  props?: Record<string, unknown>;
};

export function artifactFilePresentation(element: ArtifactFileElement): {
  label: string;
  filename: string;
} {
  const filename = element.name?.trim() || "Attachment";
  const description = element.props?.description;
  const label =
    typeof description === "string" && description.trim()
      ? description.trim()
      : filename;

  return { label, filename };
}
