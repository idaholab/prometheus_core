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

"""Markdown that text from a spec or a results file can't break out of, and the only links allowed.

The report and the step summary both use these, so a string is escaped the same way in each.
"""

from __future__ import annotations

import re
from typing import Any

MAX_CELL = 200
"""The longest text kept in one table cell, after which it is cut with `…`."""
MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~&])")
"""Characters that mean something in markdown or HTML, escaped with a backslash."""


def escape(text: str, limit: int = MAX_CELL) -> str:
    """Text safe in a markdown table cell: one line, special characters escaped, at most `limit` characters."""
    text = " ".join(str(text).split())
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return MARKDOWN_SPECIAL.sub(r"\\\1", text)


def code(text: str, limit: int = MAX_CELL, *, in_table: bool) -> str:
    """Text as an inline code span: one line, capped, with no backtick to close the span early.

    Markdown takes everything in a code span literally, so backslash escapes would show. The one
    exception is a table cell, where GFM splits on `|` before it reads the span, so a `|` there is
    written `\\|` (which GFM turns back into `|`).
    """
    text = " ".join(str(text).replace("`", "").split())
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return f"`{text.replace('|', chr(92) + '|') if in_table else text}`"


PROSE_SPECIAL = re.compile(r"([\\\[\]<>*_~|&])")
"""Outside a code span, what can start a link, image, autolink, HTML, emphasis, strikethrough, an
entity or a table cell; each is escaped with a backslash."""
BLOCK_START = re.compile(r"^(\s*)([#>+=-]|\d+[.)])")
"""A line start markdown reads as a heading, quote, list or rule."""


def prose(text: str, limit: int = MAX_CELL, *, line_start: bool = False) -> str:
    """Text as markdown that can only be text: one line, capped, code spans kept as written.

    Outside code spans only PROSE_SPECIAL is escaped, so `.` and `-` read as they are. Spans are kept
    only when every backtick stands alone and they pair up: markdown matches a span by the length of
    its backtick run, so a run of two or more would pair differently from a split on single
    backticks and leave text unescaped. Otherwise every backtick is escaped, so no span can open.
    With `line_start`, the text starts its own line, so a leading BLOCK_START is escaped too.
    """
    text = " ".join(str(text).split())
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    if text.count("`") % 2 or "``" in text:
        out = PROSE_SPECIAL.sub(r"\\\1", text).replace("`", "\\`")
    else:
        parts = text.split("`")
        out = "`".join(part if n % 2 else PROSE_SPECIAL.sub(r"\\\1", part) for n, part in enumerate(parts))
    return BLOCK_START.sub(lambda m: m.group(1) + "\\" + m.group(2), out) if line_start else out


def anchor(heading: str) -> str:
    """GitHub's link anchor for a heading: lower case, punctuation and emoji dropped, spaces as `-`."""
    return re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")


PLAIN_PATH = re.compile(r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*$")
"""A repository path safe to put in a link: letters, digits, `_`, `.`, `-`, and `/` between parts."""


def source_url(base: str, path: str | None, line: int = 0) -> str:
    """`<base>/<path>#L<line>`, a file at this run's commit, when `base` is known and `path` is plain, else ""."""
    if not (base and path and PLAIN_PATH.fullmatch(path)) or ".." in path.split("/"):
        return ""
    return f"{base}/{path}" + (f"#L{line}" if line > 0 else "")


RUN_PATH = re.compile(r"/actions/runs/[1-9][0-9]{0,19}(?:/(?:attempts|job)/[1-9][0-9]{0,19})?")
"""What follows `<server>/<owner>/<repo>` in a run, run attempt or job URL."""
ARTIFACT_PATH = re.compile(r"/actions/runs/[1-9][0-9]{0,19}/artifacts/[1-9][0-9]{0,19}")
"""What follows `<server>/<owner>/<repo>` in an artifact URL, as `actions/upload-artifact` gives it."""


def _under(url: Any, base: str, path: re.Pattern[str]) -> str:
    """`url` when it is `base` followed by exactly `path`, else ""."""
    if not (base and isinstance(url, str) and url.startswith(base + "/")):
        return ""
    return url if path.fullmatch(url[len(base) :]) else ""


def safe_url(url: Any, base: str) -> str:
    """The URL when it is a run, attempt or job URL under `base`, this run's repository URL, else "".

    `base` comes from `ci.repository_url`; without one (outside CI) nothing is linked.
    """
    return _under(url, base, RUN_PATH)


def safe_artifact_url(url: Any, base: str) -> str:
    """The URL when it is an artifact URL under `base`, this run's repository URL, else ""."""
    return _under(url, base, ARTIFACT_PATH)
