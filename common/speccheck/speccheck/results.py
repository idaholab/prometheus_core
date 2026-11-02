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

"""The `speccheck-results/1` file: what a test run or a CI job claims, and how each claim came out.

See plan/design.md, "Results files", and `schema/speccheck-results-1.schema.json`. JSON Lines: one
header, then one line per claiming test. A results file is untrusted data, since a pull request
controls what its tests write: it is parsed as JSON only, size-limited, every field is checked,
and paths in it are never opened.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from speccheck.specs import Problem

SCHEMA = "speccheck-results/1"
"""The format and its version. A reader rejects any other value instead of guessing."""

OUTCOMES = ("passed", "failed", "error", "skipped", "xfailed", "xpassed", "deselected", "collected")
"""Every outcome a result may have. Only `passed` is evidence."""
KINDS = ("test", "ci")
"""A result is a test, or a CI job recorded by `record`."""

MAX_FILE_BYTES = 16 * 1024 * 1024
"""The largest results file read; a bigger one is a problem, not a crash or a memory spike."""
MAX_LINE_BYTES = 64 * 1024
"""The longest line read."""
MAX_TEXT = 1000
"""The longest string field kept, after which a field is a problem."""
MAX_COVERS = 200
"""The most IDs one result may claim."""

HEADER_KEYS = {"schema", "producer", "runner", "ci", "started"}
"""The header keys this speccheck reads; a reader ignores any other (see `_known`)."""
CI_KEYS = {
    "provider",
    "server",
    "repository",
    "workflow",
    "job",
    "leg",
    "run_id",
    "run_attempt",
    "job_id",
    "sha",
    "ref",
    "event",
    "run_url",
    "job_url",
}
"""The keys of a header's `ci` block this speccheck reads; any other is ignored."""
RESULT_KEYS = {"test", "file", "line", "covers", "outcome", "kind"}
"""The result keys this speccheck reads; any other is ignored."""


@dataclass
class Result:
    """One claiming test (or CI job) and its outcome."""

    test: str
    """The test's node ID, or the CI job's name."""
    covers: list[str]
    """The IDs it claims."""
    outcome: str
    """One of OUTCOMES."""
    file: str = ""
    """The test file, as the runner reported it; never opened."""
    line: int = 0
    """The test's line in that file, 1-based, or 0 when unknown."""
    kind: str = "test"
    """`test` or `ci`."""

    def to_json(self) -> dict[str, Any]:
        """The result line's object."""
        body: dict[str, Any] = {"test": self.test, "covers": self.covers, "outcome": self.outcome}
        if self.file:
            body["file"] = self.file
        if self.line:
            body["line"] = self.line
        if self.kind != "test":
            body["kind"] = self.kind
        return body


@dataclass
class ResultsFile:
    """One results file: who wrote it, where, and its results."""

    producer: str
    """The producer, from `SPECCHECK_PRODUCER` or `record`."""
    runner: str = ""
    """What wrote it, such as `pytest 8.4.1`."""
    ci: dict[str, Any] | None = None
    """Where it ran (see `ci.context`), or None outside CI."""
    started: str = ""
    """When the run started, ISO 8601 UTC."""
    results: list[Result] = field(default_factory=list)
    """Its results, in the order written."""
    source: str = ""
    """The file it was read from, for messages; not part of the format."""

    def header(self) -> dict[str, Any]:
        """The header line's object."""
        return {
            "schema": SCHEMA,
            "producer": self.producer,
            "runner": self.runner,
            "ci": self.ci,
            "started": self.started,
        }


def dumps(results_file: ResultsFile) -> str:
    """The file's text: the header, then one line per result."""
    lines = [results_file.header(), *(result.to_json() for result in results_file.results)]
    return "".join(json.dumps(line, sort_keys=True, ensure_ascii=False) + "\n" for line in lines)


def _umask() -> int:
    """The process umask; it can only be read by setting it."""
    mask = os.umask(0)
    os.umask(mask)
    return mask


def write(path: Path, results_file: ResultsFile) -> None:
    """Write atomically: to a temporary file beside `path`, then renamed over it, so a crash leaves nothing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(dumps(results_file))
        # mkstemp makes the file 0600; give it the mode an ordinary new file would get, so a file written by
        # a container as root can be read by the host user
        os.chmod(temporary, 0o666 & ~_umask())
        os.replace(temporary, path)
    except BaseException:
        os.unlink(temporary)
        raise


SURROGATE = re.compile("[\ud800-\udfff]")
"""A lone surrogate: valid in JSON's `\\u` escapes, but not text, so it can't be written out as UTF-8."""


class Invalid(Exception):
    """A field of a results file is wrong; the message says which."""


def _text(value: Any, name: str, *, allow_empty: bool = True) -> str:
    """A string field, length-checked."""
    if not isinstance(value, str):
        raise Invalid(f"`{name}` must be a string")
    if len(value) > MAX_TEXT:
        raise Invalid(f"`{name}` is longer than {MAX_TEXT} characters")
    if SURROGATE.search(value):
        raise Invalid(f"`{name}` has a lone surrogate (`\\ud800` to `\\udfff`), which isn't text")
    if not allow_empty and not value:
        raise Invalid(f"`{name}` must not be empty")
    return value


def _known(body: dict[str, Any], keys: set[str]) -> dict[str, Any]:
    """Only the keys this speccheck reads: a newer writer may add fields within a schema, and those are
    dropped here, unread and never printed."""
    return {key: value for key, value in body.items() if key in keys}


def _header(body: Any) -> ResultsFile:
    """Validate the header line."""
    if not isinstance(body, dict):
        raise Invalid("the first line must be the header object")
    if body.get("schema") != SCHEMA:
        raise Invalid(f"`schema` is {body.get('schema')!r}; this speccheck reads only {SCHEMA!r}")
    body = _known(body, HEADER_KEYS)
    ci = body.get("ci")
    if ci is not None:
        if not isinstance(ci, dict):
            raise Invalid("`ci` must be an object or null")
        ci = _known(ci, CI_KEYS)
        for key, value in ci.items():
            if value is not None and not isinstance(value, (str, int)) or isinstance(value, bool):
                raise Invalid(f"`ci.{key}` must be a string, a number or null")
            if isinstance(value, str):
                _text(value, f"ci.{key}")
    return ResultsFile(
        producer=_text(body.get("producer"), "producer", allow_empty=False),
        runner=_text(body.get("runner", ""), "runner"),
        ci=ci,
        started=_text(body.get("started", ""), "started"),
    )


def _result(body: Any) -> Result:
    """Validate one result line."""
    if not isinstance(body, dict):
        raise Invalid("a result must be an object")
    body = _known(body, RESULT_KEYS)
    covers = body.get("covers")
    if not isinstance(covers, list) or not covers or len(covers) > MAX_COVERS:
        raise Invalid(f"`covers` must be a list of 1 to {MAX_COVERS} IDs")
    outcome = body.get("outcome")
    if outcome not in OUTCOMES:
        raise Invalid(f"`outcome` is {outcome!r}; it must be one of {', '.join(OUTCOMES)}")
    kind = body.get("kind", "test")
    if kind not in KINDS:
        raise Invalid(f"`kind` must be one of {', '.join(KINDS)}")
    line = body.get("line", 0)
    if not isinstance(line, int) or isinstance(line, bool) or line < 0:
        raise Invalid("`line` must be a whole number")
    return Result(
        test=_text(body.get("test"), "test", allow_empty=False),
        covers=[_text(item, "covers[]", allow_empty=False) for item in covers],
        outcome=outcome,
        file=_text(body.get("file", ""), "file"),
        line=line,
        kind=kind,
    )


def parse(text: str, source: str) -> tuple[ResultsFile | None, list[Problem]]:
    """Parse one file's text; on any problem return None and the problem, so one bad file can't count."""
    # Split on "\n" only, as `dumps` writes it: splitlines() also splits on U+2028, U+0085 and the like,
    # which `ensure_ascii=False` leaves unescaped inside a test ID, and would cut that line in two.
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    if not lines:
        return None, [Problem(source, 0, "empty results file; the run that wrote it may have crashed", "results-empty")]
    for number, line in enumerate(lines, 1):
        if len(line.encode("utf-8")) > MAX_LINE_BYTES:
            return None, [Problem(source, number, f"line longer than {MAX_LINE_BYTES} bytes", "results-line-too-long")]
    parsed: ResultsFile | None = None
    for number, line in enumerate(lines, 1):
        if number > 1 and not line.strip():
            continue
        try:
            body = json.loads(line)
            if parsed is None:
                parsed = _header(body)
            else:
                parsed.results.append(_result(body))
        except json.JSONDecodeError as exc:
            return None, [Problem(source, number, f"not JSON: {exc.msg}", "results-not-json")]
        except RecursionError:
            return None, [
                Problem(source, number, "not JSON this reader accepts: nested too deeply", "results-not-json")
            ]
        except ValueError as exc:  # such as an integer of more digits than Python converts
            return None, [Problem(source, number, f"not JSON this reader accepts: {exc}", "results-not-json")]
        except Invalid as exc:
            return None, [Problem(source, number, f"not a valid {SCHEMA} line: {exc}", "results-invalid")]
    parsed.source = source
    return parsed, []


def read(path: Path, source: str | None = None) -> tuple[ResultsFile | None, list[Problem]]:
    """Read and validate one results file, refusing one bigger than MAX_FILE_BYTES."""
    source = source or path.as_posix()
    try:
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            return None, [
                Problem(source, 0, f"results file is {size} bytes; the limit is {MAX_FILE_BYTES}", "results-too-large")
            ]
        data = path.read_bytes()
    except OSError as exc:
        return None, [Problem(source, 0, f"can't read: {exc.strerror}", "results-unreadable")]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None, [Problem(source, 0, "not UTF-8 text", "results-not-utf8")]
    return parse(text, source)


def collect(paths: Iterable[Path]) -> list[Path]:
    """The results files among the given files and folders: every `*.jsonl` under a folder, sorted.

    Symlinks are not followed, so an artifact can't point the reader at a file elsewhere.
    """
    found: list[Path] = []
    for path in paths:
        if path.is_symlink():
            continue
        if path.is_dir():
            found += sorted(p for p in path.rglob("*.jsonl") if p.is_file() and not p.is_symlink())
        else:
            found.append(path)
    return found


def read_all(paths: Iterable[Path]) -> tuple[list[ResultsFile], list[Problem]]:
    """Every results file under the inputs, and the problems; a missing input is a problem."""
    files: list[ResultsFile] = []
    problems: list[Problem] = []
    inputs = list(paths)
    for path in inputs:
        if not path.exists() and not path.is_symlink():
            problems.append(Problem(path.as_posix(), 0, "no such results file or folder", "results-missing"))
    for path in collect(p for p in inputs if p.exists()):
        parsed, found = read(path)
        problems += found
        if parsed is not None:
            files.append(parsed)
    return files, problems
