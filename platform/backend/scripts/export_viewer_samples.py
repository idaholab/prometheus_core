#!/usr/bin/env python3
# This file is part of Prometheus
# https://inl.gov/super-intelligence/prometheus/
#
# Copyright 2026 Battelle Energy Alliance, LLC
# All rights reserved, see NOTICE.txt for full restrictions
# https://github.com/idaholab/prometheus_core/blob/main/NOTICE.txt
#
# Licensed under the MIT License, please see LICENSE for details
# https://github.com/idaholab/prometheus_core/blob/main/LICENSE
#
# SPDX-License-Identifier: MIT

"""Write the shared viewer samples to ``../frontend/e2e/samples/``.

The viewer playground and the end-to-end viewer tests read these files. The STL is
built from vtk primitives and converted by the backend's own mesh code, so the mesh
sample is what a chat turn would get. The IFC model comes from a small stdlib IFC4
writer. The samples are committed; ``tests/test_viewer_samples.py`` regenerates them
and fails if that changes a committed file. Regenerate them with::

    uv run python scripts/export_viewer_samples.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

import vtk

BACKEND = Path(__file__).resolve().parent.parent
SAMPLES_DIR = BACKEND.parent / "frontend" / "e2e" / "samples"

# The 64 characters of the IFC GlobalId encoding, in order
_IFC_BASE64 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"
_GUID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://inl.gov/super-intelligence/prometheus/viewer-samples")


def write_stl(path: Path) -> None:
    """Write a small bracket (base plate, upright plate, boss) as a binary STL."""
    base = vtk.vtkCubeSource()
    base.SetCenter(0.0, 0.2, 0.0)
    base.SetXLength(4.0)
    base.SetYLength(0.4)
    base.SetZLength(2.0)
    upright = vtk.vtkCubeSource()
    upright.SetCenter(-1.8, 1.45, 0.0)
    upright.SetXLength(0.4)
    upright.SetYLength(2.5)
    upright.SetZLength(2.0)
    boss = vtk.vtkCylinderSource()
    boss.SetCenter(1.0, 0.7, 0.0)
    boss.SetRadius(0.4)
    boss.SetHeight(0.6)
    boss.SetResolution(32)

    append = vtk.vtkAppendPolyData()
    for source in (base, upright, boss):
        append.AddInputConnection(source.GetOutputPort())
    triangles = vtk.vtkTriangleFilter()
    triangles.SetInputConnection(append.GetOutputPort())

    writer = vtk.vtkSTLWriter()
    writer.SetFileName(str(path))
    writer.SetFileTypeToBinary()
    writer.SetInputConnection(triangles.GetOutputPort())
    writer.Write()


def _ifc_guid(key: str) -> str:
    """A stable 22-character IFC GlobalId for ``key``."""
    number = uuid.uuid5(_GUID_NAMESPACE, key).int
    return "".join(_IFC_BASE64[(number >> (6 * i)) & 0x3F] for i in reversed(range(22)))


def _real(value: float) -> str:
    return repr(float(value))


def _point(*coords: float) -> str:
    return "(" + ",".join(_real(c) for c in coords) + ")"


# name, IFC entity, attributes after Tag, profile, location (x, y, z), axis, depth.
# A rectangle profile is (x size, y size); a circle profile is (radius,).
# The axis is the extrusion direction; None extrudes up.
_ELEMENTS: list[
    tuple[str, str, str, tuple[float, ...], tuple[float, float, float], tuple[float, ...] | None, float]
] = [
    ("Floor Slab", "IFCSLAB", ".FLOOR.", (10.0, 6.0), (5.0, 3.0, -0.2), None, 0.2),
    ("South Wall", "IFCWALL", ".STANDARD.", (10.0, 0.2), (5.0, 0.1, 0.0), None, 3.0),
    ("North Wall", "IFCWALL", ".STANDARD.", (10.0, 0.2), (5.0, 5.9, 0.0), None, 3.0),
    ("West Wall", "IFCWALL", ".STANDARD.", (0.2, 5.6), (0.1, 3.0, 0.0), None, 3.0),
    ("East Wall", "IFCWALL", ".STANDARD.", (0.2, 5.6), (9.9, 3.0, 0.0), None, 3.0),
    ("Column C1", "IFCCOLUMN", ".COLUMN.", (0.3, 0.3), (3.5, 3.0, 0.0), None, 2.7),
    ("Column C2", "IFCCOLUMN", ".COLUMN.", (0.3, 0.3), (6.5, 3.0, 0.0), None, 2.7),
    ("Beam B1", "IFCBEAM", ".BEAM.", (3.3, 0.3), (5.0, 3.0, 2.7), None, 0.3),
    ("Door D1", "IFCDOOR", "2.1,0.9,.DOOR.,.SINGLE_SWING_LEFT.,$", (0.9, 0.25), (2.0, 0.1, 0.0), None, 2.1),
    ("Window W1", "IFCWINDOW", "1.2,1.2,.WINDOW.,.SINGLE_PANEL.,$", (1.2, 0.25), (7.0, 5.9, 1.0), None, 1.2),
    ("Roof Slab", "IFCSLAB", ".ROOF.", (10.0, 6.0), (5.0, 3.0, 3.0), None, 0.2),
    ("Pump P-101", "IFCPUMP", ".CIRCULATOR.", (0.6, 0.4), (7.0, 1.5, 0.0), None, 0.5),
    ("Pipe P-101-1", "IFCPIPESEGMENT", ".RIGIDSEGMENT.", (0.05,), (7.3, 1.5, 0.25), (1.0, 0.0, 0.0), 1.7),
    ("Pipe P-101-2", "IFCPIPESEGMENT", ".RIGIDSEGMENT.", (0.05,), (9.0, 1.5, 0.25), None, 2.25),
]


def write_ifc(path: Path) -> None:
    """Write a small IFC4 building with a pump and two pipes, with the stdlib only.

    The header has a fixed timestamp and an empty author and organization, and the
    file holds no person, organization or owner history, so it names only the project.
    """
    lines: list[str] = []

    def add(entity: str) -> str:
        lines.append(f"#{len(lines) + 1}={entity};")
        return f"#{len(lines)}"

    origin = add(f"IFCCARTESIANPOINT({_point(0.0, 0.0, 0.0)})")
    z_axis = add(f"IFCDIRECTION({_point(0.0, 0.0, 1.0)})")
    x_axis = add(f"IFCDIRECTION({_point(1.0, 0.0, 0.0)})")
    world = add(f"IFCAXIS2PLACEMENT3D({origin},{z_axis},{x_axis})")
    # web-ifc needs an explicit profile position, though IFC4 makes it optional
    profile_origin = add(f"IFCCARTESIANPOINT({_point(0.0, 0.0)})")
    profile_placement = add(f"IFCAXIS2PLACEMENT2D({profile_origin},$)")
    model = add(f"IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,{world},$)")
    body = add(f"IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Body','Model',*,*,*,*,{model},$,.MODEL_VIEW.,$)")
    units = [
        add("IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.)"),
        add("IFCSIUNIT(*,.AREAUNIT.,$,.SQUARE_METRE.)"),
        add("IFCSIUNIT(*,.VOLUMEUNIT.,$,.CUBIC_METRE.)"),
        add("IFCSIUNIT(*,.PLANEANGLEUNIT.,$,.RADIAN.)"),
    ]
    unit_assignment = add(f"IFCUNITASSIGNMENT(({','.join(units)}))")
    project = add(f"IFCPROJECT('{_ifc_guid('project')}',$,'Viewer sample project',$,$,$,$,({model}),{unit_assignment})")

    site_placement = add(f"IFCLOCALPLACEMENT($,{world})")
    site = add(f"IFCSITE('{_ifc_guid('site')}',$,'Site',$,$,{site_placement},$,$,.ELEMENT.,$,$,$,$,$)")
    building_placement = add(f"IFCLOCALPLACEMENT({site_placement},{world})")
    building = add(f"IFCBUILDING('{_ifc_guid('building')}',$,'Building',$,$,{building_placement},$,$,.ELEMENT.,$,$,$)")
    storey_placement = add(f"IFCLOCALPLACEMENT({building_placement},{world})")
    storey = add(f"IFCBUILDINGSTOREY('{_ifc_guid('storey')}',$,'Ground Floor',$,$,{storey_placement},$,$,.ELEMENT.,0.)")
    add(f"IFCRELAGGREGATES('{_ifc_guid('project-site')}',$,$,$,{project},({site}))")
    add(f"IFCRELAGGREGATES('{_ifc_guid('site-building')}',$,$,$,{site},({building}))")
    add(f"IFCRELAGGREGATES('{_ifc_guid('building-storey')}',$,$,$,{building},({storey}))")

    elements = []
    for name, entity, tail, profile, location, axis, depth in _ELEMENTS:
        if len(profile) == 1:
            swept = add(f"IFCCIRCLEPROFILEDEF(.AREA.,$,{profile_placement},{_real(profile[0])})")
        else:
            swept = add(f"IFCRECTANGLEPROFILEDEF(.AREA.,$,{profile_placement},{_real(profile[0])},{_real(profile[1])})")
        solid = add(f"IFCEXTRUDEDAREASOLID({swept},{world},{z_axis},{_real(depth)})")
        shape = add(f"IFCSHAPEREPRESENTATION({body},'Body','SweptSolid',({solid}))")
        product_shape = add(f"IFCPRODUCTDEFINITIONSHAPE($,$,({shape}))")
        point = add(f"IFCCARTESIANPOINT({_point(*location)})")
        if axis is None:
            relative = add(f"IFCAXIS2PLACEMENT3D({point},$,$)")
        else:
            direction = add(f"IFCDIRECTION({_point(*axis)})")
            relative = add(f"IFCAXIS2PLACEMENT3D({point},{direction},{z_axis})")
        placement = add(f"IFCLOCALPLACEMENT({storey_placement},{relative})")
        elements.append(add(f"{entity}('{_ifc_guid(name)}',$,'{name}',$,$,{placement},{product_shape},$,{tail})"))
    add(f"IFCRELCONTAINEDINSPATIALSTRUCTURE('{_ifc_guid('storey-contents')}',$,$,$,({','.join(elements)}),{storey})")

    header = [
        "ISO-10303-21;",
        "HEADER;",
        "FILE_DESCRIPTION(('ViewDefinition [ReferenceView]'),'2;1');",
        "FILE_NAME('model.ifc','2026-01-01T00:00:00',(''),(''),'export_viewer_samples.py','Prometheus','');",
        "FILE_SCHEMA(('IFC4'));",
        "ENDSEC;",
        "DATA;",
    ]
    footer = ["ENDSEC;", "END-ISO-10303-21;"]
    path.write_text("\n".join(header + lines + footer) + "\n", encoding="utf-8")


def write_samples(out_dir: Path) -> list[Path]:
    """Write the generated samples to ``out_dir`` and return their paths.

    ``diagram.mmd``, ``results.json`` and ``README.md`` are hand-written and are not
    written here.
    """
    from app.services.mesh.service import _build_json_body, _convert_sync

    mesh_dir = out_dir / "mesh"
    mesh_dir.mkdir(parents=True, exist_ok=True)

    stl_path = out_dir / "part.stl"
    write_stl(stl_path)
    written = [stl_path]

    with tempfile.TemporaryDirectory() as cache_dir:
        cache_root = Path(cache_dir)
        dataset_id, manifest, metadata = _convert_sync(stl_path, cache_root, "part.stl", "", "model/stl")
        for name in ("surface_t0000.vtp", "manifest.json", "meta.json"):
            target = mesh_dir / name
            shutil.copyfile(cache_root / dataset_id / name, target)
            written.append(target)

    json_body = _build_json_body(dataset_id, manifest, metadata, "Sample part (STL)")
    json_body_path = mesh_dir / "json_body.json"
    # Indented, with keys in the order the backend builds them
    json_body_path.write_text(json.dumps(json_body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    written.append(json_body_path)

    ifc_path = out_dir / "model.ifc"
    write_ifc(ifc_path)
    written.append(ifc_path)
    return written


def main() -> None:
    # The app package is the backend directory
    sys.path.insert(0, str(BACKEND))
    for path in write_samples(SAMPLES_DIR):
        print(f"wrote {path.relative_to(BACKEND.parent)}")


if __name__ == "__main__":
    main()
