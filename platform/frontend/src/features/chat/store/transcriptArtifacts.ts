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
 * Give each turn of a resumed conversation the artifacts that turn produced.
 *
 * `GET /api/conversations/{id}` returns the conversation's artifact catalog plus, per
 * message, the `artifact_ids` the client-agent recorded on that reply. The Prometheus
 * Artifact Contract ("Frontend viewer ownership") says the catalog is state for future
 * turns and never a rendering source: a generated output renders only under the
 * response that created it. So a restored turn shows exactly its own ids, resolved in
 * the catalog, and nothing else. An id the catalog does not hold (a user upload, which
 * the backend leaves out) is skipped, and a turn with no ids (a user turn, or one stored
 * before the ids were recorded) shows none.
 *
 * Kept as a dependency-free leaf module so it is unit-testable under `node --test`
 * (`chat.ts` itself pulls in the API client and can only run inside Vite).
 */

/** Minimal shape needed from a transcript entry. */
export type TurnLike = {
  role: "user" | "assistant";
  artifact_ids?: string[] | null;
};

/** Minimal shape needed from a catalog entry. */
export type IdentifiedArtifact = {
  artifact_id: string;
};

/**
 * One array per entry in `messages`: the catalog entries named by that message's
 * `artifact_ids`, in that order, each at most once per turn. User entries stay empty.
 */
export function artifactsPerTurn<A extends IdentifiedArtifact>(messages: TurnLike[], catalog: A[]): A[][] {
  const byId = new Map(catalog.map((a) => [a.artifact_id, a] as const));
  return messages.map((m) => {
    if (m.role !== "assistant") return [];
    const ids = [...new Set(m.artifact_ids ?? [])];
    return ids.flatMap((id) => byId.get(id) ?? []);
  });
}
