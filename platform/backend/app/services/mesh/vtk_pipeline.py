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

"""VTK pipeline for reading and converting Exodus II files to web-friendly VTP.

Ported from the old ``frontend/components/exodus/vtk_pipeline.py``. This module
``import vtk`` at load time, so it must only ever be imported *lazily* from a
conversion code path (see :mod:`app.services.mesh.service`), never at app/router
import time — the offline backend test environment does not install VTK.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import vtk

from .exceptions import ConversionError, InvalidExodusFileError
from .models import ConvertRequest, ExodusMetadata


def create_exodus_reader(file_path: Path) -> "vtk.vtkExodusIIReader":
    """Create and configure an Exodus II reader."""
    reader = vtk.vtkExodusIIReader()
    reader.SetFileName(str(file_path))
    reader.UpdateInformation()
    return reader


def extract_metadata(reader: "vtk.vtkExodusIIReader") -> ExodusMetadata:
    """Extract timesteps, variables, blocks, bounds and counts from a reader."""
    info = reader.GetExecutive().GetOutputInformation(0)
    num_timesteps = 0
    time_values: list[float] = []

    if info.Has(vtk.vtkStreamingDemandDrivenPipeline.TIME_STEPS()):
        time_values = list(info.Get(vtk.vtkStreamingDemandDrivenPipeline.TIME_STEPS()))
        num_timesteps = len(time_values)

    nodal_variables = [reader.GetPointResultArrayName(i) for i in range(reader.GetNumberOfPointResultArrays())]
    element_variables = [reader.GetElementResultArrayName(i) for i in range(reader.GetNumberOfElementResultArrays())]
    global_variables = [reader.GetGlobalResultArrayName(i) for i in range(reader.GetNumberOfGlobalResultArrays())]

    element_blocks = []
    for i in range(reader.GetNumberOfElementBlockArrays()):
        element_blocks.append({"index": i, "name": reader.GetElementBlockArrayName(i)})

    # Enable all arrays/blocks to get accurate bounds + counts.
    for name in nodal_variables:
        reader.SetPointResultArrayStatus(name, 1)
    for name in element_variables:
        reader.SetElementResultArrayStatus(name, 1)
    for block in element_blocks:
        reader.SetElementBlockArrayStatus(block["name"], 1)

    reader.Update()
    output = reader.GetOutput()

    bounds = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    num_nodes = 0
    num_elements = 0

    if output:
        output.GetBounds(bounds)
        iterator = output.NewIterator()
        iterator.InitTraversal()
        while not iterator.IsDoneWithTraversal():
            block = iterator.GetCurrentDataObject()
            if block and hasattr(block, "GetNumberOfPoints"):
                num_nodes += block.GetNumberOfPoints()
            if block and hasattr(block, "GetNumberOfCells"):
                num_elements += block.GetNumberOfCells()
            iterator.GoToNextItem()

    return ExodusMetadata(
        num_timesteps=num_timesteps,
        time_values=time_values,
        nodal_variables=nodal_variables,
        element_variables=element_variables,
        global_variables=global_variables,
        element_blocks=element_blocks,
        # GetBounds() fills a 6-element list; mypy can't infer the fixed length.
        bounds=cast("tuple[float, float, float, float, float, float]", tuple(bounds)),
        num_nodes=num_nodes,
        num_elements=num_elements,
    )


def extract_surface(input_data: "vtk.vtkDataObject") -> "vtk.vtkPolyData":
    """Extract the surface from a dataset (handles multi-block)."""
    if isinstance(input_data, vtk.vtkMultiBlockDataSet):
        geometry_filter = vtk.vtkCompositeDataGeometryFilter()
        geometry_filter.SetInputData(input_data)
        geometry_filter.Update()
        return geometry_filter.GetOutput()
    surface_filter = vtk.vtkDataSetSurfaceFilter()
    surface_filter.SetInputData(input_data)
    surface_filter.Update()
    return surface_filter.GetOutput()


def apply_decimation(polydata: "vtk.vtkPolyData", target_reduction: float) -> "vtk.vtkPolyData":
    """Reduce triangle count by ``target_reduction`` (0 < r < 1)."""
    if target_reduction <= 0 or target_reduction >= 1:
        return polydata
    decimate = vtk.vtkQuadricDecimation()
    decimate.SetInputData(polydata)
    decimate.SetTargetReduction(target_reduction)
    decimate.Update()
    return decimate.GetOutput()


def compute_normals(polydata: "vtk.vtkPolyData", style: str = "flat") -> "vtk.vtkPolyData":
    """Compute display normals, defaulting to flat (per-cell) element shading."""
    normals = vtk.vtkPolyDataNormals()
    normals.SetInputData(polydata)
    if style == "smooth":
        normals.ComputePointNormalsOn()
        normals.ComputeCellNormalsOff()
        normals.SplittingOff()
    else:
        normals.ComputePointNormalsOff()
        normals.ComputeCellNormalsOn()
        normals.SplittingOn()
    normals.Update()
    return normals.GetOutput()


def clean_polydata(polydata: "vtk.vtkPolyData") -> "vtk.vtkPolyData":
    """Merge duplicate points."""
    clean = vtk.vtkCleanPolyData()
    clean.SetInputData(polydata)
    clean.Update()
    return clean.GetOutput()


def write_vtp(polydata: "vtk.vtkPolyData", output_path: Path, compress: bool = True) -> None:
    """Write polydata to a ``.vtp`` file (ZLib-compressed by default)."""
    writer = vtk.vtkXMLPolyDataWriter()
    writer.SetFileName(str(output_path))
    writer.SetInputData(polydata)
    if compress:
        writer.SetCompressorTypeToZLib()
    else:
        writer.SetCompressorTypeToNone()
    writer.Write()


def get_array_range(polydata: "vtk.vtkPolyData", array_name: str) -> tuple[float, float]:
    """Return the scalar range of a named point/cell array (``(0, 0)`` if absent)."""
    array = polydata.GetPointData().GetArray(array_name)
    if array is None:
        array = polydata.GetCellData().GetArray(array_name)
    if array is None:
        return (0.0, 0.0)
    low, high = array.GetRange()
    return (float(low), float(high))


def convert_timestep(
    reader: "vtk.vtkExodusIIReader",
    timestep_index: int,
    request: ConvertRequest,
) -> "vtk.vtkPolyData":
    """Convert a single timestep to display-ready polydata."""
    reader.SetTimeStep(timestep_index)
    reader.Update()

    output = reader.GetOutput()
    if output is None:
        raise ConversionError(f"Failed to read timestep {timestep_index}")

    polydata = extract_surface(output)

    if request.decimate is not None and request.decimate > 0:
        polydata = apply_decimation(polydata, request.decimate)

    polydata = clean_polydata(polydata)

    if request.include_normals:
        polydata = compute_normals(polydata, request.normal_style)

    return polydata


def require_geometry(metadata: ExodusMetadata, input_path: Path) -> None:
    """Raise :class:`InvalidExodusFileError` when the reader read no geometry.

    VTK's Exodus reader logs an error but does not raise on a file it can't open: it
    yields an empty mesh. Converting that would write a manifest, which the
    content-hash cache then serves as this file's mesh forever, so callers check this
    before anything is written.

    ``num_nodes`` is summed over the element blocks :func:`extract_metadata` enabled,
    which is all of them. If that ever honours a block selection, a readable file with
    no blocks selected would be rejected here; check before that change lands.
    """
    if not metadata.num_nodes:
        raise InvalidExodusFileError(f"No geometry read from {input_path.name}; not a readable Exodus II file")


def run_conversion(request: ConvertRequest) -> dict:
    """Run the full Exodus→VTP conversion, writing VTP files + ``manifest.json`` +
    ``meta.json`` into ``request.output_dir``. Returns the manifest dict."""
    input_path = request.input_path
    output_dir = request.output_dir

    if not input_path.exists():
        raise InvalidExodusFileError(f"File not found: {input_path}")

    reader = create_exodus_reader(input_path)
    metadata = extract_metadata(reader)
    require_geometry(metadata, input_path)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Disable all result arrays, then enable the requested ones (or all if none named).
    for name in metadata.nodal_variables:
        reader.SetPointResultArrayStatus(name, 0)
    for name in metadata.element_variables:
        reader.SetElementResultArrayStatus(name, 0)

    vars_to_enable = request.variables or (metadata.nodal_variables + metadata.element_variables)
    for name in vars_to_enable:
        if name in metadata.nodal_variables:
            reader.SetPointResultArrayStatus(name, 1)
        if name in metadata.element_variables:
            reader.SetElementResultArrayStatus(name, 1)

    # Element blocks: named subset, or all.
    if request.blocks:
        for block in metadata.element_blocks:
            reader.SetElementBlockArrayStatus(block["name"], 1 if block["name"] in request.blocks else 0)
    else:
        for block in metadata.element_blocks:
            reader.SetElementBlockArrayStatus(block["name"], 1)

    # Which timesteps to process.
    if request.timestep_mode == "single":
        timestep_indices = [request.timestep_index or 0]
    elif request.timestep_mode == "stride":
        stride = request.timestep_stride or 1
        timestep_indices = list(range(0, metadata.num_timesteps, stride))
    else:  # "all"
        timestep_indices = list(range(metadata.num_timesteps))

    if not timestep_indices:
        timestep_indices = [0]

    files = []
    array_ranges: dict[str, list[float]] = {}

    for i, ts_idx in enumerate(timestep_indices):
        polydata = convert_timestep(reader, ts_idx, request)

        filename = f"surface_t{i:04d}.vtp"
        write_vtp(polydata, output_dir / filename, request.compress)

        time_value = metadata.time_values[ts_idx] if ts_idx < len(metadata.time_values) else 0.0
        files.append({"index": i, "timestep_index": ts_idx, "time_value": time_value, "filename": filename})

        for name in vars_to_enable:
            range_val = get_array_range(polydata, name)
            if name not in array_ranges:
                array_ranges[name] = list(range_val)
            else:
                array_ranges[name][0] = min(array_ranges[name][0], range_val[0])
                array_ranges[name][1] = max(array_ranges[name][1], range_val[1])

    point_vars = [v for v in vars_to_enable if v in metadata.nodal_variables]
    cell_vars = [v for v in vars_to_enable if v in metadata.element_variables]

    manifest = {
        "version": "1.0",
        "num_timesteps": len(files),
        "files": files,
        "variables": {"point": point_vars, "cell": cell_vars},
        "array_ranges": array_ranges,
        "bounds": list(metadata.bounds),
    }

    with open(output_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    with open(output_dir / "meta.json", "w") as f:
        json.dump(metadata.to_dict(), f, indent=2)

    return manifest
