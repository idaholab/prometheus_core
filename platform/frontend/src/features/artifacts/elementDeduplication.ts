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

export type DeduplicatedElement = {
  id?: string;
  type?: string;
  name?: string;
  url?: string;
  path?: string;
  props?: Record<string, unknown>;
};

type ClassifyElement<T extends DeduplicatedElement> = (element: T) => string;

function elementId(element: DeduplicatedElement): string {
  return element.id ?? "";
}

function stringProp(element: DeduplicatedElement, name: string): string {
  const value = element.props?.[name];
  return typeof value === "string" ? value.trim() : "";
}

function resourceSignature(element: DeduplicatedElement): string {
  if (element.type === "custom") {
    const component = (element.name ?? "").trim();
    const resource =
      stringProp(element, "name") ||
      stringProp(element, "datasetId") ||
      stringProp(element, "artifactId") ||
      stringProp(element, "artifact_id") ||
      stringProp(element, "baseUrl");
    return [component, resource].filter(Boolean).join(":").toLowerCase();
  }

  return (
    (element.name ?? "").trim() ||
    element.url ||
    element.path ||
    elementId(element)
  ).toLowerCase();
}

function duplicateKey(element: DeduplicatedElement): string {
  return `${element.type}:${resourceSignature(element)}`;
}

export function dedupeElements<T extends DeduplicatedElement>(
  elements: T[],
  classifyElement: ClassifyElement<T>,
): T[] {
  const previewImageKeys = new Set(
    elements
      .filter((element) => element.type !== "file" && classifyElement(element) === "image")
      .map(resourceSignature)
      .filter(Boolean),
  );
  const seen = new Set<string>();

  return elements.filter((element) => {
    if (
      element.type === "file" &&
      classifyElement(element) === "image" &&
      previewImageKeys.has(resourceSignature(element))
    ) {
      return false;
    }

    const key = duplicateKey(element);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function elementKey(element: DeduplicatedElement): string {
  return elementId(element) || duplicateKey(element);
}
