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

"""Tests for the shared viewer samples in ``platform/frontend/e2e/samples/``.

``scripts/export_viewer_samples.py`` writes the generated samples from the backend's own
mesh conversion code and a stdlib IFC writer; the files are committed for the viewer
playground and the end-to-end viewer tests. These tests keep the committed files honest.

- The committed samples equal what the script writes now, so a change to the mesh conversion,
  the MeshViewer props or the IFC writer fails here until someone regenerates the samples.
- The committed IFC model names no person or organization and has no owner history, and it holds
  an element of each category that the IFC viewer lists.

``SAMPLES_DIR`` is the committed samples directory and ``REGENERATE`` the command that
rewrites it; ``load_export_script()`` imports the script, which is not in a package.
"""

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest
import vtk

BACKEND_DIR = Path(__file__).resolve().parent.parent
SAMPLES_DIR = BACKEND_DIR.parent / "frontend" / "e2e" / "samples"
EXPORT_SCRIPT = BACKEND_DIR / "scripts" / "export_viewer_samples.py"
REGENERATE = "cd platform/backend && uv run python scripts/export_viewer_samples.py"

# Generated files that the script writes byte for byte the same on every run
BYTE_EQUAL_SAMPLES = ["part.stl", "model.ifc", "mesh/manifest.json", "mesh/meta.json", "mesh/json_body.json"]
VTP_SAMPLE = "mesh/surface_t0000.vtp"


def load_export_script() -> ModuleType:
    """Import ``scripts/export_viewer_samples.py`` as a module."""
    spec = importlib.util.spec_from_file_location("export_viewer_samples", EXPORT_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def generated_samples(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The samples as the script writes them now, in a temp directory."""
    out_dir = tmp_path_factory.mktemp("viewer_samples")
    load_export_script().write_samples(out_dir)
    return out_dir


def _drift_message(name: str) -> str:
    return f"{name} in {SAMPLES_DIR} no longer matches the generator; regenerate the samples with: {REGENERATE}"


Vectors = tuple[tuple[float, ...], ...]


def _read_vtp(path: Path) -> tuple[int, int, Vectors, Vectors | None]:
    """The point count, cell count, point coordinates and cell ``Normals`` tuples of a VTP file.

    The normals are ``None`` when the file has no ``Normals`` cell array.
    """
    reader = vtk.vtkXMLPolyDataReader()
    reader.SetFileName(str(path))
    reader.Update()
    polydata = reader.GetOutput()
    points = polydata.GetPoints()
    coords = tuple(points.GetPoint(i) for i in range(points.GetNumberOfPoints()))
    normals_array = polydata.GetCellData().GetArray("Normals")
    normals = (
        None
        if normals_array is None
        else tuple(normals_array.GetTuple(i) for i in range(normals_array.GetNumberOfTuples()))
    )
    return polydata.GetNumberOfPoints(), polydata.GetNumberOfCells(), coords, normals


@pytest.mark.parametrize("name", BYTE_EQUAL_SAMPLES)
def test_viewer_sample_matches_generator(generated_samples: Path, name: str) -> None:
    """A committed sample is byte-equal to the script's output."""
    committed = SAMPLES_DIR / name
    assert committed.is_file(), f"{name} is missing from {SAMPLES_DIR}; write it with: {REGENERATE}"
    assert (generated_samples / name).read_bytes() == committed.read_bytes(), _drift_message(name)


def test_viewer_sample_vtp_matches_generator(generated_samples: Path) -> None:
    """The committed VTP has the generated points, cells and cell normals."""
    committed = SAMPLES_DIR / VTP_SAMPLE
    assert committed.is_file(), f"{VTP_SAMPLE} is missing from {SAMPLES_DIR}; write it with: {REGENERATE}"
    generated_points, generated_cells, generated_coords, generated_normals = _read_vtp(generated_samples / VTP_SAMPLE)
    committed_points, committed_cells, committed_coords, committed_normals = _read_vtp(committed)
    assert generated_points > 0, f"the generator wrote an empty {VTP_SAMPLE}"
    assert committed_points == generated_points, _drift_message(VTP_SAMPLE) + " (point count)"
    assert committed_cells == generated_cells, _drift_message(VTP_SAMPLE) + " (cell count)"
    assert committed_coords == generated_coords, _drift_message(VTP_SAMPLE) + " (point coordinates)"
    assert generated_normals is not None, f"the generator wrote {VTP_SAMPLE} without a Normals cell array"
    assert committed_normals is not None, _drift_message(VTP_SAMPLE) + " (no Normals cell array)"
    assert committed_normals == generated_normals, _drift_message(VTP_SAMPLE) + " (cell normals)"


IFC_SAMPLE = SAMPLES_DIR / "model.ifc"
# Every entity whose name contains one of these parts names a person, an organization or an owner
IFC_FORBIDDEN_NAME_PARTS = ["PERSON", "ORGANIZATION", "OWNERHISTORY"]
IFC_VIEWER_CATEGORIES = [
    "IFCWALL",
    "IFCSLAB",
    "IFCCOLUMN",
    "IFCBEAM",
    "IFCDOOR",
    "IFCWINDOW",
    "IFCPUMP",
    "IFCPIPESEGMENT",
]
# An empty STEP list of strings, as the FILE_NAME author and organization
EMPTY_STEP_LISTS = {"()", "('')"}

_STEP_ENTITY = re.compile(r"#(\d+)\s*=\s*([A-Za-z0-9_]+)\s*\((.*)\)\s*;")
_STEP_FILE_NAME = re.compile(r"FILE_NAME\s*\((.*)\)\s*;")


def _split_step_args(args: str) -> list[str]:
    """Split a STEP argument list at its top-level commas, keeping strings and nested lists whole."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    in_string = False
    for char in args:
        if char == "'":
            in_string = not in_string
        elif not in_string and char in "()":
            depth += 1 if char == "(" else -1
        elif not in_string and depth == 0 and char == ",":
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return parts


@pytest.fixture(scope="module")
def ifc_lines() -> tuple[list[str], list[str]]:
    """The HEADER and DATA section lines of the committed IFC sample."""
    assert IFC_SAMPLE.is_file(), f"model.ifc is missing from {SAMPLES_DIR}; write it with: {REGENERATE}"
    lines = [line.strip() for line in IFC_SAMPLE.read_text(encoding="utf-8").splitlines()]
    header = lines[lines.index("HEADER;") + 1 : lines.index("ENDSEC;")]
    data_start = lines.index("DATA;") + 1
    data = lines[data_start : lines.index("ENDSEC;", data_start)]
    return header, data


@pytest.fixture(scope="module")
def ifc_entities(ifc_lines: tuple[list[str], list[str]]) -> list[tuple[str, list[str]]]:
    """The (entity name, arguments) of each ``#N=IFCxxx(...);`` line of the DATA section."""
    entities = []
    for line in ifc_lines[1]:
        match = _STEP_ENTITY.fullmatch(line)
        assert match is not None, f"model.ifc has a DATA line that is not one STEP entity: {line!r}"
        entities.append((match.group(2).upper(), _split_step_args(match.group(3))))
    return entities


@pytest.mark.parametrize("name_part", IFC_FORBIDDEN_NAME_PARTS)
def test_ifc_sample_has_no_person_or_organization_entity(
    ifc_entities: list[tuple[str, list[str]]], name_part: str
) -> None:
    """model.ifc has no entity that names a person, an organization or an owner history."""
    found = sorted({name for name, _ in ifc_entities if name_part in name})
    assert not found, (
        f"model.ifc holds {', '.join(found)}, whose name contains {name_part}; the sample must name only the project"
    )


def test_ifc_sample_file_name_has_empty_author_and_organization(ifc_lines: tuple[list[str], list[str]]) -> None:
    """The FILE_NAME header names no author and no organization."""
    file_names = [match for line in ifc_lines[0] if (match := _STEP_FILE_NAME.fullmatch(line))]
    assert len(file_names) == 1, f"model.ifc has {len(file_names)} FILE_NAME headers, expected 1"
    args = _split_step_args(file_names[0].group(1))
    assert len(args) == 7, f"FILE_NAME has {len(args)} arguments, expected 7: {args}"
    assert args[2] in EMPTY_STEP_LISTS, f"FILE_NAME author is {args[2]}, expected empty"
    assert args[3] in EMPTY_STEP_LISTS, f"FILE_NAME organization is {args[3]}, expected empty"


def test_ifc_sample_has_one_project_named_viewer_sample_project(ifc_entities: list[tuple[str, list[str]]]) -> None:
    """The one IFCPROJECT is named ``Viewer sample project``."""
    projects = [args for name, args in ifc_entities if name == "IFCPROJECT"]
    assert len(projects) == 1, f"model.ifc has {len(projects)} IFCPROJECT entities, expected 1"
    # IfcProject attributes: GlobalId, OwnerHistory, Name, ...
    assert projects[0][2] == "'Viewer sample project'", f"IFCPROJECT name is {projects[0][2]}"


@pytest.mark.parametrize("category", IFC_VIEWER_CATEGORIES)
def test_ifc_sample_holds_viewer_category(ifc_entities: list[tuple[str, list[str]]], category: str) -> None:
    """model.ifc holds an element of each IFC viewer category."""
    names = {name for name, _ in ifc_entities}
    assert category in names, f"model.ifc holds no {category} entity; the IFC viewer lists that category"
