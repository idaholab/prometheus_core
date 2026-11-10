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

"""Validating a config table, reading TOML, and finding the file."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from speccheck import config
from speccheck.claims import Claim
from speccheck.config import ConfigError
from speccheck.results import MAX_NAME


@pytest.fixture
def path(tmp_path: Path) -> Path:
    """Where the config pretends to be: beside an existing `specs` folder."""
    (tmp_path / "specs").mkdir()
    return tmp_path / "speccheck.toml"


def table(**extra) -> dict:
    """The smallest valid table, plus `extra` (keys with `-` given as `_`)."""
    return {"specs": "specs", **{k.replace("_", "-"): v for k, v in extra.items()}}


def fails(path: Path, body: dict, message: str, where: str = "") -> None:
    """`from_table` raises a ConfigError naming the file and containing `message`."""
    with pytest.raises(ConfigError, match=re.escape(f"{path}: ") + ".*" + re.escape(message)):
        config.from_table(body, path, where)


class TestFromTable:
    """Every key, its type, and its default."""

    def test_defaults(self, path: Path):
        """Everything but `specs` is optional; the spec folder is resolved against the config's folder."""
        loaded = config.from_table(table(), path)
        assert loaded.specs_dir == (path.parent / "specs").resolve() and loaded.path == path
        assert (loaded.prefix, loaded.require_index, loaded.producers, loaded.title) == (
            "",
            True,
            {},
            "speccheck requirements",
        )

    def test_every_key(self, path: Path):
        """The values given are kept."""
        loaded = config.from_table(table(id_prefix="T", require_index=False, report={"title": "Mine"}), path)
        assert (loaded.prefix, loaded.require_index, loaded.title) == ("T", False, "Mine")

    @pytest.mark.parametrize(
        ("body", "key"),
        [
            (table(spec="x"), "spec"),
            (table(producers={"unit": {"workflow": []}}), "producers.unit.workflow"),
            (table(ci={"job": {"covers": ["X"], "cover": 1}}), "ci.job.cover"),
            (table(report={"name": "x"}), "report.name"),
        ],
    )
    def test_unknown_keys(self, path: Path, body, key):
        """Every table rejects keys it doesn't know, naming the dotted key and the known ones."""
        fails(path, body, f"unknown key `{key}` (known: ")

    def test_keys_are_named_from_where_the_table_is(self, path: Path):
        """In a pyproject.toml, `tool.speccheck.` comes first."""
        fails(path, table(x=1), "unknown key `tool.speccheck.x`", "tool.speccheck")
        fails(path, {"specs": 3}, "`tool.speccheck.specs` must name the spec folder", "tool.speccheck")

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            ({}, "`specs` must name the spec folder"),
            ({"specs": ""}, "`specs` must name the spec folder"),
            ({"specs": 3}, "`specs` must name the spec folder"),
            ({"specs": "gone"}, "`specs` is 'gone', which is not a folder"),
            (table(producers=1), "`producers` must be a table"),
            (table(producers={"unit": 1}), "`producers.unit` must be a table"),
            (table(ci=[]), "`ci` must be a table"),
            (table(require_index="yes"), "`require-index` must be true or false"),
            (table(report=1), "`report` must be a table"),
            (table(report={"title": 1}), "`report.title` must be a string"),
        ],
    )
    def test_wrong_values(self, path: Path, body, message):
        """A value of the wrong type is an error naming its key."""
        fails(path, body, message)

    @pytest.mark.parametrize("bad", ["spc", "S-PC", "1SPC", 3])
    def test_a_malformed_prefix(self, path: Path, bad):
        """Capital letters and digits, starting with a letter."""
        fails(path, table(id_prefix=bad), "`id-prefix` must be capital letters and digits")


class TestProducers:
    """`[producers.<name>]`: which specs a test run may claim, and in which workflows."""

    def test_a_list_of_spec_numbers(self, path: Path):
        """A producer limited to some specs may claim only those, and is expected in its workflows."""
        loaded = config.from_table(table(producers={"unit": {"specs": ["001", "004"], "workflows": ["ci"]}}), path)
        unit = loaded.producers["unit"]
        assert (unit.specs, unit.workflows, unit.ci_job, unit.covers) == (("001", "004"), ("ci",), False, ())
        assert unit.may_claim("004") and not unit.may_claim("002")
        assert loaded.producers_in("ci") == [unit] and loaded.producers_in("other") == []

    def test_all_is_the_default(self, path: Path):
        """Without `specs`, or with `"all"`, a producer may claim every spec."""
        for body in ({}, {"specs": "all"}):
            unit = config.from_table(table(producers={"unit": body}), path).producers["unit"]
            assert unit.specs is None and unit.may_claim("123") and unit.workflows == ()

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            ({"specs": ["1"]}, "`producers.unit.specs`: '1' is not a spec number such as \"001\""),
            ({"specs": "001"}, "`producers.unit.specs` must be a list of strings"),
            ({"specs": [1]}, "`producers.unit.specs` must be a list of strings"),
            ({"workflows": "ci"}, "`producers.unit.workflows` must be a list of strings"),
        ],
    )
    def test_bad_values(self, path: Path, body, message):
        """Spec numbers are three-digit strings; workflows a list of strings."""
        fails(path, table(producers={"unit": body}), message)

    @pytest.mark.parametrize("name", ["Unit", "-x", "a b", "a/b", ""])
    def test_a_bad_name(self, path: Path, name):
        """A name a results file or a command line couldn't carry safely."""
        fails(path, table(producers={name: {}}), "a name is lowercase letters, digits, `-`, `_` and `.`")

    def test_a_name_over_the_limit(self, path: Path):
        """MAX_NAME characters is fine; one more is an error that says how long it is."""
        assert "a" * MAX_NAME in config.from_table(table(producers={"a" * MAX_NAME: {}}), path).producers
        fails(path, table(producers={"a" * (MAX_NAME + 1): {}}), "a name is at most 200 characters; this one is 201")

    @pytest.mark.parametrize("name", ["unit", "speccheck-requirements", "a.b_c", "3"])
    def test_good_names(self, path: Path, name):
        """Lowercase letters, digits, `-`, `_` and `.`, starting with a letter or digit."""
        assert name in config.from_table(table(producers={name: {}}), path).producers


class TestCiJobs:
    """`[ci.<job>]`: a CI job that is itself evidence for the IDs it covers."""

    def test_a_ci_job_is_a_producer(self, path: Path):
        """It claims the IDs it covers, may claim any spec, and is marked as a CI job."""
        body = {"covers": {"T-REQ-001-01": "  it\n publishes ", "T-REQ-001-02": "it is signed"}, "workflows": ["ci"]}
        job = config.from_table(table(ci={"publish": body}), path).producers["publish"]
        assert (job.ci_job, job.covers, job.workflows, job.specs) == (
            True,
            ("T-REQ-001-01", "T-REQ-001-02"),
            ("ci",),
            None,
        )
        assert job.claims == (Claim("T-REQ-001-01", "it publishes"), Claim("T-REQ-001-02", "it is signed"))

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            ({"covers": {}}, "`ci.publish.covers` must claim at least one ID"),
            ({}, "`ci.publish.covers` must be a table from ID to how the job proves it"),
            ({"covers": ["X"]}, "`ci.publish.covers` must be a table from ID to how the job proves it"),
            ({"covers": {"X": 3}}, "`ci.publish.covers.X` must be a string saying how the job proves it"),
            ({"covers": {"X": " "}}, "`ci.publish.covers.X`: the explanation for X is empty"),
            ({"covers": {"X": "tbd"}}, "`ci.publish.covers.X`: the explanation for X is a placeholder"),
            ({"covers": {"X": "h"}, "workflows": 1}, "`ci.publish.workflows` must be a list of strings"),
        ],
    )
    def test_bad_values(self, path: Path, body, message):
        """`covers` is a table that claims something, each explanation usable as a test's."""
        fails(path, table(ci={"publish": body}), message)

    def test_a_bad_name(self, path: Path):
        """The same rule as a producer's."""
        fails(path, table(ci={"Pub": {"covers": {"X": "h"}}}), "`ci.Pub`: a name is lowercase")

    def test_a_name_over_the_limit(self, path: Path):
        """The same limit as a producer's."""
        fails(path, table(ci={"j" * 201: {"covers": {"X": "h"}}}), "a name is at most 200 characters; this one is 201")

    def test_a_ci_job_cant_share_a_producers_name(self, path: Path):
        """Two entries would claim to be the same results file's producer."""
        fails(
            path, table(producers={"x": {}}, ci={"x": {"covers": {"X": "h"}}}), "`ci.x` has the same name as a producer"
        )


class TestLoad:
    """Reading TOML: a speccheck.toml is the table; a pyproject.toml has it under [tool.speccheck]."""

    def test_speccheck_toml(self, path: Path):
        """The whole file is the table."""
        path.write_text('specs = "specs"\nid-prefix = "T"\n')
        assert config.load(path).prefix == "T"

    def test_pyproject_table(self, path: Path):
        """The table is read from pyproject.toml, and errors name its dotted key."""
        pyproject = path.parent / "pyproject.toml"
        pyproject.write_text('[tool.speccheck]\nspecs = "specs"\nid-prefix = "T"\n')
        assert config.load(pyproject).prefix == "T"
        pyproject.write_text('[tool.speccheck]\nspecs = "specs"\nx = 1\n')
        with pytest.raises(ConfigError, match="unknown key `tool.speccheck.x`"):
            config.load(pyproject)
        pyproject.write_text("[tool.other]\n")
        with pytest.raises(ConfigError, match=r"no \[tool.speccheck\] table"):
            config.load(pyproject)

    def test_not_toml(self, path: Path):
        """A syntax error names the file, not a traceback."""
        path.write_text("specs = \n")
        with pytest.raises(ConfigError, match="speccheck.toml: not valid TOML"):
            config.load(path)

    def test_missing(self, path: Path):
        """A file that isn't there can't be read."""
        with pytest.raises(ConfigError, match="speccheck.toml: can't read the config: No such file"):
            config.load(path)

    def test_the_toml_module(self):
        """tomllib from 3.11, tomli before."""
        expected = "tomllib" if sys.version_info >= (3, 11) else "tomli"
        assert config.tomllib.__name__ == expected


class TestFind:
    """Which file is the config."""

    def test_explicit_wins(self, tmp_path: Path):
        """`--config` is used even when speccheck.toml exists, relative to the cwd, or absolute."""
        (tmp_path / "speccheck.toml").write_text("")
        (tmp_path / "other.toml").write_text("")
        assert config.find("other.toml", tmp_path) == tmp_path / "other.toml"
        assert config.find(str(tmp_path / "other.toml"), Path("/")) == tmp_path / "other.toml"

    def test_explicit_missing(self, tmp_path: Path):
        """A `--config` that doesn't exist says so, as given."""
        with pytest.raises(ConfigError, match="^nope.toml: no such config file$"):
            config.find("nope.toml", tmp_path)

    def test_speccheck_toml_then_pyproject(self, tmp_path: Path):
        """speccheck.toml first; without it, a pyproject.toml with [tool.speccheck]."""
        (tmp_path / "pyproject.toml").write_text('[tool.speccheck]\nspecs = "specs"\n')
        assert config.find(None, tmp_path) == tmp_path / "pyproject.toml"
        (tmp_path / "speccheck.toml").write_text("")
        assert config.find(None, tmp_path) == tmp_path / "speccheck.toml"

    def test_nothing_found(self, tmp_path: Path):
        """A pyproject.toml without the table doesn't count, and the message says what to pass."""
        with pytest.raises(ConfigError, match="pass --config PATH"):
            config.find(None, tmp_path)
        (tmp_path / "pyproject.toml").write_text("[tool.other]\n")
        with pytest.raises(ConfigError, match="pass --config PATH"):
            config.find(None, tmp_path)
