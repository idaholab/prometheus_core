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

"""Finding, reading and validating the config."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from speccheck import config
from speccheck.config import ConfigError
from tests.conftest import Repo


def load_text(repo: Repo, text: str, name: str = "speccheck.toml") -> config.Config:
    """Write a config and load it."""
    return config.load(repo.write(name, text))


class TestFind:
    """Which file is the config."""

    def test_explicit_wins(self, repo: Repo):
        """`--config` is used even when speccheck.toml exists, relative to the current folder."""
        repo.write("other.toml", 'specs = "specs"\n')
        assert config.find("other.toml", repo.root) == repo.root / "other.toml"
        assert config.find(str(repo.root / "other.toml"), Path("/")) == repo.root / "other.toml"

    def test_explicit_missing(self, repo: Repo):
        """A `--config` that doesn't exist says so."""
        with pytest.raises(ConfigError, match="nope.toml: no such config file"):
            config.find("nope.toml", repo.root)

    def test_speccheck_toml_then_pyproject(self, repo: Repo):
        """speccheck.toml first; without it, a pyproject.toml with [tool.speccheck]."""
        assert config.find(None, repo.root) == repo.root / "speccheck.toml"
        (repo.root / "speccheck.toml").unlink()
        repo.write("pyproject.toml", '[tool.speccheck]\nspecs = "specs"\n')
        assert config.find(None, repo.root) == repo.root / "pyproject.toml"

    def test_nothing_found(self, repo: Repo):
        """A pyproject.toml without the table doesn't count, and the message says what to pass."""
        (repo.root / "speccheck.toml").unlink()
        repo.write("pyproject.toml", "[tool.other]\n")
        with pytest.raises(ConfigError, match="pass --config PATH"):
            config.find(None, repo.root)

    def test_pyproject_table(self, repo: Repo):
        """The table is read from pyproject.toml, and errors name its dotted key."""
        loaded = load_text(repo, '[tool.speccheck]\nspecs = "specs"\nid-prefix = "T"\n', "pyproject.toml")
        assert loaded.prefix == "T"
        with pytest.raises(ConfigError, match="unknown key `tool.speccheck.x`"):
            load_text(repo, '[tool.speccheck]\nspecs = "specs"\nx = 1\n', "pyproject.toml")
        with pytest.raises(ConfigError, match=r"no \[tool.speccheck\] table"):
            load_text(repo, "[tool.other]\n", "pyproject.toml")


class TestPaths:
    """The spec folder."""

    def test_relative_to_the_config_file(self, repo: Repo):
        """`specs` is resolved against the config's folder, not the current one."""
        repo.write("sub/specs/000-index.md", "")
        loaded = load_text(repo, 'specs = "specs"\n', "sub/speccheck.toml")
        assert loaded.specs_dir == (repo.root / "sub" / "specs").resolve()

    def test_specs_must_be_a_folder(self, repo: Repo):
        """A missing or empty `specs` is an error."""
        with pytest.raises(ConfigError, match="`specs` is 'gone', which is not a folder"):
            load_text(repo, 'specs = "gone"\n')
        with pytest.raises(ConfigError, match="`specs` must name the spec folder"):
            load_text(repo, "specs = 3\n")


class TestUnknownKeys:
    """Every table rejects keys it doesn't know."""

    @pytest.mark.parametrize(
        ("text", "key"),
        [
            ('specs = "specs"\nspec = "x"\n', "spec"),
            ('specs = "specs"\n[producers.unit]\nworkflow = []\n', "producers.unit.workflow"),
            ('specs = "specs"\n[ci.job]\ncovers = ["T-REQ-001-01"]\ncover = 1\n', "ci.job.cover"),
            ('specs = "specs"\n[report]\nname = "x"\n', "report.name"),
        ],
    )
    def test_unknown_key(self, repo: Repo, text: str, key: str):
        """The message names the file and the dotted key."""
        with pytest.raises(ConfigError, match=f"speccheck.toml: unknown key `{key}`"):
            load_text(repo, text)

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ('specs = "specs"\nproducers = 1\n', "`producers` must be a table"),
            ('specs = "specs"\nrequire-index = "yes"\n', "`require-index` must be true or false"),
            ('specs = "specs"\n[report]\ntitle = 1\n', "`report.title` must be a string"),
            ('specs = "specs"\n[producers.unit]\nworkflows = "ci"\n', "`producers.unit.workflows` must be a list"),
            ('specs = "specs"\n[producers.Unit]\n', "a name is lowercase letters"),
        ],
    )
    def test_wrong_types(self, repo: Repo, text: str, message: str):
        """A value of the wrong type is an error naming its key."""
        with pytest.raises(ConfigError, match=message):
            load_text(repo, text)

    def test_defaults(self, repo: Repo):
        """Everything but `specs` is optional."""
        loaded = load_text(repo, 'specs = "specs"\n')
        assert (loaded.prefix, loaded.require_index, loaded.producers, loaded.title) == (
            "",
            True,
            {},
            "speccheck requirements",
        )


@pytest.mark.parametrize("bad", ["spc", "S-PC", "1SPC", 3])
def test_a_malformed_prefix_fails(repo: Repo, bad):
    """Capital letters and digits, starting with a letter."""
    value = f'"{bad}"' if isinstance(bad, str) else bad
    with pytest.raises(ConfigError, match="`id-prefix` must be capital letters"):
        load_text(repo, f'specs = "specs"\nid-prefix = {value}\n')


class TestProducers:
    """Which specs a producer may claim."""

    def test_a_list_of_spec_numbers(self, repo: Repo):
        """A producer limited to some specs may claim only those."""
        loaded = load_text(repo, 'specs = "specs"\n[producers.unit]\nspecs = ["001", "004"]\nworkflows = ["ci"]\n')
        unit = loaded.producers["unit"]
        assert unit.may_claim("004") and not unit.may_claim("002")
        assert loaded.producers_in("ci") == [unit] and loaded.producers_in("other") == []

    def test_all_is_the_default(self, repo: Repo):
        """Without `specs`, a producer may claim every spec."""
        loaded = load_text(repo, 'specs = "specs"\n[producers.unit]\n')
        assert loaded.producers["unit"].specs is None and loaded.producers["unit"].may_claim("123")

    def test_a_bad_spec_number(self, repo: Repo):
        """Spec numbers are three digits, as strings."""
        with pytest.raises(ConfigError, match="'1' is not a spec number"):
            load_text(repo, 'specs = "specs"\n[producers.unit]\nspecs = ["1"]\n')


class TestCiJobs:
    """`[ci.<job>]` entries."""

    def test_a_ci_job_is_a_producer(self, repo: Repo):
        """It claims the IDs it covers, and is marked as a CI job."""
        loaded = load_text(repo, 'specs = "specs"\n[ci.publish]\ncovers = ["T-REQ-001-01"]\nworkflows = ["ci"]\n')
        job = loaded.producers["publish"]
        assert (job.ci_job, job.covers, job.workflows) == (True, ("T-REQ-001-01",), ("ci",))

    def test_covers_is_required(self, repo: Repo):
        """An empty or missing `covers` is an error."""
        with pytest.raises(ConfigError, match="`ci.publish.covers` must list at least one ID"):
            load_text(repo, 'specs = "specs"\n[ci.publish]\ncovers = []\n')
        with pytest.raises(ConfigError, match="`ci.publish.covers` must be a list of strings"):
            load_text(repo, 'specs = "specs"\n[ci.publish]\n')

    def test_a_ci_job_cant_share_a_producers_name(self, repo: Repo):
        """Two entries would claim to be the same results file's producer."""
        with pytest.raises(ConfigError, match="same name as a producer"):
            load_text(repo, 'specs = "specs"\n[producers.x]\n[ci.x]\ncovers = ["T-REQ-001-01"]\n')


class TestToml:
    """TOML on every Python."""

    def test_the_toml_module(self):
        """tomllib from 3.11, tomli before."""
        expected = "tomllib" if sys.version_info >= (3, 11) else "tomli"
        assert config.tomllib.__name__ == expected

    def test_a_syntax_error_names_the_file(self, repo: Repo):
        """Not a traceback."""
        with pytest.raises(ConfigError, match="speccheck.toml: not valid TOML"):
            load_text(repo, "specs = \n")
