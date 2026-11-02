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

"""specs/001-spec-format.md, through `speccheck lint` and `speccheck check`."""

from __future__ import annotations

import pytest

from tests.requirements.conftest import INDEX, Project, spec


@pytest.mark.covers("SPC-REQ-001-01")
def test_file_names_and_titles(project: Project):
    """A misnamed file and a title without the number are each reported where they are."""
    project.write("specs/000-index.md", INDEX + "- [002](002-other.md)\n")
    project.spec("")
    project.write("specs/002-other.md", spec("", number="002").replace("# 002 -", "# 2 -"))
    project.write("specs/Notes.md", "x")
    run = project.speccheck("lint")
    assert run.code == 1
    assert "specs/Notes.md: a spec file must be named NNN-short-name.md" in run.err
    assert "specs/002-other.md:1: the first line must be the title, `# 002 - <name>`" in run.err


@pytest.mark.covers("SPC-REQ-001-02")
def test_the_index_must_link_every_spec(project: Project):
    """A spec the index only mentions in prose is reported; a link in any markdown form lists it."""
    project.write("specs/000-index.md", "# Index\n\nSpec 002 is 002-other.md.\n\n| 001 | [x](./001-thing.md#a) |\n")
    project.spec("")
    project.spec("", number="002", name="002-other.md")
    run = project.speccheck("lint")
    assert run.code == 1
    assert run.err.splitlines()[0] == (
        "specs/000-index.md: the index doesn't link 002-other.md; list it as `[002](002-other.md)`"
    )
    (project.root / "specs" / "000-index.md").unlink()
    assert "needs a 000-index.md" in project.speccheck("lint").err
    project.write("speccheck.toml", 'specs = "specs"\nid-prefix = "T"\nrequire-index = false\n')
    assert project.speccheck("lint").code == 0


@pytest.mark.covers("SPC-REQ-001-03")
def test_the_status_line(project: Project):
    """Missing, unknown, repeated, and implemented with nothing in it, are all problems."""
    project.write("specs/001-thing.md", "# 001 - Thing\n\nstatus: done\nstatus: draft\n")
    run = project.speccheck("lint")
    assert "specs/001-thing.md:3: status must be one of draft, implemented, retired" in run.err
    assert "specs/001-thing.md:4: a second `status:` line; a spec has one" in run.err
    project.spec("", status="implemented")
    assert "specs/001-thing.md: an implemented spec needs at least one requirement" in project.speccheck("lint").err
    project.write("specs/001-thing.md", "# 001 - Thing\n")
    assert "specs/001-thing.md: missing the `status:` line" in project.speccheck("lint").err


@pytest.mark.covers("SPC-REQ-001-04")
def test_bullets_in_any_other_form_are_reported(project: Project):
    """Star, bold, nested, unprefixed and wrongly numbered bullets each get a problem with the form to write."""
    project.spec(
        "- T-REQ-001-01: Good. ⚠ untested\n* T-REQ-001-02: Star.\n- **T-REQ-001-03**: Bold.\n"
        "  - T-REQ-001-04: Nested.\n- REQ-001-05: No prefix.\n- T-REQ-002-01: Wrong spec."
    )
    run = project.speccheck("lint")
    assert run.err.count("a bullet must read `- T-REQ-NNN-XX: text` (or BEH)") == 4
    assert "T-REQ-002-01 belongs in spec 002" in run.err
    assert run.err.splitlines()[-1] == "speccheck lint: 1 specs, 2 requirements; 5 problems"


@pytest.mark.covers("SPC-REQ-001-05")
def test_ids_are_unique(project: Project):
    """The second use of an ID points at the first."""
    project.write("specs/000-index.md", INDEX + "- [002](002-other.md)\n")
    project.spec("- T-REQ-001-01: One. ⚠ untested")
    project.write("specs/002-other.md", spec("- T-REQ-001-01: Again. ⚠ untested", number="002"))
    run = project.speccheck("lint")
    assert "T-REQ-001-01 is also at specs/001-thing.md:7; IDs are unique" in run.err
    assert "specs/002-other.md:7:" in run.err


@pytest.mark.covers("SPC-REQ-001-06")
def test_markers_on_continuation_lines(project: Project):
    """A marker on a wrapped line counts, and both markers on one bullet is a problem."""
    project.spec(
        "- T-REQ-001-01: It MUST work\n  for a long while. ⚠ untested\n"
        "- T-REQ-001-02: Later\n  (planned: step 2)\n- T-REQ-001-03: Both. (planned: step 2) ⚠ untested"
    )
    run = project.speccheck("check", "--json")
    statuses = {r["id"]: r["status"] for r in run.json()["requirements"]}
    assert statuses == {"T-REQ-001-01": "untested", "T-REQ-001-02": "planned", "T-REQ-001-03": "planned"}
    assert [p["message"] for p in run.json()["problems"]] == [
        "T-REQ-001-03 is both planned and untested; keep one marker"
    ]


@pytest.mark.covers("SPC-REQ-001-07")
def test_retired_requirements(project: Project):
    """`Retired.` and `Retired:` retire a bullet, other wording doesn't, and a retired spec retires all of it."""
    project.write("specs/000-index.md", INDEX + "- [002](002-old.md)\n")
    project.spec("- T-REQ-001-01: Retired. Gone.\n- T-REQ-001-02: Retired: gone.\n- T-REQ-001-03: Retired later.")
    project.write("specs/002-old.md", spec("- T-REQ-002-01: It did.", status="retired", number="002"))
    statuses = {r["id"]: r["status"] for r in project.speccheck("check", "--json").json()["requirements"]}
    assert statuses == {
        "T-REQ-001-01": "retired",
        "T-REQ-001-02": "retired",
        "T-REQ-001-03": "unclaimed",
        "T-REQ-002-01": "retired",
    }


@pytest.mark.covers("SPC-REQ-001-08")
def test_fenced_examples_are_ignored(project: Project):
    """Bullets and header lines in a code block are neither requirements nor problems."""
    project.spec(
        "- T-REQ-001-01: Real. ⚠ untested\n\n```markdown\n- T-REQ-001-09: Example\n* bad\nstatus: retired\n```"
    )
    run = project.speccheck("lint", "--json")
    assert run.code == 0 and run.json()["requirement_count"] == 1


@pytest.mark.covers("SPC-REQ-001-09")
def test_the_old_checkers_lines_say_where_the_setting_went(project: Project):
    """`tests:` and `id-prefix:` point at the config."""
    project.write("specs/000-index.md", "# Index\n\nid-prefix: T\n\n" + INDEX)
    project.write("specs/001-thing.md", spec("").replace("status: draft", "status: draft\ntests: tests"))
    run = project.speccheck("lint")
    assert "specs/000-index.md:3: the `id-prefix:` line is gone; set `id-prefix` in the config instead" in run.err
    assert (
        "specs/001-thing.md:4: the `tests:` line is gone; say which producers may claim this spec in the config"
        in run.err
    )
