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

// Shared, engine-agnostic grouping rules for the viewer visibility trees.
//
// Both IFCViewerEngine (matching on IFC element Name) and OBJViewerEngine
// (matching on OBJ mesh names, which carry the same IFC Name — see
// alchemy-backend/app/processing.py, which writes each product as
// `o IfcType__Name` with spaces turned into underscores) import these so the
// two viewers group identically from a single source of truth.
//
// The regexes are pinned to the names the backend authors in
// ifcplus/api/built_element/insulated_metal_panel.py (envelope panels and
// flashing) and ifcplus/api/building/clear_span_industrial_building.py (column
// base plates). src/tests/components/viewer/IFCViewerEngine.test.ts fails if a
// rename there makes these go inert.

// A piece of an insulated-metal-panel wall face: the capture is the panel name,
// e.g. "Envelope Panel - Side Wall at X Max"; the second group is the layer.
export const WALL_PANEL_PIECE =
  /^(Envelope Panel - (?:Side|End) Wall .+) - (Outer Skin|Core|Inner Liner)$/i;

// The roof is authored identically to a wall face.
export const ROOF_PANEL_PIECE =
  /^(Envelope Panel - Roof.*) - (Outer Skin|Core|Inner Liner)$/i;

// Flashing closing the joints. Corner flashing runs vertically between two wall
// faces, so it follows the walls; eave/rake flashing caps the roof edge.
export const CORNER_FLASHING = /^Envelope Flashing - Corner .+$/i;
export const EDGE_FLASHING = /^Envelope Flashing - (?:Eave|Rake) .+$/i;

// A column base-plate assembly carries the column's grid name, e.g.
// "Base Plate for Column A1 - Base Plate" / "... - Anchor Bolt 0". The capture
// is the column name ("Column A1"), which is the join key back to the column.
export const BASEPLATE_FOR = /^Base Plate for (.+?)(?: - .+)?$/i;

// Outer skin → core → inner liner, so a panel's layers read outside-in.
const PIECE_ORDER = ["Outer Skin", "Core", "Inner Liner"];

// One element the caller handed in, identified by whatever id its engine uses
// (Fragments localId for IFC, a synthetic index for OBJ).
export type NamedItem = { id: number; name: string };

// A structural group derived from names alone — no engine/model specifics. The
// caller turns these into its own id maps and toggle keys.
export type NameGroup = {
  label: string;
  members: { id: number; label: string }[];
};

// What an engine returns to the overlay: a parent group with toggle keys baked
// in, its member pieces nested. The overlay renders walls/roof/columns and pipe
// runs through the same GroupedTreeSection, so both engines use this shape.
export type TreeGroupMember = { key: string; label: string };
export type TreeGroup = {
  key: string;
  label: string;
  members: TreeGroupMember[];
};

const byLabel = (a: { label: string }, b: { label: string }): number =>
  a.label.localeCompare(b.label, undefined, { numeric: true });

// Shared implementation for walls and roof: bucket panel pieces by panel name,
// then collect the matching flashing into one trailing group. Returns [] when
// nothing matches, which the caller reads as "no layers — keep the flat toggle".
function groupPanelPieces(
  items: NamedItem[],
  piecePattern: RegExp,
  flashingPattern: RegExp,
  flashingLabel: string,
): NameGroup[] {
  const panels = new Map<string, { id: number; label: string }[]>();
  const flashing: { id: number; label: string }[] = [];

  for (const item of items) {
    const piece = piecePattern.exec(item.name);
    if (piece) {
      const [, panelName, layer] = piece;
      if (!panels.has(panelName)) panels.set(panelName, []);
      panels.get(panelName)!.push({ id: item.id, label: layer });
      continue;
    }
    if (flashingPattern.test(item.name)) {
      flashing.push({
        id: item.id,
        label: item.name.replace(/^Envelope Flashing - /i, ""),
      });
    }
  }

  const groups: NameGroup[] = [];
  for (const [label, members] of panels) {
    members.sort(
      (a, b) => PIECE_ORDER.indexOf(a.label) - PIECE_ORDER.indexOf(b.label),
    );
    groups.push({ label, members });
  }
  groups.sort(byLabel);

  if (flashing.length > 0) {
    flashing.sort(byLabel);
    groups.push({ label: flashingLabel, members: flashing });
  }

  return groups;
}

export function groupWallPieces(items: NamedItem[]): NameGroup[] {
  return groupPanelPieces(
    items,
    WALL_PANEL_PIECE,
    CORNER_FLASHING,
    "Corner Flashing",
  );
}

export function groupRoofPieces(items: NamedItem[]): NameGroup[] {
  return groupPanelPieces(
    items,
    ROOF_PANEL_PIECE,
    EDGE_FLASHING,
    "Eave & Rake Flashing",
  );
}

// Each column becomes a group with the column shaft as its first member and its
// base-plate assembly (plate + anchor bolts + hex nuts) nested under it, matched
// by the "Base Plate for <column name>" prefix. Returns [] when no column has
// any base-plate member, so the caller keeps the flat Columns toggle.
export function groupColumnsWithBasePlates(
  columns: NamedItem[],
  candidates: NamedItem[],
): NameGroup[] {
  // Column name → the base-plate pieces bolted to it.
  const platesByColumn = new Map<string, { id: number; label: string }[]>();
  for (const cand of candidates) {
    const match = BASEPLATE_FOR.exec(cand.name);
    if (!match) continue;
    const columnName = match[1];
    if (!platesByColumn.has(columnName)) platesByColumn.set(columnName, []);
    platesByColumn.get(columnName)!.push({
      id: cand.id,
      // "Base Plate for Column A1 - Anchor Bolt 0" → "Anchor Bolt 0".
      label: cand.name.replace(/^Base Plate for .+? - /i, "") || cand.name,
    });
  }

  let anyMatched = false;
  const groups: NameGroup[] = [];
  for (const column of columns) {
    const plates = platesByColumn.get(column.name) ?? [];
    if (plates.length > 0) anyMatched = true;
    plates.sort(byLabel);
    groups.push({
      label: column.name,
      members: [{ id: column.id, label: "Column" }, ...plates],
    });
  }

  if (!anyMatched) return [];
  groups.sort(byLabel);
  return groups;
}
