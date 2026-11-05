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

"""Read a folder of SDD specs: the index, each spec's header, and its REQ and BEH bullets.

The format is described in the README. This module only reads specs; which tests claim which
requirement comes from results files (`results.py`), never from the spec text.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

OLD_UNTESTED = re.compile(r"⚠ untested\.?\Z")
"""The old format's marker for a requirement with no test yet, at the end of its text (SPC-REQ-001-09).

Only at the end, where specs put it, so a requirement can name the marker, as 001-09 does."""

OLD_PLANNED = re.compile(r"\(planned:.*\)\.?\Z", re.S)
"""The old format's marker for a requirement a later plan step delivers, such as `(planned: step 3b)`, at the end.

Matched from the last `(planned:`, so its step may hold parentheses, as the unimplemented suffix's reason may."""

OLD_RETIRED = re.compile(r"Retired([.:])")
"""How an old-format retired bullet's text starts: `Retired.` or `Retired:`, not "Retired later"."""

PREFIX = re.compile(r"[A-Z][A-Z0-9]*\Z")
"""A well-formed ID prefix: capital letters and digits, starting with a letter. Use `.match`; `\\Z`, unlike `$`, does not allow a trailing newline."""

SPEC_FILE = re.compile(r"^(\d{3})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
"""A numbered spec's file name: `NNN-short-name.md`."""

INDEX = "000-index.md"
"""The index file every spec folder has."""

SUFFIX_START = "(unimplemented"
"""Where the unimplemented suffix starts; the last one in a text is the one that may end it."""

SUFFIX = re.compile(r"\(unimplemented(?::(?P<reason>.*))?\)\.?", re.S)
"""The unimplemented suffix, `(unimplemented: <reason>)` with an optional full stop after it, matched with
`fullmatch` from SUFFIX_START. The reason may hold parentheses; it ends at the text's last `)`."""

UNIMPLEMENTED_EXAMPLE = "(unimplemented: <reason>)"
"""The suffix as messages show it."""

CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069]")
"""Characters that can end a line, drive a terminal or a CI log, or reorder how a line reads.

Newlines, escapes and other controls, the line and paragraph separators, and the bidi embedding,
override and isolate controls (U+202A to U+202E, U+2066 to U+2069), which can make a test name
show reversed or hide what follows it."""


def collapse(text: str) -> str:
    """`text` with each run of whitespace, line breaks included, made one space, and the ends trimmed."""
    return " ".join(text.split())


def comparable(text: str) -> str:
    """`text` as compared for sameness (SPC-REQ-001-10): the unimplemented suffix removed, whitespace collapsed,
    case ignored, one trailing full stop dropped."""
    text = collapse(split_suffix(collapse(text))[0]).casefold()
    return text[:-1].rstrip() if text.endswith(".") else text


def split_suffix(text: str) -> tuple[str, str | None]:
    """`text` without its unimplemented suffix, and the suffix's reason (None when it has no suffix).

    The suffix counts only at the very end, after one optional full stop. The reason is trimmed, and
    is "" for `(unimplemented)` or an empty reason, which is a problem the caller reports.
    """
    start = text.rfind(SUFFIX_START)
    match = SUFFIX.fullmatch(text.rstrip(), start) if start >= 0 else None
    if match is None:
        return text, None
    return text[:start].rstrip(), (match.group("reason") or "").strip()


def plain(text: str) -> str:
    """`text` as one line that no CI log acts on: control characters and log commands written out.

    Each control character is written as an escape, such as `\\n` or `\\x1b`, so the text stays on
    one line. File names and results files are not trusted, and a GitHub Actions log acts on a
    line that starts with `::` (after spaces), as in `::error::x`, and on `##[` anywhere in a line,
    as in `##[error]x`. So a leading `:` is written `\\x3a` and the `[` of `##[` is written `\\x5b`.
    """
    text = CONTROL.sub(lambda match: ascii(match.group(0))[1:-1], text).replace("##[", "##\\x5b")
    body = text.lstrip()
    if body.startswith("::"):
        text = text[: len(text) - len(body)] + "\\x3a" + body[1:]
    return text


class Syntax:
    """The ID patterns of one spec folder, whose IDs may carry a prefix such as `SPC-REQ-003-04`.

    A prefix keeps one folder's IDs apart from another's, since both number their specs from 001.
    With a prefix, a bare `REQ-003-04` is not one of this folder's IDs; without one, a prefixed ID
    is not either.
    """

    def __init__(self, prefix: str = "") -> None:
        """Compile the patterns for IDs written with `prefix` (none for bare IDs)."""
        self.head = f"{prefix}-" if prefix else ""
        """What comes before `REQ` or `BEH` in an ID, such as `SPC-`."""
        head = re.escape(self.head)
        self.id = re.compile(rf"{head}(?:REQ|BEH)-(?P<number>\d{{3}})-\d{{2}}")
        """A full ID, matched against a whole string with `fullmatch`."""
        self.bullet_start = re.compile(rf"^\s*[-*+]\s+[*_`]*(?:{head})?(?:REQ|BEH)\b")
        """A line that starts a requirement or behavior bullet in any list style, well-formed or not.

        `* REQ-...`, `- **REQ-...**` and an indented `  - REQ-...` all count, so none of them can
        slip past the checker as ordinary text.
        """
        self.bullet = re.compile(rf"^- (?P<id>{head}(?:REQ|BEH)-(?P<number>\d{{3}})-\d{{2}}): \S")
        """A well-formed bullet: `- <prefix>REQ-NNN-XX: text`."""

    def example(self) -> str:
        """An example ID in this folder's form, for messages."""
        return f"{self.head}REQ-001-01"


@dataclass(frozen=True)
class Problem:
    """One rule that a spec, a config, a results file or a claim breaks."""

    path: str
    """The file, relative to where speccheck runs where possible."""
    line: int
    """The 1-based line number, or 0 when there is none (the problem is the whole file or the config)."""
    message: str
    """What is wrong and what to do about it."""
    code: str = "problem"
    """A stable kebab-case name for the kind of problem, such as `unclaimed`; it does not change with the wording."""

    def __str__(self) -> str:
        """`path:line: message`, the form editors and CI logs link, with control characters written out."""
        text = f"{self.path}:{self.line}: {self.message}" if self.line else f"{self.path}: {self.message}"
        return plain(text)

    def to_json(self) -> dict:
        """The problem as a JSON object (the text is left as is; JSON escapes it)."""
        return {"path": self.path, "line": self.line, "message": self.message, "code": self.code}


@dataclass
class Requirement:
    """One REQ or BEH bullet in a spec."""

    id: str
    """The ID, such as `SPC-REQ-003-04`."""
    spec: Spec
    """The spec it belongs to."""
    line: int
    """Where the bullet starts in the spec file."""
    text: str
    """The bullet's text after the ID, joined across its continuation lines, without the unimplemented suffix."""
    reason: str | None = None
    """Why it isn't implemented yet, from its `(unimplemented: <reason>)` suffix; None when it has none."""

    @property
    def unimplemented(self) -> bool:
        """Whether the bullet ends with the unimplemented suffix."""
        return self.reason is not None


@dataclass
class Spec:
    """One numbered spec file."""

    path: Path
    """The spec file."""
    number: str
    """Its three-digit number."""
    title: str = ""
    """Its title, from the first line."""
    purpose: str = ""
    """Its `## Purpose` section's text, joined onto one line, or "" when it has none."""
    requirements: list[Requirement] = field(default_factory=list)
    """Its REQ and BEH bullets, in order."""
    removed: list[str] = field(default_factory=list)
    """The IDs its `removed:` line lists, in order, each once."""
    removed_line: int = 0
    """The line of its `removed:` line, or 0 when it has none."""


@dataclass
class SpecSet:
    """Every spec of one folder, and the problems found reading them."""

    specs: list[Spec]
    """The specs, in file name order."""
    requirements: dict[str, Requirement]
    """Every requirement by ID, in spec order; a duplicate ID keeps the first."""
    problems: list[Problem]
    """Format problems, as `lint` reports them."""
    syntax: Syntax
    """The folder's ID patterns."""
    removed: dict[str, str] = field(default_factory=dict)
    """Every ID a spec's `removed:` line lists, to the number of the spec it was removed from."""
    removed_specs: list[str] = field(default_factory=list)
    """The spec numbers the index's `removed:` line lists."""

    def removed_from(self, claimed: str, number: str) -> str:
        """Why the ID `claimed`, of spec `number`, can't be claimed because it was removed, or ""."""
        if claimed in self.removed:
            return f"{claimed} was removed from spec {self.removed[claimed]}; delete the claim"
        if number in self.removed_specs:
            return f"{claimed} is in spec {number}, which was removed; delete the claim"
        return ""


def old_forms(text: str, id_: str) -> list[tuple[str, str]]:
    """The old format's markers on a requirement's text, each with what replaces it (SPC-REQ-001-09)."""
    replace = f"end it with `{UNIMPLEMENTED_EXAMPLE}` if a plan delivers it later, or give it a test"
    found = []
    if OLD_UNTESTED.search(text):
        found.append(("`⚠ untested`, which is gone", replace))
    start = text.rfind("(planned:")
    if start >= 0 and OLD_PLANNED.fullmatch(text, start):
        found.append(("`(planned: ...)`, which is gone", replace))
    retired = OLD_RETIRED.match(text)
    if retired:
        old = f"`Retired{retired.group(1)}`, which is gone"
        found.append((old, f"delete the requirement and list {id_} in its spec's `removed:` line"))
    return found


def continues(line: str) -> bool:
    """Whether `line` continues the bullet or header line above it: two or more spaces, then text (SPC-REQ-001-06)."""
    return line.startswith("  ") and bool(line.strip())


def header_lines(lines: list[str], key: str) -> list[tuple[int, str]]:
    """Each `key:` line above the first `##` outside a fence, with its value joined across continuation lines.

    Returns `(line number, value)` pairs, the value trimmed, so a caller can report a repeat at its line.
    """
    found: list[tuple[int, str]] = []
    in_fence = False
    current: list[str] | None = None
    for line_number, line in enumerate(lines, 1):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence, current = not in_fence, None
            continue
        if in_fence:
            continue
        if line.startswith("## "):
            break
        if current is not None and continues(line):
            current.append(line.strip())
            found[-1] = (found[-1][0], " ".join(current))
            continue
        current = None
        if line.startswith(f"{key}:"):
            current = [line[len(key) + 1 :].strip()]
            found.append((line_number, current[0]))
    return found


def listed(value: str) -> list[str]:
    """The comma-separated items of a header value, trimmed, empty ones dropped."""
    return [item.strip() for item in value.split(",") if item.strip()]


def what_is_wrong(line: str, syntax: Syntax) -> str:
    """Say which way a malformed bullet line differs from the form, and echo its first 60 characters."""
    stripped = line.strip()
    if line[0].isspace():
        reason = "an indented bullet"
    elif stripped[0] != "-":
        reason = f"`{stripped[0]}` where `-` belongs"
    elif re.match(r"^-\s+[*_`]", line):
        reason = "the ID wrapped in markup"
    elif syntax.head and not re.match(rf"^-\s+{re.escape(syntax.head)}", line):
        reason = f"an ID without the `{syntax.head}` prefix"
    elif re.match(rf"^- {re.escape(syntax.head)}(?:REQ|BEH)-\d{{3}}-\d{{2}}(?!\d)", line):
        reason = "no `: ` and text after the ID"
    else:
        reason = "an ID that is not NNN-XX"
    shown = stripped[:60] + ("…" if len(stripped) > 60 else "")
    return f"{reason}: `{shown}`"


def rel(path: Path, root: Path) -> str:
    """`path` relative to `root` where possible, for messages."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def parse_spec(path: Path, root: Path, syntax: Syntax, problems: list[Problem]) -> Spec:
    """Read one spec file's header line and bullets, recording format problems."""
    number = path.name[:3]
    spec = Spec(path=path, number=number)
    name = rel(path, root)
    lines = path.read_text(encoding="utf-8").splitlines()
    title = re.match(rf"# {number} - (\S.*)", lines[0]) if lines else None
    if title is None:
        problems.append(Problem(name, 1, f"the first line must be the title, `# {number} - <name>`", "spec-title"))
    else:
        spec.title = title.group(1).strip()

    current: Requirement | None = None
    section = ""
    purpose: list[str] = []
    in_header = True
    in_fence = False
    for line_number, line in enumerate(lines, 1):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            current = None
            continue
        if in_fence:
            continue
        if line.startswith("## "):
            in_header = False
            section = line[3:].strip()
            current = None
            continue
        if section == "Purpose" and line.strip():
            purpose.append(line.strip())
        if in_header and line.startswith("status:"):
            message = (
                "the `status:` line is gone; delete it (a planned requirement ends with `(unimplemented: <reason>)`)"
            )
            problems.append(Problem(name, line_number, message, "status-line-gone"))

        if syntax.bullet_start.match(line):
            match = syntax.bullet.match(line)
            if match is None:
                message = f"a bullet must read `- {syntax.head}REQ-NNN-XX: text` (or BEH); found {what_is_wrong(line, syntax)}"
                problems.append(Problem(name, line_number, message, "bullet-malformed"))
                current = None
                continue
            if match.group("number") != number:
                problems.append(
                    Problem(
                        name,
                        line_number,
                        f"{match.group('id')} belongs in spec {match.group('number')}",
                        "bullet-wrong-spec",
                    )
                )
            current = Requirement(
                id=match.group("id"), spec=spec, line=line_number, text=line[match.end("id") + 2 :].strip()
            )
            spec.requirements.append(current)
        elif current is not None and continues(line):
            current.text += " " + line.strip()
        else:
            current = None

    spec.purpose = " ".join(purpose)
    for requirement in spec.requirements:
        requirement.text, requirement.reason = split_suffix(requirement.text)
        if requirement.reason == "":
            message = f"{requirement.id} needs a reason: write `{UNIMPLEMENTED_EXAMPLE}`"
            problems.append(Problem(name, requirement.line, message, "reason-missing"))
        for old, fix in old_forms(requirement.text, requirement.id):
            problems.append(Problem(name, requirement.line, f"{requirement.id} has {old}; {fix}", "old-marker"))
    found = header_lines(lines, "removed")
    example = f"{syntax.head}REQ-{number}-01"

    def wrong(item: str) -> str:
        """Why `item` can't be one of this spec's removed IDs, or ""."""
        match = syntax.id.fullmatch(item)
        if match is None or match.group("number") != number:
            return f"`{item}` in `removed:` isn't an ID of this spec; they read like `{example}`"
        return ""

    spec.removed = removed_list(found, wrong, name, problems)
    spec.removed_line = found[0][0] if found else 0
    return spec


def removed_list(
    found: list[tuple[int, str]], wrong: Callable[[str], str], name: str, problems: list[Problem]
) -> list[str]:
    """The items a `removed:` line lists, each once (SPC-REQ-001-11, 001-12).

    `wrong` says why an item can't be listed, or "". A second `removed:` line, an item `wrong`
    refuses, and an item listed twice are each a problem in `name`, and are left out.
    """
    items: list[str] = []
    for line_number, _ in found[1:]:
        message = "a second `removed:` line; list everything on the first"
        problems.append(Problem(name, line_number, message, "removed-repeated"))
    for line_number, value in found[:1]:
        for item in listed(value):
            why = wrong(item)
            if why:
                problems.append(Problem(name, line_number, why, "removed-invalid"))
            elif item in items:
                problems.append(Problem(name, line_number, f"{item} is listed twice in `removed:`", "removed-repeated"))
            else:
                items.append(item)
    return items


def spec_number_problem(item: str) -> str:
    """Why `item` can't be in the index's `removed:` line, or "": spec numbers are three digits, not `000`."""
    if item == "000":
        return "`000` in `removed:` is the index, not a spec"
    if re.fullmatch(r"\d{3}", item):
        return ""
    return f"`{item}` in `removed:` isn't a spec number; they are three digits, like `007`"


def links_to(index_text: str, name: str) -> bool:
    """Whether the index has a Markdown link to the spec file, such as `[001](001-thing.md)`.

    A mention of the spec's number or name in prose is not a listing, so a spec can't be left out
    of the index and still pass because another paragraph happens to say "001".
    """
    return re.search(rf"\]\((?:\./)?{re.escape(name)}(?:#[^)]*)?\)", index_text) is not None


def load(specs_dir: Path, root: Path, prefix: str = "", require_index: bool = True) -> SpecSet:
    """Read every spec in the folder and check the format; `root` is what paths in messages are relative to."""
    problems: list[Problem] = []
    syntax = Syntax(prefix)
    index = specs_dir / INDEX
    index_text = index.read_text(encoding="utf-8") if index.is_file() else None
    if index_text is None and require_index:
        problems.append(
            Problem(rel(index, root), 0, f"the spec folder needs a {INDEX} that links every spec", "index-missing")
        )
    removed_specs: list[str] = []
    if index_text is not None:
        found = header_lines(index_text.splitlines(), "removed")
        removed_specs = removed_list(found, spec_number_problem, rel(index, root), problems)

    specs = []
    for path in sorted(specs_dir.glob("*.md")):
        if path.name == INDEX:
            continue
        if not SPEC_FILE.match(path.name):
            problems.append(
                Problem(rel(path, root), 0, "a spec file must be named NNN-short-name.md", "spec-file-name")
            )
            continue
        if path.name[:3] in removed_specs:
            message = f"spec {path.name[:3]} is listed as removed in {INDEX}; delete the file or the listing"
            problems.append(Problem(rel(path, root), 0, message, "spec-removed"))
            continue
        if require_index and index_text is not None and not links_to(index_text, path.name):
            message = f"the index doesn't link {path.name}; list it as `[{path.name[:3]}]({path.name})`"
            problems.append(Problem(rel(index, root), 0, message, "index-link-missing"))
        specs.append(parse_spec(path, root, syntax, problems))

    requirements: dict[str, Requirement] = {}
    texts: dict[str, Requirement] = {}
    for spec in specs:
        name = rel(spec.path, root)
        if not spec.requirements:
            message = (
                f"a spec needs at least one requirement; if it has none left, delete it and list "
                f"{spec.number} in {INDEX}'s `removed:` line"
            )
            problems.append(Problem(name, 0, message, "spec-empty"))
        for requirement in spec.requirements:
            if requirement.id in requirements:
                first = requirements[requirement.id]
                where = f"{rel(first.spec.path, root)}:{first.line}"
                problems.append(
                    Problem(
                        name, requirement.line, f"{requirement.id} is also at {where}; IDs are unique", "id-duplicate"
                    )
                )
                continue
            requirements[requirement.id] = requirement
            same = texts.setdefault(comparable(requirement.text), requirement)
            if same is not requirement:
                where = f"{rel(same.spec.path, root)}:{same.line}"
                message = (
                    f"{requirement.id} has the same text as {same.id} at {where}; each requirement says something new"
                )
                problems.append(Problem(name, requirement.line, message, "text-duplicate"))

    removed: dict[str, str] = {}
    for spec in specs:
        for id_ in spec.removed:
            removed[id_] = spec.number
            if id_ in requirements:
                again = requirements[id_]
                where = f"{rel(again.spec.path, root)}:{again.line}"
                message = f"{id_} is listed in `removed:` but is a requirement at {where}; a removed ID is never reused"
                problems.append(Problem(rel(spec.path, root), spec.removed_line, message, "removed-reused"))
    return SpecSet(
        specs=specs,
        requirements=requirements,
        problems=problems,
        syntax=syntax,
        removed=removed,
        removed_specs=removed_specs,
    )
