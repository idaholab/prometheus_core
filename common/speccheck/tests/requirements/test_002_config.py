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


@pytest.mark.covers(
    "SPC-REQ-002-01",
    "lint reads --config over speccheck.toml, falls back to [tool.speccheck] in pyproject.toml, and exits 2 with what to pass when neither exists",
)
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


@pytest.mark.covers(
    "SPC-REQ-002-02",
    "a config in sub/ finds sub/specs when run from the parent folder, and a `specs` naming a missing folder exits 2",
)
def test_paths_are_relative_to_the_config(project: Project):
    """A config in a subfolder finds its spec folder next to it, from anywhere; a missing folder is exit 2."""
    project.write("sub/speccheck.toml", 'specs = "specs"\nid-prefix = "T"\n')
    project.write("sub/specs/000-index.md", "")
    assert project.speccheck("lint", "--config", "sub/speccheck.toml").code == 0
    project.write("sub/speccheck.toml", 'specs = "gone"\n')
    run = project.speccheck("lint", "--config", "sub/speccheck.toml")
    assert run.code == 2 and "`specs` is 'gone', which is not a folder" in run.err


@pytest.mark.parametrize(
    ("extra", "key"),
    [
        pytest.param(
            "specz = 1\n",
            "specz",
            marks=pytest.mark.covers(
                "SPC-REQ-002-03", "an unknown top-level key exits 2 naming speccheck.toml and the key"
            ),
            id="top-level",
        ),
        pytest.param(
            "[producers.docker]\nworkflow = []\n",
            "producers.docker.workflow",
            marks=pytest.mark.covers(
                "SPC-REQ-002-03", "a misspelt key in a [producers.docker] table is named with its table"
            ),
            id="producer",
        ),
        pytest.param(
            '[ci.job]\ncovers = { "T-REQ-001-01" = "the job" }\ncover = 1\n',
            "ci.job.cover",
            marks=pytest.mark.covers(
                "SPC-REQ-002-03", "a stray key beside covers in a [ci.job] table is named with its table"
            ),
            id="ci-job",
        ),
        pytest.param(
            "[report]\nname = 1\n",
            "report.name",
            marks=pytest.mark.covers("SPC-REQ-002-03", "an unknown key in the [report] table is named as report.name"),
            id="report",
        ),
    ],
)
def test_unknown_keys_name_the_file_and_key(project: Project, extra: str, key: str):
    """At the top level and in every table."""
    top, tables = (extra, "") if not extra.startswith("[") else ("", extra)
    project.write("speccheck.toml", top + CONFIG + tables)
    run = project.speccheck("lint")
    assert run.code == 2 and f"speccheck.toml: unknown key `{key}`" in run.err


@pytest.mark.covers(
    "SPC-REQ-002-03",
    "an unknown key under [tool.speccheck] in pyproject.toml is named by its full dotted path",
)
def test_unknown_keys_in_pyproject_name_the_dotted_key(project: Project):
    """In a pyproject.toml, the key's full path."""
    (project.root / "speccheck.toml").unlink()
    project.write("pyproject.toml", '[tool.speccheck]\nspecs = "specs"\nprefix = "T"\n')
    assert "pyproject.toml: unknown key `tool.speccheck.prefix`" in project.speccheck("lint").err


@pytest.mark.covers(
    "SPC-REQ-002-04",
    "lowercase, hyphenated and digit-first prefixes exit 2, and an empty prefix reads bare REQ-001-01 bullets",
)
def test_the_prefix(project: Project):
    """A malformed prefix is exit 2; an empty one means bare IDs."""
    for bad in ("spc", "S-PC", "1SPC"):
        project.write("speccheck.toml", f'specs = "specs"\nid-prefix = "{bad}"\n')
        run = project.speccheck("lint")
        assert run.code == 2 and "`id-prefix` must be capital letters and digits" in run.err
    project.write("speccheck.toml", 'specs = "specs"\nid-prefix = ""\n')
    project.spec("- REQ-001-01: Bare. ⚠ untested")
    assert project.speccheck("lint").out == "speccheck lint: 1 specs, 1 requirement\n"


@pytest.mark.covers(
    "SPC-REQ-002-05",
    "a producer limited to spec 002 may not claim T-REQ-001-01, and dropping its `specs` key lets it",
)
def test_a_producer_limited_to_some_specs(project: Project):
    """A claim on a spec outside the producer's list is a problem; "all" is the default."""
    project.write("speccheck.toml", CONFIG.replace('specs = "all"', 'specs = ["002"]'))
    project.spec("- T-REQ-001-01: One. ⚠ untested")
    project.results("r.jsonl", "unit", [("t", ["T-REQ-001-01"], "collected")])
    run = project.speccheck("check", "r.jsonl")
    assert "T-REQ-001-01 is in spec 001, which producer `unit` may not claim" in run.err
    project.write("speccheck.toml", CONFIG.replace('specs = "all"\n', ""))
    assert "may not claim" not in project.speccheck("check", "r.jsonl").err


@pytest.mark.covers(
    "SPC-REQ-002-06",
    "an empty `covers` table and the old list form each exit 2",
)
def test_ci_job_entries(project: Project):
    """`covers` is a table that claims an ID."""
    project.write("speccheck.toml", CONFIG + "[ci.publish]\ncovers = {}\n")
    run = project.speccheck("lint")
    assert run.code == 2 and "`ci.publish.covers` must claim at least one ID" in run.err
    project.write("speccheck.toml", CONFIG + '[ci.publish]\ncovers = ["T-REQ-001-01"]\n')
    run = project.speccheck("lint")
    assert run.code == 2 and "`ci.publish.covers` must be a table from ID to how the job proves it" in run.err


@pytest.mark.covers(
    "SPC-REQ-002-08",
    "a [ci.unit] entry beside producer unit exits 2 saying it has the same name as a producer",
)
def test_a_ci_job_cant_share_a_producers_name(project: Project):
    """A job and a producer are told apart by name, so they can't have the same one."""
    project.write("speccheck.toml", CONFIG + '[ci.unit]\ncovers = { "T-REQ-001-01" = "the job" }\n')
    run = project.speccheck("lint")
    assert run.code == 2 and "`ci.unit` has the same name as a producer" in run.err


@pytest.mark.covers(
    "SPC-REQ-002-06",
    "a CI job's empty, placeholder and non-string explanations exit 2, each naming the job's key and the ID",
)
def test_ci_job_explanations_are_checked_as_a_tests(project: Project):
    """The same spec-free rules as a test's explanation, at config load."""
    for how, message in (
        ('"  "', "`ci.publish.covers.T-REQ-001-01`: the explanation for T-REQ-001-01 is empty"),
        ('"FIXME"', "`ci.publish.covers.T-REQ-001-01`: the explanation for T-REQ-001-01 is a placeholder"),
        ("3", "`ci.publish.covers.T-REQ-001-01` must be a string saying how the job proves it"),
    ):
        project.write("speccheck.toml", CONFIG + f'[ci.publish]\ncovers = {{ "T-REQ-001-01" = {how} }}\n')
        run = project.speccheck("lint")
        assert run.code == 2 and message in run.err, (how, run.err)


@pytest.mark.covers(
    "SPC-REQ-002-06",
    "check fails on a CI job explanation that copies a spec bullet, naming the job and the copied requirement",
)
def test_ci_job_explanation_that_copies_a_requirement(project: Project):
    """The spec-dependent rule (003-09) is checked when the specs are read."""
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: The image MUST build.")
    project.write("speccheck.toml", CONFIG + '[ci.publish]\ncovers = { "T-REQ-001-01" = "the image must build" }\n')
    project.results("r.jsonl", "unit", [("t", ["T-REQ-001-02"], "collected")])
    run = project.speccheck("check", "r.jsonl")
    assert run.code == 1
    assert (
        "speccheck.toml: `ci.publish.covers`: the explanation for T-REQ-001-01 is the text of T-REQ-001-02" in run.err
    )


@pytest.mark.covers(
    "SPC-REQ-002-07",
    "`python -m speccheck lint` succeeds on the Python running the suite, and a broken TOML line exits 2 naming the file",
)
def test_toml_on_this_python(project: Project):
    """The config reads on whichever Python runs this (CI runs 3.10 to 3.14), and bad TOML names the file."""
    done = subprocess.run([sys.executable, "-m", "speccheck", "lint"], cwd=project.root, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    project.write("speccheck.toml", "specs = \n")
    run = project.speccheck("lint")
    assert run.code == 2 and "speccheck.toml: not valid TOML" in run.err
