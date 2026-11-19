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

// The Walls and Roof toggles have to reach inside an insulated-metal-panel
// envelope. The backend authors each face as a bodyless IfcWall/IfcRoof
// decomposed into two IfcPlate skins and an IfcBuildingElementPart core, plus
// IfcDiscreteAccessory flashing that belongs to no entity-type category, so
// hiding by entity class alone hides nothing a user can see.
//
// These tests pin the CATEGORY_NAME_PATTERNS regexes to the names the backend
// actually writes (taken from tests/output/ifcplus/api/building/
// clear_span_industrial_buildings.ifc). If the backend renames a panel or a
// piece, this suite fails instead of the toggle quietly going inert.

import { describe, it, expect, beforeEach, vi } from 'vitest';
// Engine mocks, from Alchemy's tests/fixtures/viewerEngine.fixtures.ts.
// viewerEngine.fixtures.ts
//
// Shared mock scaffolding for tests touching IFCViewerEngine. The engine wires
// up a whole @thatopen/components world in its constructor, so that library is
// mocked down to the surface the constructor and the visibility methods
// actually touch.
//
// The important part is that the mocks are not inert stubs: setModelElements()
// installs a small table of IFC elements, and both getItemsOfCategories() and
// the ItemsFinder query really do evaluate the engine's own regexes against it.
// A wrong or over-broad pattern in CATEGORY_NAME_PATTERNS therefore fails a
// test instead of sailing through a stub that answers whatever it is asked.
//
// Note: vi.mock() calls are hoisted within the file they're written in, so they
// still take effect here even though this file is imported by the test file
// rather than containing the tests itself - as long as this file is imported
// (statically) before IFCViewerEngine is loaded.


// One row of the fake model. localId is what the real Fragments API hands back
// and what Hider.set() is given, so the tests assert on sets of these.
// `bodyless: true` marks an element Fragments produced no geometry for (an
// insulated-metal-panel IfcWall/IfcRoof container, decomposed into its pieces) —
// getItemsIdsWithGeometry() below omits those, mirroring the real model.
type FakeElement = {
  localId: number;
  ifcClass: string;
  name: string;
  bodyless?: boolean;
};

const MODEL_ID = 'model-1';

let elements: FakeElement[] = [];

function setModelElements(next: FakeElement[]): void {
  elements = next;
}

// Every Hider.set() call the engine made, in order. A single toggle issues one
// call per matching query (name patterns plus the entity-class path), so tests
// assert on the union rather than on a call count.
const hiderSetCalls: { visible: boolean; localIds: number[] }[] = [];

function hiddenLocalIds(): Set<number> {
  const ids = new Set<number>();
  for (const call of hiderSetCalls) {
    if (!call.visible) for (const id of call.localIds) ids.add(id);
  }
  return ids;
}

function hiddenNames(): string[] {
  const ids = hiddenLocalIds();
  return elements
    .filter((el) => ids.has(el.localId))
    .map((el) => el.name)
    .sort();
}

function resetViewerMocks(): void {
  hiderSetCalls.length = 0;
  finderQueries.clear();
  elements = [];
}

const matchesAny = (value: string, regexes: RegExp[]): boolean =>
  regexes.some((regex) => regex.test(value));

// -- Fake Fragments model ----------------------------------------------------

const fakeModel = {
  modelId: MODEL_ID,
  // Mirrors FragmentsModel.getItemsOfCategories: entity-class regexes in,
  // { [className]: localId[] } out.
  getItemsOfCategories: async (regexes: RegExp[]): Promise<Record<string, number[]>> => {
    const byClass: Record<string, number[]> = {};
    for (const el of elements) {
      if (!matchesAny(el.ifcClass, regexes)) continue;
      (byClass[el.ifcClass] ??= []).push(el.localId);
    }
    return byClass;
  },
  // Mirrors FragmentsModel.getItemsData for the Name attribute, which the tree
  // enumeration (enumerateWallGroups / enumerateColumnGroups) reads to group by
  // name. Shape matches the engine's `dataList[i].Name = { value: string }`.
  getItemsData: async (
    localIds: number[],
  ): Promise<{ Name: { value: string } }[]> =>
    localIds.map((id) => {
      const el = elements.find((e) => e.localId === id);
      return { Name: { value: el?.name ?? `#${id}` } };
    }),
  // Mirrors FragmentsModel.getItemsIdsWithGeometry: the localIds Fragments
  // produced geometry for. The engine uses this to keep bodyless panel
  // containers out of the walls/roof trees' standalone entries.
  getItemsIdsWithGeometry: async (): Promise<number[]> =>
    elements.filter((e) => !e.bodyless).map((e) => e.localId),
};

// -- Fake ItemsFinder --------------------------------------------------------

type FinderQueryDef = {
  categories?: RegExp[];
  attributes?: { queries: { name: RegExp; value: RegExp }[] };
};

const finderQueries = new Map<string, FinderQueryDef[]>();

const fakeItemsFinder = {
  list: {
    has: (key: string): boolean => finderQueries.has(key),
    get: (key: string) => {
      const defs = finderQueries.get(key);
      if (!defs) return undefined;
      return {
        // Mirrors the real query.test(): a ModelIdMap of the matching items,
        // or {} when nothing matched (which the engine treats as "skip").
        test: async (): Promise<Record<string, Set<number>>> => {
          const ids = new Set<number>();
          for (const def of defs) {
            const nameQuery = def.attributes?.queries.find((q) => q.name.test('Name'));
            if (!nameQuery) continue;
            for (const el of elements) {
              if (def.categories && !matchesAny(el.ifcClass, def.categories)) continue;
              if (nameQuery.value.test(el.name)) ids.add(el.localId);
            }
          }
          return ids.size > 0 ? { [MODEL_ID]: ids } : {};
        },
      };
    },
  },
  create: (key: string, defs: FinderQueryDef[]): void => {
    finderQueries.set(key, defs);
  },
};

// -- Fake Hider --------------------------------------------------------------

const fakeHider = {
  set: vi.fn(async (visible?: boolean, modelIdMap?: Record<string, Set<number>>) => {
    hiderSetCalls.push({
      visible: visible ?? true,
      localIds: modelIdMap ? [...(modelIdMap[MODEL_ID] ?? [])] : [],
    });
  }),
};

// -- Mocked libraries --------------------------------------------------------

vi.mock('@thatopen/components', () => {
  class Worlds {
    // The engine assigns scene/camera/renderer onto whatever this returns.
    create() {
      return {} as Record<string, unknown>;
    }
  }
  class SimpleScene {
    config = {
      directionalLight: { intensity: 0 },
      ambientLight: { intensity: 0 },
    };
    three = { add: vi.fn() };
    setup = vi.fn();
  }
  class SimpleCamera {
    controls = { addEventListener: vi.fn() };
    three = {};
  }
  // The engine constructs an OrthoPerspectiveCamera (projection-toggle feature)
  // and sets tone-mapping on the renderer's `.three`; the mock has to carry
  // both or `new IFCViewerEngine()` throws before any test body runs.
  class OrthoPerspectiveCamera {
    controls = { addEventListener: vi.fn() };
    three = {};
    projection = { current: 'Perspective', toggle: vi.fn() };
  }
  class SimpleRenderer {
    three = { toneMapping: 0, toneMappingExposure: 1 };
  }
  class FragmentsManager {
    static getWorker = async () => '';
    list = new Map<string, typeof fakeModel>([[MODEL_ID, fakeModel]]);
    core = {
      update: vi.fn(),
      models: { materials: { list: { onItemSet: { add: vi.fn() } } } },
    };
    init = vi.fn();
  }
  class Hider {}
  class ItemsFinder {}
  class IfcLoader {}

  class Components {
    private registry = new Map<unknown, unknown>([
      [Worlds, new Worlds()],
      [FragmentsManager, new FragmentsManager()],
      [Hider, fakeHider],
      [ItemsFinder, fakeItemsFinder],
    ]);

    get(token: unknown): unknown {
      const instance = this.registry.get(token);
      // Loud on purpose: a new collaborator in the engine should surface as a
      // failing test naming it, not as an undefined that breaks elsewhere.
      if (!instance) {
        throw new Error(`viewerEngine.fixtures: unmocked components.get(${String(token)})`);
      }
      return instance;
    }

    init = vi.fn();
  }

  return {
    Components,
    Worlds,
    SimpleScene,
    SimpleCamera,
    OrthoPerspectiveCamera,
    SimpleRenderer,
    FragmentsManager,
    Hider,
    ItemsFinder,
    IfcLoader,
  };
});

// Types only, but still a runtime import in the engine's module graph.
vi.mock('@thatopen/fragments', () => ({}));

// Only reached by the pipe-run parsing path, which these tests never call.
// Mocked so the wasm-bearing module never has to load under jsdom.
vi.mock('web-ifc', () => ({
  IfcAPI: class {},
  IFCPIPESEGMENT: 0,
  IFCPIPEFITTING: 0,
  IFCRELCONNECTSPORTS: 0,
  IFCRELNESTS: 0,
}));

// Imported after the mocks are registered above (hoisting only reorders
// vi.mock calls within this module, not across module boundaries, so this
// dynamic import still needs to come after them textually).
const { default: IFCViewerEngine } = await import('./IFCViewerEngine');

function createEngine() {
  return new IFCViewerEngine({ container: document.createElement('div') });
}

// Verbatim from the generated IFC.
const WALL_FACES = [
  'Envelope Panel - End Wall at Y Min',
  'Envelope Panel - Side Wall at X Max',
  'Envelope Panel - End Wall at Y Max',
  'Envelope Panel - Side Wall at X Min',
];

const ROOF_FACE = 'Envelope Panel - Roof';

const PIECE_SUFFIXES: [suffix: string, ifcClass: string][] = [
  ['Outer Skin', 'IfcPlate'],
  ['Core', 'IfcBuildingElementPart'],
  ['Inner Liner', 'IfcPlate'],
];

// Vertical, closing two wall faces each - so these follow the Walls toggle.
const CORNER_FLASHING = [
  'Envelope Flashing - Corner at X Min Y Min',
  'Envelope Flashing - Corner at X Max Y Min',
  'Envelope Flashing - Corner at X Max Y Max',
  'Envelope Flashing - Corner at X Min Y Max',
];

// Capping the roof edge - so these follow the Roof toggle.
const EDGE_FLASHING = [
  'Envelope Flashing - Eave at X Min',
  'Envelope Flashing - Eave at X Max',
  'Envelope Flashing - Rake at Y Min',
  'Envelope Flashing - Rake at Y Max',
];

// Elements the envelope patterns must never catch.
//
// Two rows here carry the real risk. Shear tabs and column base plates share
// IfcPlate with the panel skins, so only the name separates them. And the
// IfcOpeningElement rows are named after the piece they void, which means
// their names DO match the wall-piece pattern - the entity-class filter is the
// only thing keeping voids out of a visibility toggle. A door or window hole in
// an end wall produces three of them, one per piece.
const NON_ENVELOPE: [ifcClass: string, name: string][] = [
  ['IfcSlab', 'IfcSlab #1'],
  ['IfcSlab', 'IfcSlab #2'],
  ['IfcPlate', 'Shear Tab at Start of B1.b1 - Plate'],
  ['IfcPlate', 'Shear Tab at End of B5.b3 - Plate'],
  ['IfcPlate', 'Base Plate for Column A1 - Base Plate'],
  ['IfcPlate', 'Base Plate for Column E4 - Base Plate'],
  ['IfcColumn', 'A1'],
  ['IfcBeam', 'B1.b1'],
  ['IfcOpeningElement', 'Envelope Panel - End Wall at Y Min - Outer Skin Opening'],
  ['IfcOpeningElement', 'Envelope Panel - End Wall at Y Min - Core Opening'],
  ['IfcOpeningElement', 'Envelope Panel - End Wall at Y Min - Inner Liner Opening'],
  // Doors and windows sit in the end walls but are named "Door in Envelope
  // Panel - ...", so the anchored patterns miss them and they keep their own
  // toggles.
  ['IfcDoor', 'Door in Envelope Panel - End Wall at Y Min'],
  ['IfcWindow', 'Window #1a in Envelope Panel - End Wall at Y Min'],
];

function buildIndustrialBuilding(): {
  elements: FakeElement[];
  wallNames: string[];
  roofNames: string[];
  otherNames: string[];
} {
  const elements: FakeElement[] = [];
  let nextId = 1;

  const add = (ifcClass: string, name: string, bodyless = false): string => {
    elements.push({ localId: nextId++, ifcClass, name, bodyless });
    return name;
  };

  const wallNames: string[] = [];
  const roofNames: string[] = [];

  for (const face of WALL_FACES) {
    // The IfcWall / IfcRoof panel face is a bodyless container — its geometry
    // lives in the three pieces below, so Fragments reports no geometry for it.
    wallNames.push(add('IfcWall', face, true));
    for (const [suffix, ifcClass] of PIECE_SUFFIXES) {
      wallNames.push(add(ifcClass, `${face} - ${suffix}`));
    }
  }

  roofNames.push(add('IfcRoof', ROOF_FACE, true));
  for (const [suffix, ifcClass] of PIECE_SUFFIXES) {
    roofNames.push(add(ifcClass, `${ROOF_FACE} - ${suffix}`));
  }

  for (const name of CORNER_FLASHING) wallNames.push(add('IfcDiscreteAccessory', name));
  for (const name of EDGE_FLASHING) roofNames.push(add('IfcDiscreteAccessory', name));

  const otherNames = NON_ENVELOPE.map(([ifcClass, name]) => add(ifcClass, name));

  return {
    elements,
    wallNames: [...wallNames].sort(),
    roofNames: [...roofNames].sort(),
    otherNames,
  };
}

beforeEach(() => {
  resetViewerMocks();
});

describe('IFCViewerEngine.setCategoryVisible - insulated metal panel envelope', () => {
  it('hides each wall panel, its three pieces and the corner flashing', async () => {
    const { elements, wallNames } = buildIndustrialBuilding();
    setModelElements(elements);

    await createEngine().setCategoryVisible('walls', false);

    // Exact equality, so an over-broad pattern that also swallowed the roof
    // pieces, a shear tab or a base plate fails here.
    expect(hiddenNames()).toEqual(wallNames);
  });

  it('hides the roof panel, its three pieces and the eave and rake flashing', async () => {
    const { elements, roofNames } = buildIndustrialBuilding();
    setModelElements(elements);

    await createEngine().setCategoryVisible('roofs', false);

    expect(hiddenNames()).toEqual(roofNames);
  });

  it('assigns every envelope element to exactly one of walls and roofs', async () => {
    const { elements, wallNames, roofNames, otherNames } = buildIndustrialBuilding();

    setModelElements(elements);
    await createEngine().setCategoryVisible('walls', false);
    const walls = hiddenLocalIds();

    resetViewerMocks();
    setModelElements(elements);
    await createEngine().setCategoryVisible('roofs', false);
    const roofs = hiddenLocalIds();

    // Disjoint: nothing is claimed by both toggles.
    expect([...walls].filter((id) => roofs.has(id))).toEqual([]);

    // Complete: together they account for the whole envelope, so neither
    // toggle can leave a floating skeleton of trim behind. This is what makes
    // corner flashing follow the walls and eave/rake flashing follow the roof
    // a decision the suite enforces rather than a detail of the regexes.
    expect(walls.size + roofs.size).toBe(wallNames.length + roofNames.length);

    // And neither toggle reaches outside the envelope.
    for (const el of elements.filter((e) => otherNames.includes(e.name))) {
      expect(walls.has(el.localId)).toBe(false);
      expect(roofs.has(el.localId)).toBe(false);
    }
  });

  it('turns a category back on with the same membership it hid', async () => {
    const { elements, roofNames } = buildIndustrialBuilding();
    setModelElements(elements);

    await createEngine().setCategoryVisible('roofs', true);

    expect(hiderSetCalls.every((call) => call.visible)).toBe(true);
    const shown = new Set(hiderSetCalls.flatMap((call) => call.localIds));
    expect(shown.size).toBe(roofNames.length);
  });
});

describe('IFCViewerEngine.setCategoryVisible - other roof authoring', () => {
  it('still hides a containment dome roof authored as a named IfcSlab', async () => {
    // The pre-existing behaviour the envelope patterns were added alongside:
    // roofs also matches an IfcSlab called "Roof Slab", and must not start
    // hiding the floor slab next to it.
    setModelElements([
      { localId: 1, ifcClass: 'IfcSlab', name: 'Roof Slab' },
      { localId: 2, ifcClass: 'IfcSlab', name: 'Floor Slab' },
    ]);

    await createEngine().setCategoryVisible('roofs', false);

    expect(hiddenNames()).toEqual(['Roof Slab']);
  });

  it('hides a containment dome authored as a named IfcBuildingElementProxy', async () => {
    // Nuclear reactor models write the dome as IfcBuildingElementProxy
    // "Containment Dome" (create_dome() in
    // alchemy-backend/app/ifc_authoring_tools.py), not an IfcRoof or "Roof
    // Slab". Only the name pattern puts it under the Roof toggle; without it
    // the dome matched no category and got no sidebar entry. The containment
    // shell wall shares the model and must stay off the Roof toggle (it is an
    // IfcWall, owned by Walls).
    setModelElements([
      { localId: 1, ifcClass: 'IfcBuildingElementProxy', name: 'Containment Dome' },
      { localId: 2, ifcClass: 'IfcWall', name: 'Containment Shell Wall' },
    ]);

    await createEngine().setCategoryVisible('roofs', false);

    expect(hiddenNames()).toEqual(['Containment Dome']);
  });
});

// Reduce the engine's TreeGroup[] to just labels + member labels, so the tests
// assert on the grouping (which pieces land under which parent, in what order)
// without caring about the opaque toggle keys the engine mints.
function shape(
  groups: { label: string; members: { label: string }[] }[],
): { label: string; members: string[] }[] {
  return groups.map((g) => ({
    label: g.label,
    members: g.members.map((m) => m.label),
  }));
}

describe('IFCViewerEngine.enumerateWallGroups / enumerateRoofGroups', () => {
  it('groups each wall panel over its three layers, plus a corner-flashing group', async () => {
    const { elements } = buildIndustrialBuilding();
    setModelElements(elements);

    const groups = shape(await createEngine().enumerateWallGroups());

    // Four panels (sorted by name) each own Outer Skin → Core → Inner Liner,
    // then a single Corner Flashing group collects the four corner accessories.
    expect(groups).toEqual([
      { label: 'Envelope Panel - End Wall at Y Max', members: ['Outer Skin', 'Core', 'Inner Liner'] },
      { label: 'Envelope Panel - End Wall at Y Min', members: ['Outer Skin', 'Core', 'Inner Liner'] },
      { label: 'Envelope Panel - Side Wall at X Max', members: ['Outer Skin', 'Core', 'Inner Liner'] },
      { label: 'Envelope Panel - Side Wall at X Min', members: ['Outer Skin', 'Core', 'Inner Liner'] },
      {
        label: 'Corner Flashing',
        members: [
          'Corner at X Max Y Max',
          'Corner at X Max Y Min',
          'Corner at X Min Y Max',
          'Corner at X Min Y Min',
        ],
      },
    ]);
  });

  it('groups the roof panel over its layers, plus an eave/rake flashing group', async () => {
    const { elements } = buildIndustrialBuilding();
    setModelElements(elements);

    const groups = shape(await createEngine().enumerateRoofGroups());

    expect(groups).toEqual([
      { label: 'Envelope Panel - Roof', members: ['Outer Skin', 'Core', 'Inner Liner'] },
      {
        label: 'Eave & Rake Flashing',
        members: ['Eave at X Max', 'Eave at X Min', 'Rake at Y Max', 'Rake at Y Min'],
      },
    ]);
  });

  it('returns no groups for a plain building, so the flat Walls toggle is kept', async () => {
    setModelElements([
      { localId: 1, ifcClass: 'IfcWall', name: 'Generic Wall 1' },
      { localId: 2, ifcClass: 'IfcWallStandardCase', name: 'Generic Wall 2' },
    ]);

    expect(await createEngine().enumerateWallGroups()).toEqual([]);
  });

  // The regression this whole change exists for: in a scene that has envelope
  // panels (so Walls/Roof render as trees and their flat class toggles are
  // suppressed), a plain body-bearing IfcWall / IfcRoof that belongs to no
  // panel — a reactor containment's cylindrical shell wall and hemispherical
  // dome roof — must still appear as its own toggle under its category, or it
  // has no sidebar control at all. The bodyless panel-face containers must NOT
  // (their geometry is in the grouped pieces).
  it('adds a standalone body-bearing containment wall/roof as its own entry when panels force tree mode', async () => {
    const { elements } = buildIndustrialBuilding();
    // Plain body-bearing IfcWall/IfcRoof belonging to no envelope panel.
    setModelElements([
      ...elements,
      { localId: 9001, ifcClass: 'IfcWall', name: 'IfcWall #5' },
      { localId: 9002, ifcClass: 'IfcRoof', name: 'IfcRoof #2' },
    ]);

    const engine = createEngine();

    // Walls: the four envelope panels + corner flashing (unchanged), then the
    // containment wall as its own single-element group. The four bodyless
    // envelope wall-face containers are absent — the exact list proves it, since
    // each would otherwise appear as its own trailing single-element group.
    expect(shape(await engine.enumerateWallGroups())).toEqual([
      { label: 'Envelope Panel - End Wall at Y Max', members: ['Outer Skin', 'Core', 'Inner Liner'] },
      { label: 'Envelope Panel - End Wall at Y Min', members: ['Outer Skin', 'Core', 'Inner Liner'] },
      { label: 'Envelope Panel - Side Wall at X Max', members: ['Outer Skin', 'Core', 'Inner Liner'] },
      { label: 'Envelope Panel - Side Wall at X Min', members: ['Outer Skin', 'Core', 'Inner Liner'] },
      {
        label: 'Corner Flashing',
        members: [
          'Corner at X Max Y Max',
          'Corner at X Max Y Min',
          'Corner at X Min Y Max',
          'Corner at X Min Y Min',
        ],
      },
      { label: 'IfcWall #5', members: ['IfcWall #5'] },
    ]);

    // Roof: the envelope roof panel + eave/rake flashing, then the dome. The
    // bodyless "Envelope Panel - Roof" IfcRoof container is not added again (the
    // group of that name is the 3-piece panel group, not a 1-member entry).
    expect(shape(await engine.enumerateRoofGroups())).toEqual([
      { label: 'Envelope Panel - Roof', members: ['Outer Skin', 'Core', 'Inner Liner'] },
      {
        label: 'Eave & Rake Flashing',
        members: ['Eave at X Max', 'Eave at X Min', 'Rake at Y Max', 'Rake at Y Min'],
      },
      { label: 'IfcRoof #2', members: ['IfcRoof #2'] },
    ]);
  });
});

describe('IFCViewerEngine.enumerateColumnGroups', () => {
  it('nests each column base-plate assembly (plate, bolts, nuts) under its column', async () => {
    setModelElements([
      { localId: 1, ifcClass: 'IfcColumn', name: 'Column A1' },
      { localId: 2, ifcClass: 'IfcColumn', name: 'Column E4' },
      { localId: 3, ifcClass: 'IfcPlate', name: 'Base Plate for Column A1 - Base Plate' },
      { localId: 4, ifcClass: 'IfcMechanicalFastener', name: 'Base Plate for Column A1 - Anchor Bolt 0' },
      { localId: 5, ifcClass: 'IfcMechanicalFastener', name: 'Base Plate for Column A1 - Hex Nut 0' },
      { localId: 6, ifcClass: 'IfcPlate', name: 'Base Plate for Column E4 - Base Plate' },
      // Shares the IfcPlate class but belongs to no column — must be ignored.
      { localId: 7, ifcClass: 'IfcPlate', name: 'Envelope Panel - Side Wall at X Max - Outer Skin' },
    ]);

    const groups = shape(await createEngine().enumerateColumnGroups());

    expect(groups).toEqual([
      {
        label: 'Column A1',
        members: ['Column', 'Anchor Bolt 0', 'Base Plate', 'Hex Nut 0'],
      },
      { label: 'Column E4', members: ['Column', 'Base Plate'] },
    ]);
  });

  it('returns no groups when columns have no base plates, so the flat toggle is kept', async () => {
    setModelElements([
      { localId: 1, ifcClass: 'IfcColumn', name: 'Column A1' },
      { localId: 2, ifcClass: 'IfcColumn', name: 'Column A2' },
    ]);

    expect(await createEngine().enumerateColumnGroups()).toEqual([]);
  });
});

describe('IFCViewerEngine.enumerateCategories', () => {
  it('reports walls and roofs on a clear-span building so their toggles render', async () => {
    const { elements } = buildIndustrialBuilding();
    setModelElements(elements);

    const present = await createEngine().enumerateCategories([
      'walls',
      'roofs',
      'floors',
      'doors',
      'pipes',
    ]);

    // walls and roofs are satisfied twice over here - by the name patterns and
    // by the IfcWall/IfcRoof containers - which is the state to hold onto:
    // while the envelope was IfcElementAssembly neither class was in the file,
    // so these two toggles did not render at all.
    // floors comes from the two base slabs, doors from the end-wall door;
    // pipes is absent from this model.
    expect(present).toEqual(['walls', 'roofs', 'floors', 'doors']);
  });
});
