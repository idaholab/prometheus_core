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

"""Load and validate one spec folder's config: `speccheck.toml`, or `[tool.speccheck]` in a pyproject.toml.

See plan/design.md, "Config". Paths are relative to the config file. Any key speccheck doesn't
know, a producer that doesn't exist, or a path that isn't there is an error naming the file and key.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from speccheck.specs import PREFIX

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

CONFIG_FILE = "speccheck.toml"
"""The config file name looked for first."""
PYPROJECT = "pyproject.toml"
"""Where a project's config lives, under `[tool.speccheck]`, when there is no speccheck.toml."""

NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
"""A producer or CI job name: lowercase letters, digits, `-`, `_` and `.`."""
SPEC_NUMBER = re.compile(r"^\d{3}$")
"""A spec number in a producer's `specs` list."""

TOP_KEYS = {"specs", "id-prefix", "require-index", "producers", "ci", "report"}
"""The keys allowed at the top of the config."""
PRODUCER_KEYS = {"specs", "workflows"}
"""The keys allowed in a `[producers.<name>]` table."""
CI_KEYS = {"covers", "workflows"}
"""The keys allowed in a `[ci.<job>]` table."""
REPORT_KEYS = {"title"}
"""The keys allowed in the `[report]` table."""


class ConfigError(Exception):
    """The config is missing, malformed, or names something that doesn't exist; exit code 2."""


@dataclass(frozen=True)
class Producer:
    """A test run or a CI job that can provide evidence."""

    name: str
    """Its name, as `SPECCHECK_PRODUCER` gives it and results files carry it."""
    specs: tuple[str, ...] | None
    """The spec numbers it may claim, or None for all of them."""
    workflows: tuple[str, ...]
    """The workflows it runs in, so `verify --complete` knows when it should have reported."""
    covers: tuple[str, ...] = ()
    """For a CI job (`[ci.<job>]`), the IDs it claims; empty for a test run."""
    ci_job: bool = False
    """Whether it is a CI job that `record` writes results for, rather than a test run."""

    def may_claim(self, spec_number: str) -> bool:
        """Whether this producer may claim a requirement of the given spec."""
        return self.specs is None or spec_number in self.specs


@dataclass
class Config:
    """One spec folder's settings."""

    path: Path
    """The config file."""
    specs_dir: Path
    """The spec folder."""
    prefix: str = ""
    """The ID prefix, such as `SPC`; empty for bare IDs."""
    require_index: bool = True
    """Whether 000-index.md must exist and link every spec."""
    producers: dict[str, Producer] = field(default_factory=dict)
    """Every producer, test runs and CI jobs, by name."""
    title: str = "speccheck requirements"
    """The report's title."""

    def producers_in(self, workflow: str) -> list[Producer]:
        """The producers expected to report in one workflow."""
        return [p for p in self.producers.values() if workflow in p.workflows]


def find(explicit: str | None, cwd: Path) -> Path:
    """The config file to use: `--config`, else speccheck.toml, else a pyproject.toml with `[tool.speccheck]`."""
    if explicit:
        path = Path(explicit)
        path = path if path.is_absolute() else cwd / path
        if not path.is_file():
            raise ConfigError(f"{explicit}: no such config file")
        return path
    if (cwd / CONFIG_FILE).is_file():
        return cwd / CONFIG_FILE
    pyproject = cwd / PYPROJECT
    if pyproject.is_file() and "speccheck" in _read(pyproject).get("tool", {}):
        return pyproject
    raise ConfigError(f"no {CONFIG_FILE}, and no [tool.speccheck] in {PYPROJECT}, here; pass --config PATH")


def _read(path: Path) -> dict[str, Any]:
    """Parse a TOML file, turning a missing file or a syntax error into a ConfigError."""
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"{path}: can't read the config: {exc.strerror}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: not valid TOML: {exc}") from None


def load(path: Path) -> Config:
    """Read and validate the config file at `path`."""
    data = _read(path)
    if path.name == PYPROJECT:
        table = data.get("tool", {}).get("speccheck")
        if table is None:
            raise ConfigError(f"{path}: no [tool.speccheck] table")
        where = "tool.speccheck"
    else:
        table = data
        where = ""
    return from_table(table, path, where)


def _key(where: str, key: str) -> str:
    """A dotted key name for messages, such as `tool.speccheck.producers.unit.specs`."""
    return f"{where}.{key}" if where else key


def _unknown(table: dict[str, Any], allowed: set[str], path: Path, where: str) -> None:
    """Fail on any key not in `allowed`."""
    for key in table:
        if key not in allowed:
            known = ", ".join(sorted(allowed))
            raise ConfigError(f"{path}: unknown key `{_key(where, key)}` (known: {known})")


def _strings(value: Any, path: Path, key: str) -> tuple[str, ...]:
    """A list of strings, or a ConfigError."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{path}: `{key}` must be a list of strings")
    return tuple(value)


def _table(value: Any, path: Path, key: str) -> dict[str, Any]:
    """A TOML table, or a ConfigError."""
    if not isinstance(value, dict):
        raise ConfigError(f"{path}: `{key}` must be a table")
    return value


def from_table(table: dict[str, Any], path: Path, where: str = "") -> Config:
    """Validate a config table read from `path`; `where` is its dotted location in the file."""
    _unknown(table, TOP_KEYS, path, where)
    specs = table.get("specs")
    if not isinstance(specs, str) or not specs:
        raise ConfigError(f"{path}: `{_key(where, 'specs')}` must name the spec folder")
    specs_dir = (path.parent / specs).resolve()
    if not specs_dir.is_dir():
        raise ConfigError(f"{path}: `{_key(where, 'specs')}` is {specs!r}, which is not a folder")

    prefix = table.get("id-prefix", "")
    if not isinstance(prefix, str) or (prefix and not PREFIX.match(prefix)):
        raise ConfigError(f"{path}: `{_key(where, 'id-prefix')}` must be capital letters and digits, such as `SPC`")
    require_index = table.get("require-index", True)
    if not isinstance(require_index, bool):
        raise ConfigError(f"{path}: `{_key(where, 'require-index')}` must be true or false")

    config = Config(path=path, specs_dir=specs_dir, prefix=prefix, require_index=require_index)
    for name, body in _table(table.get("producers", {}), path, _key(where, "producers")).items():
        key = _key(where, f"producers.{name}")
        config.producers[name] = _producer(name, _table(body, path, key), path, key)
    for name, body in _table(table.get("ci", {}), path, _key(where, "ci")).items():
        key = _key(where, f"ci.{name}")
        if name in config.producers:
            raise ConfigError(f"{path}: `{key}` has the same name as a producer; a CI job is its own producer")
        config.producers[name] = _ci_job(name, _table(body, path, key), path, key)

    report = _table(table.get("report", {}), path, _key(where, "report"))
    _unknown(report, REPORT_KEYS, path, _key(where, "report"))
    title = report.get("title", config.title)
    if not isinstance(title, str):
        raise ConfigError(f"{path}: `{_key(where, 'report.title')}` must be a string")
    config.title = title
    return config


def _check_name(name: str, path: Path, key: str) -> None:
    """Fail on a producer or job name that a results file or a command line couldn't carry safely."""
    if not NAME.match(name):
        raise ConfigError(f"{path}: `{key}`: a name is lowercase letters, digits, `-`, `_` and `.`")


def _producer(name: str, body: dict[str, Any], path: Path, key: str) -> Producer:
    """One `[producers.<name>]` table."""
    _check_name(name, path, key)
    _unknown(body, PRODUCER_KEYS, path, key)
    specs = body.get("specs", "all")
    if specs == "all":
        numbers = None
    else:
        numbers = _strings(specs, path, f"{key}.specs")
        for number in numbers:
            if not SPEC_NUMBER.match(number):
                raise ConfigError(f'{path}: `{key}.specs`: {number!r} is not a spec number such as "001"')
    return Producer(name=name, specs=numbers, workflows=_strings(body.get("workflows", []), path, f"{key}.workflows"))


def _ci_job(name: str, body: dict[str, Any], path: Path, key: str) -> Producer:
    """One `[ci.<job>]` table: a CI job that is itself the evidence for the IDs it covers."""
    _check_name(name, path, key)
    _unknown(body, CI_KEYS, path, key)
    covers = _strings(body.get("covers"), path, f"{key}.covers")
    if not covers:
        raise ConfigError(f"{path}: `{key}.covers` must list at least one ID")
    workflows = _strings(body.get("workflows", []), path, f"{key}.workflows")
    return Producer(name=name, specs=None, workflows=workflows, covers=covers, ci_job=True)
