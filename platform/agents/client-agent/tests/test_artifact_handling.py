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

"""Unit tests for artifact catalog helpers."""

from __future__ import annotations


from orchestration.artifact_handling import merge_artifact_catalogs


def test_merge_artifact_catalogs_preserves_existing_and_incoming() -> None:
    existing = [
        {"artifact_id": "a-1", "name": "Original CAD", "uri": "file:///tmp/original.step"},
    ]
    incoming = [
        {
            "artifact_id": "a-2",
            "name": "New Mesh",
            "uri": "file:///tmp/new.msh",
            "metadata": {"deeplynx_file_id": 42},
        },
    ]

    merged = merge_artifact_catalogs(existing, incoming)

    assert [item["artifact_id"] for item in merged] == ["a-1", "a-2"]
    assert merged[1]["metadata"] == {"deeplynx_file_id": 42}
