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

"""specs/002-config.md, through the command line."""

from __future__ import annotations

import subprocess
import sys

import pytest

from tests.requirements.conftest import CONFIG, Project


@pytest.mark.covers("SPC-REQ-002-01")
def test_which_config_is_used(project: Project):
    """`--config` first, then speccheck.toml, then [tool.speccheck]; none is exit 2 with what to pass."""
    project.spec("- T-REQ-001-01: One. ⚠ untested")
    project.write("other.toml", 'specs = "specs"\nid-prefix = "OTHER"\n')
    # T-REQ-001-01 is not a bullet in a folder whose prefix is OTHER, so other.toml sees no requirements
    assert project.speccheck("lint", "--config", "other.toml").out == "speccheck lint: 1 specs, 0 requirements\n"
    assert project.speccheck("lint").out == "speccheck lint: 1 specs, 1 requirement\n"
    assert project.speccheck("lint").code == 0
    (project.root / "speccheck.toml").unlink()
    project.write("pyproject.toml", '[tool.speccheck]\nspecs = "specs"\nid-prefix = "T"\n')
    assert project.speccheck("lint").code == 0
    (project.root / "pyproject.toml").unlink()
    run = project.speccheck("lint")
    assert run.code == 2
    assert "no speccheck.toml, and no [tool.speccheck] in pyproject.toml, here; pass --config PATH" in run.err


@pytest.mark.covers("SPC-REQ-002-02")
def test_paths_are_relative_to_the_config(project: Project):
    """A config in a subfolder finds its spec folder next to it, from anywhere; a missing folder is exit 2."""
    project.write("sub/speccheck.toml", 'specs = "specs"\nid-prefix = "T"\n')
    project.write("sub/specs/000-index.md", "")
    assert project.speccheck("lint", "--config", "sub/speccheck.toml").code == 0
    project.write("sub/speccheck.toml", 'specs = "gone"\n')
    run = project.speccheck("lint", "--config", "sub/speccheck.toml")
    assert run.code == 2 and "`specs` is 'gone', which is not a folder" in run.err


@pytest.mark.covers("SPC-REQ-002-03")
@pytest.mark.parametrize(
    ("extra", "key"),
    [
        ("specz = 1\n", "specz"),
        ("[producers.docker]\nworkflow = []\n", "producers.docker.workflow"),
        ('[ci.job]\ncovers = ["T-REQ-001-01"]\ncover = 1\n', "ci.job.cover"),
        ("[report]\nname = 1\n", "report.name"),
    ],
)
def test_unknown_keys_name_the_file_and_key(project: Project, extra: str, key: str):
    """At the top level and in every table."""
    top, tables = (extra, "") if not extra.startswith("[") else ("", extra)
    project.write("speccheck.toml", top + CONFIG + tables)
    run = project.speccheck("lint")
    assert run.code == 2 and f"speccheck.toml: unknown key `{key}`" in run.err


@pytest.mark.covers("SPC-REQ-002-03")
def test_unknown_keys_in_pyproject_name_the_dotted_key(project: Project):
    """In a pyproject.toml, the key's full path."""
    (project.root / "speccheck.toml").unlink()
    project.write("pyproject.toml", '[tool.speccheck]\nspecs = "specs"\nprefix = "T"\n')
    assert "pyproject.toml: unknown key `tool.speccheck.prefix`" in project.speccheck("lint").err


@pytest.mark.covers("SPC-REQ-002-04")
def test_the_prefix(project: Project):
    """A malformed prefix is exit 2; an empty one means bare IDs."""
    for bad in ("spc", "S-PC", "1SPC"):
        project.write("speccheck.toml", f'specs = "specs"\nid-prefix = "{bad}"\n')
        run = project.speccheck("lint")
        assert run.code == 2 and "`id-prefix` must be capital letters and digits" in run.err
    project.write("speccheck.toml", 'specs = "specs"\nid-prefix = ""\n')
    project.spec("- REQ-001-01: Bare. ⚠ untested")
    assert project.speccheck("lint").out == "speccheck lint: 1 specs, 1 requirement\n"


@pytest.mark.covers("SPC-REQ-002-05")
def test_a_producer_limited_to_some_specs(project: Project):
    """A claim on a spec outside the producer's list is a problem; "all" is the default."""
    project.write("speccheck.toml", CONFIG.replace('specs = "all"', 'specs = ["002"]'))
    project.spec("- T-REQ-001-01: One. ⚠ untested")
    project.results("r.jsonl", "unit", [("t", ["T-REQ-001-01"], "collected")])
    run = project.speccheck("check", "r.jsonl")
    assert "T-REQ-001-01 is in spec 001, which producer `unit` may not claim" in run.err
    project.write("speccheck.toml", CONFIG.replace('specs = "all"\n', ""))
    assert "may not claim" not in project.speccheck("check", "r.jsonl").err


@pytest.mark.covers("SPC-REQ-002-06")
def test_ci_job_entries(project: Project):
    """`covers` must list an ID, and a job can't share a producer's name."""
    project.write("speccheck.toml", CONFIG + "[ci.publish]\ncovers = []\n")
    assert "`ci.publish.covers` must list at least one ID" in project.speccheck("lint").err
    project.write("speccheck.toml", CONFIG + '[ci.unit]\ncovers = ["T-REQ-001-01"]\n')
    run = project.speccheck("lint")
    assert run.code == 2 and "`ci.unit` has the same name as a producer" in run.err


@pytest.mark.covers("SPC-REQ-002-07")
def test_toml_on_this_python(project: Project):
    """The config reads on whichever Python runs this (CI runs 3.10 to 3.14), and bad TOML names the file."""
    done = subprocess.run([sys.executable, "-m", "speccheck", "lint"], cwd=project.root, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    project.write("speccheck.toml", "specs = \n")
    run = project.speccheck("lint")
    assert run.code == 2 and "speccheck.toml: not valid TOML" in run.err
