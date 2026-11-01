#!/usr/bin/env python3
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

"""Check a folder of SDD specs against the tests and CI jobs that cite them.

    speccheck.py --specs build/specs              # list problems, exit 1 if there are any
    speccheck.py --specs build/specs --report     # also print the evidence for every ID

Paths in a spec's `tests:` line are relative to `--root` (default: the current folder).
Standard library only, Python 3.10 or newer. The rules are in README.md next to this file.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

STATUSES = ("draft", "implemented", "retired")
"""The values a spec's `status:` line may take."""

ID_PATTERN = re.compile(r"\b(REQ|BEH)-(\d{3})-(\d{2})\b")
"""A full requirement or behavior ID, such as `REQ-003-04`."""

BULLET_START = re.compile(r"^- (REQ|BEH)\b")
"""A line that starts a requirement or behavior bullet, well-formed or not."""

BULLET = re.compile(r"^- ((?:REQ|BEH)-(\d{3})-\d{2}): \S")
"""A well-formed bullet: `- REQ-NNN-XX: text`."""

SPEC_FILE = re.compile(r"^(\d{3})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
"""A numbered spec's file name: `NNN-short-name.md`."""

UNTESTED = "⚠ untested"
"""The marker for a requirement that has no test yet."""

PLANNED = re.compile(r"\(planned: [^)]+\)")
"""The marker for a requirement a later plan step delivers, such as `(planned: step 3b)`."""

IMPLEMENTS = re.compile(r"\bImplements\b")
"""On a citing line, marks the citation as "this is the implementation", not a test of it."""

COVERS = re.compile(r"\bCovers\b")
"""In a workflow, marks a comment as a citation from a job that checks the requirement."""

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", "dist"}
"""Folders under a `tests:` path that are never read."""


@dataclass(frozen=True)
class Problem:
    """One rule a spec or a citation breaks."""

    path: str
    """The file, relative to the root."""
    line: int
    """The 1-based line number, or 0 for the whole file."""
    message: str
    """What is wrong and what to do about it."""

    def __str__(self) -> str:
        """`path:line: message`, the form editors and CI logs link."""
        return f"{self.path}:{self.line}: {self.message}" if self.line else f"{self.path}: {self.message}"


@dataclass
class Requirement:
    """One REQ or BEH bullet in a spec."""

    id: str
    """The ID, such as `REQ-003-04`."""
    spec: Spec
    """The spec it belongs to."""
    line: int
    """Where the bullet starts in the spec file."""
    text: str
    """The bullet's text after the ID, joined across its continuation lines."""

    @property
    def retired(self) -> bool:
        """Whether the bullet, or its whole spec, is retired."""
        return self.text.startswith("Retired") or self.spec.status == "retired"

    @property
    def untested(self) -> bool:
        """Whether the bullet carries `⚠ untested`."""
        return UNTESTED in self.text

    @property
    def planned(self) -> bool:
        """Whether the bullet carries `(planned: ...)`."""
        return PLANNED.search(self.text) is not None


@dataclass
class Spec:
    """One numbered spec file."""

    path: Path
    """The spec file."""
    number: str
    """Its three-digit number."""
    status: str = ""
    """Its `status:` value."""
    tests: list[Path] = field(default_factory=list)
    """The files and folders named on its `tests:` line, resolved against the root."""
    requirements: list[Requirement] = field(default_factory=list)
    """Its REQ and BEH bullets, in order."""


@dataclass(frozen=True)
class Citation:
    """One mention of an ID in a test file or a workflow."""

    id: str
    """The ID cited."""
    path: Path
    """The citing file."""
    line: int
    """The 1-based line of the mention."""
    kind: str
    """`test`, `ci` (a workflow job that checks it) or `implements`."""
    job: str = ""
    """For a workflow, the job the comment sits in."""


def rel(path: Path, root: Path) -> str:
    """`path` relative to `root` where possible, for messages."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def parse_spec(path: Path, root: Path, problems: list[Problem]) -> Spec:
    """Read one spec file's header lines and bullets, recording format problems."""
    number = path.name[:3]
    spec = Spec(path=path, number=number)
    name = rel(path, root)
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or not lines[0].startswith(f"# {number} "):
        problems.append(Problem(name, 1, f"the first line must be the title, `# {number} - <name>`"))

    current: Requirement | None = None
    seen_header = {"status": False, "tests": False}
    for number_, line in enumerate(lines, 1):
        for key in seen_header:
            if line.startswith(f"{key}:"):
                seen_header[key] = True
                value = line[len(key) + 1 :].strip()
                if key == "status":
                    spec.status = value
                    if value not in STATUSES:
                        problems.append(Problem(name, number_, f"status must be one of {', '.join(STATUSES)}"))
                else:
                    spec.tests = parse_tests_line(value, root, name, number_, problems)

        if BULLET_START.match(line):
            match = BULLET.match(line)
            if match is None:
                problems.append(Problem(name, number_, "a bullet must read `- REQ-NNN-XX: text` (or BEH)"))
                current = None
                continue
            if match.group(2) != number:
                problems.append(Problem(name, number_, f"{match.group(1)} belongs in spec {match.group(2)}"))
            current = Requirement(id=match.group(1), spec=spec, line=number_, text=line[match.end(1) + 2 :].strip())
            spec.requirements.append(current)
        elif current is not None and line.startswith("  ") and line.strip():
            current.text += " " + line.strip()
        else:
            current = None

    for key, seen in seen_header.items():
        if not seen:
            problems.append(Problem(name, 0, f"missing the `{key}:` line"))
    return spec


def parse_tests_line(value: str, root: Path, name: str, line: int, problems: list[Problem]) -> list[Path]:
    """The paths on a `tests:` line; `none` means none. A path that doesn't exist is a problem."""
    if value in ("", "none"):
        return []
    paths = []
    for item in (part.strip() for part in value.split(",")):
        path = root / item
        if not path.exists():
            problems.append(Problem(name, line, f"`tests:` names {item}, which doesn't exist under the root"))
        else:
            paths.append(path)
    return paths


def is_workflow(path: Path) -> bool:
    """Whether a file is a GitHub Actions workflow, whose citations must sit inside a job."""
    return path.suffix in (".yml", ".yaml") and path.parent.name == "workflows" and path.parent.parent.name == ".github"


def files_under(paths: Iterable[Path]) -> Iterator[Path]:
    """Every readable file under the given files and folders, each once, in a stable order."""
    seen: set[Path] = set()
    for path in paths:
        candidates = [path] if path.is_file() else sorted(path.rglob("*"))
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved in seen or not candidate.is_file():
                continue
            inside = candidate.relative_to(path).parts[:-1] if candidate != path else ()
            if any(part in SKIP_DIRS for part in inside):
                continue
            seen.add(resolved)
            yield candidate


def citations_in(path: Path, root: Path, problems: list[Problem]) -> list[Citation]:
    """Every ID mentioned in a file. A file that isn't text is skipped."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    if is_workflow(path):
        return workflow_citations(path, text, root, problems)
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        for match in ID_PATTERN.finditer(line):
            kind = "implements" if IMPLEMENTS.search(line, 0, match.start()) else "test"
            found.append(Citation(id=match.group(0), path=path, line=number, kind=kind))
    return found


def workflow_citations(path: Path, text: str, root: Path, problems: list[Problem]) -> list[Citation]:
    """IDs in a workflow: only in a `# Covers ...` or `# Implements ...` comment inside a job.

    Jobs are found by indentation under the top-level `jobs:` key, so no YAML parser is needed. A
    citation must be indented deeper than its job's key, so a renamed or deleted job can't keep one.
    """
    found = []
    name = rel(path, root)
    in_jobs = False
    job_indent: int | None = None
    job = ""
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if stripped and not stripped.startswith("#"):
            if indent == 0:
                in_jobs = stripped.startswith("jobs:")
                job = ""
                job_indent = None
            elif in_jobs and (job_indent is None or indent <= job_indent):
                job_indent = indent
                job = stripped.split(":", 1)[0].strip("'\"")
        ids = [match.group(0) for match in ID_PATTERN.finditer(line)]
        if not ids:
            continue
        comment = stripped.startswith("#")
        implements = comment and IMPLEMENTS.search(stripped) is not None
        covers = comment and COVERS.search(stripped) is not None
        if not (implements or covers):
            problems.append(
                Problem(name, number, "cite IDs in a workflow as a `# Covers ...` or `# Implements ...` comment")
            )
            continue
        if not job or job_indent is None or indent <= job_indent:
            problems.append(Problem(name, number, "a workflow citation must be a comment inside a job, below its key"))
            continue
        kind = "implements" if implements else "ci"
        found += [Citation(id=id_, path=path, line=number, kind=kind, job=job) for id_ in ids]
    return found


def load_specs(specs_dir: Path, root: Path, problems: list[Problem]) -> list[Spec]:
    """Every numbered spec in the folder, checked against the index."""
    specs = []
    index = specs_dir / "000-index.md"
    index_text = index.read_text(encoding="utf-8") if index.is_file() else None
    if index_text is None:
        problems.append(Problem(rel(index, root), 0, "the spec folder needs a 000-index.md"))
    for path in sorted(specs_dir.glob("*.md")):
        if path.name == "000-index.md":
            continue
        if not SPEC_FILE.match(path.name):
            problems.append(Problem(rel(path, root), 0, "a spec file must be named NNN-short-name.md"))
            continue
        if index_text is not None and not re.search(rf"\b{path.name[:3]}\b", index_text):
            problems.append(Problem(rel(index, root), 0, f"the index doesn't list {path.name[:3]} ({path.name})"))
        specs.append(parse_spec(path, root, problems))
    return specs


def check(specs_dir: Path, root: Path) -> tuple[list[Problem], dict[str, list[Citation]], list[Requirement]]:
    """Every problem, the citations of each known ID, and every requirement, in spec order."""
    problems: list[Problem] = []
    specs = load_specs(specs_dir, root, problems)

    requirements: dict[str, Requirement] = {}
    for spec in specs:
        for requirement in spec.requirements:
            if requirement.id in requirements:
                first = requirements[requirement.id]
                where = f"{rel(first.spec.path, root)}:{first.line}"
                problems.append(Problem(rel(spec.path, root), requirement.line, f"{requirement.id} is also at {where}"))
                continue
            requirements[requirement.id] = requirement
            if requirement.untested and requirement.planned:
                problems.append(
                    Problem(rel(spec.path, root), requirement.line, f"{requirement.id} is both planned and untested")
                )

    scanned = [path for spec in specs for path in spec.tests]
    cited: dict[str, list[Citation]] = {id_: [] for id_ in requirements}
    for path in files_under(scanned):
        for citation in citations_in(path, root, problems):
            where = rel(citation.path, root)
            requirement = requirements.get(citation.id)
            if requirement is None:
                problems.append(Problem(where, citation.line, f"{citation.id} isn't in any spec"))
            elif requirement.retired:
                problems.append(Problem(where, citation.line, f"{citation.id} is retired; cite what replaced it"))
            elif not any(is_within(citation.path, test) for test in requirement.spec.tests):
                spec_name = rel(requirement.spec.path, root)
                problems.append(
                    Problem(where, citation.line, f"{citation.id} is cited here, outside {spec_name}'s `tests:`")
                )
            else:
                cited[citation.id].append(citation)

    for requirement in requirements.values():
        if requirement.retired:
            continue
        name = rel(requirement.spec.path, root)
        evidence = cited[requirement.id]
        if evidence and requirement.untested:
            problems.append(Problem(name, requirement.line, f"{requirement.id} is cited, so remove `{UNTESTED}`"))
        elif evidence and requirement.planned:
            problems.append(
                Problem(name, requirement.line, f"{requirement.id} is cited, so remove its `(planned: ...)`")
            )
        elif not evidence and not (requirement.untested or requirement.planned):
            problems.append(
                Problem(name, requirement.line, f"{requirement.id} has no citing test; cite it or mark it `{UNTESTED}`")
            )

    ordered = [requirement for spec in specs for requirement in spec.requirements]
    return problems, cited, ordered


def is_within(path: Path, test: Path) -> bool:
    """Whether a file is, or sits under, a `tests:` path."""
    path, test = path.resolve(), test.resolve()
    return path == test or test in path.parents


def evidence_summary(requirement: Requirement, citations: list[Citation], root: Path) -> str:
    """One line describing what proves a requirement, for `--report`."""
    if requirement.retired:
        return "retired"
    if not citations:
        return "planned" if requirement.planned else "untested"
    parts = []
    for citation in citations:
        where = rel(citation.path, root)
        if citation.job:
            where += f" job {citation.job}"
        parts.append(f"{citation.kind}: {where}:{citation.line}")
    return "; ".join(parts)


def main(argv: list[str] | None = None) -> int:
    """Check the specs; exit 1 if any rule is broken."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--specs", type=Path, required=True, help="the folder holding 000-index.md and NNN-*.md")
    parser.add_argument("--root", type=Path, default=Path("."), help="what `tests:` paths are relative to")
    parser.add_argument("--report", action="store_true", help="also print the evidence for every ID")
    args = parser.parse_args(argv)
    if not args.specs.is_dir():
        parser.error(f"{args.specs} is not a folder")

    problems, cited, requirements = check(args.specs, args.root)
    if args.report:
        for requirement in requirements:
            print(f"{requirement.id}  {evidence_summary(requirement, cited.get(requirement.id, []), args.root)}")
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"speccheck: {len(problems)} problem{'s' if len(problems) != 1 else ''}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
