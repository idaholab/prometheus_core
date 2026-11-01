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

"""Read and update dotenv files (`.env`, `.env.example`).

Dotenv rules: quotes are stripped, `$` is not expanded, `\\r` and a BOM are
ignored. Writes are atomic and keep the file's mode; new files are 0600.
Errors name the line number, never its text (it may hold a secret).
"""

from __future__ import annotations

import contextlib
import os
import re
import stat
import tempfile
from pathlib import Path

_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*")
"""Matches a valid variable name."""


class EnvFileError(ValueError):
    """A malformed line. The message has the line number, not the line."""


def _unquote(raw: str, lineno: int) -> str:
    """Strip the quotes from a value, or a trailing comment from an unquoted one."""
    raw = raw.strip()
    if raw[:1] in ("'", '"'):
        quote = raw[0]
        end = raw.find(quote, 1)
        while quote == '"' and end > 0 and raw[end - 1] == "\\":
            end = raw.find(quote, end + 1)
        if end < 0:
            raise EnvFileError(f"line {lineno}: unterminated quote")
        value = raw[1:end]
        return value.replace('\\"', '"').replace("\\n", "\n") if quote == '"' else value
    # Unquoted: a ` #` starts a comment.
    return re.split(r"\s+#", raw, maxsplit=1)[0].strip()


def _scan(lines: list[str]) -> list[tuple[str, int, int, str]]:
    """Each assignment as (key, first line index, index after its last line, raw value), in file order.

    A quoted value may continue on the following lines, so an assignment can span several.
    """
    found: list[tuple[str, int, int, str]] = []
    i = 0
    while i < len(lines):
        start = i
        line = lines[i].strip()
        i += 1
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, rest = line.partition("=")
        key = key.strip()
        if not sep or not _KEY.fullmatch(key):
            raise EnvFileError(f"line {start + 1}: expected KEY=value")
        rest = rest.lstrip()
        if rest[:1] in ("'", '"') and rest.find(rest[0], 1) < 0:
            while i < len(lines) and rest.find(rest[0], 1) < 0:
                rest += "\n" + lines[i]
                i += 1
        found.append((key, start, i, rest))
    return found


def parse(text: str) -> dict[str, str]:
    """Parse dotenv text. Multi-line quoted values are supported; for a repeated key the last one wins."""
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    return {key: _unquote(rest, start + 1) for key, start, _, rest in _scan(text.split("\n"))}


_ONE_LINER = re.compile(r'^#\s*python3 -c "(.+)"\s*$')
"""A comment line holding the `python3 -c "..."` that generates a secret."""
_ASSIGNMENT = re.compile(r"^([A-Z][A-Z0-9_]*)=")
"""A `KEY=` line in `.env.example`."""


def generators(example: str) -> dict[str, str]:
    """Map each variable to the one-liner in the comment block directly above it."""
    found: dict[str, str] = {}
    pending: str | None = None
    for line in example.splitlines():
        if match := _ONE_LINER.match(line):
            pending = match.group(1)
        elif match := _ASSIGNMENT.match(line):
            if pending:
                found[match.group(1)] = pending
            pending = None
        elif not line.startswith("#"):
            pending = None
    return found


def example_keys(example: str) -> list[str]:
    """The keys `.env.example` sets with an active line (not a commented-out default), in file order."""
    return [match.group(1) for line in example.splitlines() if (match := _ASSIGNMENT.match(line))]


def missing_keys(example: str, current: dict[str, str]) -> list[str]:
    """The keys `.env.example` sets that `.env` lacks, so a new key reaches an existing `.env`."""
    return [key for key in example_keys(example) if key not in current]


def read(path: Path) -> dict[str, str]:
    """Parse the dotenv file at `path`; a file that can't be read as UTF-8 text is an `EnvFileError`.

    The message says why in general terms only: a decode error names the offset of the bad byte.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise EnvFileError("the file is not valid UTF-8 text") from None
    except OSError as exc:
        raise EnvFileError(f"the file can't be read ({exc.strerror or type(exc).__name__})") from None
    return parse(text)


def _format(value: str) -> str:
    """Quote a value for `.env` only if it needs it."""
    if value == "" or re.fullmatch(r"[\w@%+=:,./-]+", value):
        return value
    if "\n" in value or '"' in value or "$" in value or "#" in value or " " in value or "'" in value:
        if "'" not in value and "\n" not in value:
            return f"'{value}'"
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
    return value


def update_text(text: str, updates: dict[str, str]) -> str:
    """Return `text` with each key set in place; keys not present are appended.

    A key is replaced where `parse` reads it: its last assignment, over every line of a multi-line
    value. Earlier duplicates are left alone. A malformed file raises `EnvFileError` rather than
    being written over, and so does a key `parse` would reject, which would make the file unreadable.
    """
    text = text.lstrip("﻿").replace("\r\n", "\n")
    parse(text)
    if any(not _KEY.fullmatch(key) for key in updates):
        raise EnvFileError("a key to write is not a valid variable name")
    lines = text.split("\n")
    pending = dict(updates)
    last = {key: (start, end) for key, start, end, _ in _scan(lines)}
    # Bottom up, so replacing a multi-line value doesn't shift the lines still to edit.
    for key, (start, end) in sorted(last.items(), key=lambda item: -item[1][0]):
        if key in pending:
            lines[start:end] = [f"{key}={_format(pending.pop(key))}"]
    if pending:
        if lines and lines[-1] == "":
            lines.pop()
        lines.extend(f"{k}={_format(v)}" for k, v in pending.items())
        lines.append("")
    return "\n".join(lines)


def write_atomic(path: Path, text: str) -> None:
    """Write `text` to `path` atomically, keeping the target's mode (new files: 0600).

    A symlinked `path` is written through to its target.
    """
    target = Path(os.path.realpath(path))
    mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o600
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def update(path: Path, updates: dict[str, str]) -> None:
    """Set keys in the file at `path`, creating it (0600) if needed."""
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    write_atomic(path, update_text(current, updates))
