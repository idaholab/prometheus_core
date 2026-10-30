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


class EnvFileError(ValueError):
    """A malformed line. The message has the line number, not the line."""


def _unquote(raw: str, lineno: int) -> str:
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


def parse(text: str) -> dict[str, str]:
    """Parse dotenv text. Multi-line quoted values are supported."""
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    values: dict[str, str] = {}
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        lineno = i + 1
        line = lines[i].strip()
        i += 1
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, rest = line.partition("=")
        key = key.strip()
        if not sep or not _KEY.fullmatch(key):
            raise EnvFileError(f"line {lineno}: expected KEY=value")
        rest = rest.lstrip()
        # A quoted value may continue on the following lines.
        if rest[:1] in ("'", '"') and rest.find(rest[0], 1) < 0:
            while i < len(lines) and rest.find(rest[0], 1) < 0:
                rest += "\n" + lines[i]
                i += 1
        values[key] = _unquote(rest, lineno)
    return values


def read(path: Path) -> dict[str, str]:
    return parse(path.read_text(encoding="utf-8"))


def _format(value: str) -> str:
    if value == "" or re.fullmatch(r"[\w@%+=:,./-]+", value):
        return value
    if "\n" in value or '"' in value or "$" in value or "#" in value or " " in value or "'" in value:
        if "'" not in value and "\n" not in value:
            return f"'{value}'"
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
    return value


def update_text(text: str, updates: dict[str, str]) -> str:
    """Return `text` with each key set in place; keys not present are appended."""
    lines = text.replace("\r\n", "\n").split("\n")
    pending = dict(updates)
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].lstrip()
        key = stripped.partition("=")[0].strip()
        if key in pending and not stripped.startswith("#"):
            lines[idx] = f"{key}={_format(pending.pop(key))}"
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
