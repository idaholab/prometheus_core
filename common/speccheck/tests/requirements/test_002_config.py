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

"""specs/002-config.md, through the command line."""

from __future__ import annotations

import pytest

from tests.requirements.conftest import CONFIG, Project


@pytest.mark.covers(
    "SPC-REQ-002-01",
    "lint reads --config over speccheck.toml, falls back to [tool.speccheck] in pyproject.toml, and exits 2 with what to pass when neither exists",
)
def test_which_config_is_used(project: Project):
    """`--config` first, then speccheck.toml, then [tool.speccheck]; none is exit 2 with what to pass."""
    project.spec("- T-REQ-001-01: One. (unimplemented: later)")
    project.write("other.toml", 'specs = "specs"\nid-prefix = "OTHER"\n')
    # T-REQ-001-01 is not a bullet in a folder whose prefix is OTHER, so other.toml sees no requirements (spec-empty)
    other = project.speccheck("lint", "--config", "other.toml")
    assert other.err.splitlines()[-1] == "speccheck lint: 1 specs, 0 requirements; 1 problem"
    assert project.speccheck("lint").out == "speccheck lint: 1 specs, 1 requirement\n"
    assert project.speccheck("lint").code == 0
    (project.root / "speccheck.toml").unlink()
    project.write("pyproject.toml", '[tool.speccheck]\nspecs = "specs"\nid-prefix = "T"\n')
    assert project.speccheck("lint").code == 0
    (project.root / "pyproject.toml").unlink()
    run = project.speccheck("lint")
    assert run.code == 2
    assert "no speccheck.toml, and no [tool.speccheck] in pyproject.toml, here; pass --config PATH" in run.err


@pytest.mark.covers(
    "SPC-REQ-002-01",
    "with speccheck.toml (prefix T) and a pyproject.toml with [tool.speccheck] (prefix OTHER) side by side, lint reads speccheck.toml's requirement, and with only the pyproject it reads the pyproject's",
)
def test_speccheck_toml_wins_over_pyproject(project: Project):
    """Both exist with different prefixes, so the count of requirements says which one was used."""
    project.spec("- T-REQ-001-01: One. (unimplemented: later)")
    project.write("pyproject.toml", '[tool.speccheck]\nspecs = "specs"\nid-prefix = "OTHER"\n')
    assert project.speccheck("lint").out == "speccheck lint: 1 specs, 1 requirement\n"
    (project.root / "speccheck.toml").unlink()
    # Only the pyproject is left, and its prefix OTHER sees no bullet in a folder written for T
    assert project.speccheck("lint").err.splitlines()[-1] == "speccheck lint: 1 specs, 0 requirements; 1 problem"


@pytest.mark.covers(
    "SPC-REQ-002-01",
    "a pyproject.toml with only [tool.other] and no speccheck.toml exits 2 saying no config was found and to pass --config",
)
def test_a_pyproject_without_a_speccheck_table_is_not_a_config(project: Project):
    """The file exists, but it isn't speccheck's, so it falls through to the error."""
    (project.root / "speccheck.toml").unlink()
    project.write("pyproject.toml", '[tool.other]\nspecs = "specs"\n')
    run = project.speccheck("lint")
    assert run.code == 2
    assert "no speccheck.toml, and no [tool.speccheck] in pyproject.toml, here; pass --config PATH" in run.err


@pytest.mark.covers(
    "SPC-REQ-002-02",
    'a config in sub/ with specs = "specs" reads sub/specs and not the parent folder\'s own specs when run from the parent, and a `specs` naming a missing folder exits 2',
)
def test_paths_are_relative_to_the_config(project: Project):
    """A config in a subfolder finds its spec folder next to it, from anywhere; a missing folder is exit 2."""
    project.spec(
        "- T-REQ-001-01: Beside the run. (unimplemented: later)\n- T-REQ-001-02: Beside the run too. (unimplemented: later)"
    )
    project.write("sub/speccheck.toml", 'specs = "specs"\nid-prefix = "T"\n')
    project.write("sub/specs/000-index.md", "# Index\n\n- [001](001-thing.md)\n")
    project.write(
        "sub/specs/001-thing.md",
        "# 001 - Thing\n\nsources: tests\n\n## Requirements\n\n- T-REQ-001-01: Beside the config. (unimplemented: later)\n",
    )
    run = project.speccheck("lint", "--config", "sub/speccheck.toml", "--json")
    assert run.code == 0 and run.json()["requirement_count"] == 1
    project.write("sub/speccheck.toml", 'specs = "gone"\n')
    run = project.speccheck("lint", "--config", "sub/speccheck.toml")
    assert run.code == 2 and "`specs` is 'gone', which is not a folder" in run.err


@pytest.mark.parametrize(
    "config",
    [
        pytest.param(
            'id-prefix = "T"\n',
            marks=pytest.mark.covers(
                "SPC-REQ-002-02", "a config with no `specs` key at all exits 2 asking for the spec folder's name"
            ),
            id="missing",
        ),
        pytest.param(
            'specs = ""\nid-prefix = "T"\n',
            marks=pytest.mark.covers(
                "SPC-REQ-002-02", "a config whose `specs` is an empty string exits 2 asking for the spec folder's name"
            ),
            id="empty",
        ),
        pytest.param(
            'specs = 3\nid-prefix = "T"\n',
            marks=pytest.mark.covers(
                "SPC-REQ-002-02", "a config whose `specs` is a number exits 2 asking for the spec folder's name"
            ),
            id="not-a-string",
        ),
        pytest.param(
            'specs = ["specs"]\nid-prefix = "T"\n',
            marks=pytest.mark.covers(
                "SPC-REQ-002-02", "a config whose `specs` is a list holding the folder's name exits 2 the same way"
            ),
            id="a-list",
        ),
    ],
)
def test_specs_must_name_the_spec_folder(project: Project, config: str):
    """Without a usable `specs` there is no folder to read, which is exit 2 and not a crash or an empty run."""
    project.write("speccheck.toml", config)
    run = project.speccheck("lint")
    assert run.code == 2
    assert "speccheck.toml: `specs` must name the spec folder" in run.err, run.err


@pytest.mark.parametrize(
    ("extra", "key"),
    [
        pytest.param(
            "specz = 1\n",
            "specz",
            marks=pytest.mark.covers(
                "SPC-REQ-002-03", "an unknown top-level key exits 2 naming speccheck.toml and the key"
            ),
            id="top-level",
        ),
        pytest.param(
            "[producers.docker]\nworkflow = []\n",
            "producers.docker.workflow",
            marks=pytest.mark.covers(
                "SPC-REQ-002-03", "a misspelt key in a [producers.docker] table is named with its table"
            ),
            id="producer",
        ),
        pytest.param(
            '[ci.job]\ncovers = { "T-REQ-001-01" = "the job" }\ncover = 1\n',
            "ci.job.cover",
            marks=pytest.mark.covers(
                "SPC-REQ-002-03", "a stray key beside covers in a [ci.job] table is named with its table"
            ),
            id="ci-job",
        ),
        pytest.param(
            "[report]\nname = 1\n",
            "report.name",
            marks=pytest.mark.covers("SPC-REQ-002-03", "an unknown key in the [report] table is named as report.name"),
            id="report",
        ),
    ],
)
def test_unknown_keys_name_the_file_and_key(project: Project, extra: str, key: str):
    """At the top level and in every table."""
    top, tables = (extra, "") if not extra.startswith("[") else ("", extra)
    project.write("speccheck.toml", top + CONFIG + tables)
    run = project.speccheck("lint")
    assert run.code == 2 and f"speccheck.toml: unknown key `{key}`" in run.err


@pytest.mark.covers(
    "SPC-REQ-002-02",
    "a config in sub/ whose specs folder exists only beside it reads that folder's requirement from the parent folder, and a `specs` naming a file exits 2",
)
def test_the_specs_folder_is_found_next_to_the_config_not_the_current_folder(project: Project):
    """The folder run from has its own `specs/` with another requirement; only the one beside the config may be read."""
    project.spec(
        "- T-REQ-001-01: Beside the run. (unimplemented: later)\n- T-REQ-001-02: Beside the run too. (unimplemented: later)"
    )
    project.write("sub/speccheck.toml", 'specs = "docs"\nid-prefix = "T"\n')
    project.write("sub/docs/000-index.md", "# Index\n\n- [001](001-thing.md)\n")
    project.write(
        "sub/docs/001-thing.md",
        "# 001 - Thing\n\nsources: tests\n\n## Requirements\n\n- T-REQ-001-01: Beside the config. (unimplemented: later)\n",
    )
    run = project.speccheck("lint", "--config", "sub/speccheck.toml", "--json")
    assert run.code == 0 and run.json()["requirement_count"] == 1
    # `specs` must be a folder, not a file
    project.write("sub/speccheck.toml", 'specs = "docs/000-index.md"\n')
    run = project.speccheck("lint", "--config", "sub/speccheck.toml")
    assert run.code == 2 and "which is not a folder" in run.err


@pytest.mark.covers(
    "SPC-REQ-002-03",
    "an unknown key under [tool.speccheck] in pyproject.toml is named by its full dotted path",
)
def test_unknown_keys_in_pyproject_name_the_dotted_key(project: Project):
    """In a pyproject.toml, the key's full path."""
    (project.root / "speccheck.toml").unlink()
    project.write("pyproject.toml", '[tool.speccheck]\nspecs = "specs"\nprefix = "T"\n')
    assert "pyproject.toml: unknown key `tool.speccheck.prefix`" in project.speccheck("lint").err


@pytest.mark.covers(
    "SPC-REQ-002-04",
    "lowercase, hyphenated and digit-first prefixes exit 2, and an empty prefix reads bare REQ-001-01 bullets",
)
def test_the_prefix(project: Project):
    """A malformed prefix is exit 2; an empty one means bare IDs."""
    for bad in ("spc", "S-PC", "1SPC", "SPC\\n", "SPC "):
        project.write("speccheck.toml", f'specs = "specs"\nid-prefix = "{bad}"\n')
        run = project.speccheck("lint")
        assert run.code == 2 and "`id-prefix` must be capital letters and digits" in run.err, bad
    for good in ("S2", "A1B", "SPC9"):
        project.write("speccheck.toml", f'specs = "specs"\nid-prefix = "{good}"\n')
        project.spec(f"- {good}-REQ-001-01: Digits are fine. (unimplemented: later)")
        assert project.speccheck("lint").code == 0, good
    project.write("speccheck.toml", 'specs = "specs"\nid-prefix = ""\n')
    project.spec("- REQ-001-01: Bare. (unimplemented: later)")
    assert project.speccheck("lint").out == "speccheck lint: 1 specs, 1 requirement\n"


@pytest.mark.covers(
    "SPC-REQ-002-05",
    "a producer limited to spec 002 may not claim T-REQ-001-01, and dropping its `specs` key lets it",
)
def test_a_producer_limited_to_some_specs(project: Project):
    """A claim on a spec outside the producer's list is a problem; "all" is the default."""
    project.write("speccheck.toml", CONFIG.replace('specs = "all"', 'specs = ["002"]'))
    project.spec("- T-REQ-001-01: One. (unimplemented: later)")
    project.results("r.jsonl", "unit", [("t", ["T-REQ-001-01"], "collected")])
    run = project.speccheck("check", "r.jsonl")
    assert "T-REQ-001-01 is in spec 001, which producer `unit` may not claim" in run.err
    project.write("speccheck.toml", CONFIG.replace('specs = "all"\n', ""))
    assert "may not claim" not in project.speccheck("check", "r.jsonl").err


@pytest.mark.parametrize(
    ("specs", "claimed", "allowed"),
    [
        pytest.param(
            '["001", "002"]',
            "T-REQ-001-01",
            True,
            marks=pytest.mark.covers(
                "SPC-REQ-002-05", "a producer limited to specs 001 and 002 may claim T-REQ-001-01 in spec 001"
            ),
            id="first-of-two",
        ),
        pytest.param(
            '["001", "002"]',
            "T-REQ-002-01",
            True,
            marks=pytest.mark.covers(
                "SPC-REQ-002-05", "a producer limited to specs 001 and 002 may claim T-REQ-002-01 in spec 002"
            ),
            id="second-of-two",
        ),
        pytest.param(
            '["001", "002"]',
            "T-REQ-003-01",
            False,
            marks=pytest.mark.covers(
                "SPC-REQ-002-05", "a producer limited to specs 001 and 002 may not claim T-REQ-003-01 in spec 003"
            ),
            id="outside-the-two",
        ),
        pytest.param(
            '"all"',
            "T-REQ-003-01",
            True,
            marks=pytest.mark.covers(
                "SPC-REQ-002-05", "a producer whose specs is the string all may claim T-REQ-003-01 in spec 003"
            ),
            id="explicit-all",
        ),
    ],
)
def test_a_producers_list_of_specs(project: Project, specs: str, claimed: str, allowed: bool):
    """The list allows each spec it names and no other; `"all"` allows every spec."""
    project.write("specs/000-index.md", "# Index\n\n- [001](001-a.md)\n- [002](002-b.md)\n- [003](003-c.md)\n")
    for number, name in (("001", "001-a.md"), ("002", "002-b.md"), ("003", "003-c.md")):
        # Only the requirement the test claims goes without the marker, so an accepted claim leaves nothing to report
        marker = "" if f"T-REQ-{number}-01" == claimed else " (unimplemented: later)"
        project.spec(f"- T-REQ-{number}-01: Spec {number}'s requirement.{marker}", number=number, name=name)
    project.write("speccheck.toml", CONFIG.replace('specs = "all"', f"specs = {specs}"))
    project.results("r.jsonl", "unit", [("t", [claimed], "collected")])
    run = project.speccheck("check", "r.jsonl")
    assert ("may not claim" not in run.err) is allowed, run.err
    if allowed:
        # Nothing else is wrong either: the claim is accepted, not merely not refused for its spec
        assert run.code == 0 and run.err == "", run.err
    else:
        assert run.code == 1
        assert f"{claimed} is in spec 003, which producer `unit` may not claim" in run.err, run.err


@pytest.mark.parametrize(
    ("specs", "message"),
    [
        pytest.param(
            '["1"]',
            "`producers.unit.specs`: '1' is not a spec number such as \"001\"",
            marks=pytest.mark.covers(
                "SPC-REQ-002-05", 'a producer whose specs list holds the one-digit "1" exits 2 naming the entry'
            ),
            id="one-digit",
        ),
        pytest.param(
            '["001", "all"]',
            "`producers.unit.specs`: 'all' is not a spec number such as \"001\"",
            marks=pytest.mark.covers(
                "SPC-REQ-002-05", "a specs list that mixes a good number with the word all exits 2 naming all"
            ),
            id="all-inside-a-list",
        ),
        pytest.param(
            "[1]",
            "`producers.unit.specs` must be a list of strings",
            marks=pytest.mark.covers(
                "SPC-REQ-002-05", "a specs list holding the integer 1 instead of a string exits 2 asking for strings"
            ),
            id="integer-entry",
        ),
    ],
)
def test_a_malformed_list_of_specs(project: Project, specs: str, message: str):
    """A list that is not spec numbers is a config error naming the producer's key, found before any results are read."""
    project.write("speccheck.toml", CONFIG.replace('specs = "all"', f"specs = {specs}"))
    run = project.speccheck("lint")
    assert run.code == 2
    assert f"speccheck.toml: {message}" in run.err, run.err


@pytest.mark.covers(
    "SPC-REQ-002-06",
    "an empty `covers` table and the old list form each exit 2",
)
def test_ci_job_entries(project: Project):
    """`covers` is a table that claims an ID."""
    project.write("speccheck.toml", CONFIG + "[ci.publish]\ncovers = {}\n")
    run = project.speccheck("lint")
    assert run.code == 2 and "`ci.publish.covers` must claim at least one ID" in run.err
    project.write("speccheck.toml", CONFIG + '[ci.publish]\ncovers = ["T-REQ-001-01"]\n')
    run = project.speccheck("lint")
    assert run.code == 2 and "`ci.publish.covers` must be a table from ID to how the job proves it" in run.err


@pytest.mark.covers(
    "SPC-REQ-002-08",
    "a [ci.unit] entry beside producer unit exits 2 saying it has the same name as a producer",
)
def test_a_ci_job_cant_share_a_producers_name(project: Project):
    """A job and a producer are told apart by name, so they can't have the same one."""
    project.write("speccheck.toml", CONFIG + '[ci.unit]\ncovers = { "T-REQ-001-01" = "the job" }\n')
    run = project.speccheck("lint")
    assert run.code == 2 and "`ci.unit` has the same name as a producer" in run.err


@pytest.mark.parametrize(
    ("table", "key"),
    [
        pytest.param(
            "producers",
            "producers",
            marks=pytest.mark.covers(
                "SPC-REQ-002-09", "a [producers.<name>] whose name is 201 characters exits 2 naming that key"
            ),
            id="producer",
        ),
        pytest.param(
            "ci",
            "ci",
            marks=pytest.mark.covers(
                "SPC-REQ-002-09", "a [ci.<job>] whose name is 201 characters exits 2 naming that key"
            ),
            id="ci-job",
        ),
    ],
)
def test_a_name_over_200_characters_is_an_error(project: Project, table: str, key: str):
    """The name is refused at config load, with its length; 200 characters is fine."""
    entry = '\ncovers = { "T-REQ-001-01" = "the job proves it" }\n' if table == "ci" else "\n"
    project.write("speccheck.toml", CONFIG + f"[{table}.{'a' * 200}]{entry}")
    assert project.speccheck("lint").code == 0
    project.write("speccheck.toml", CONFIG + f"[{table}.{'a' * 201}]{entry}")
    run = project.speccheck("lint")
    assert run.code == 2
    assert f"`{key}.{'a' * 201}`: a name is at most 200 characters; this one is 201" in run.err


@pytest.mark.covers(
    "SPC-REQ-002-06",
    "a CI job's empty, placeholder and non-string explanations exit 2, each naming the job's key and the ID",
)
def test_ci_job_explanations_are_checked_as_tests(project: Project):
    """The same spec-free rules as a test's explanation, at config load."""
    for how, message in (
        ('"  "', "`ci.publish.covers.T-REQ-001-01`: the explanation for T-REQ-001-01 is empty"),
        ('"FIXME"', "`ci.publish.covers.T-REQ-001-01`: the explanation for T-REQ-001-01 is a placeholder"),
        ("3", "`ci.publish.covers.T-REQ-001-01` must be a string saying how the job proves it"),
    ):
        project.write("speccheck.toml", CONFIG + f'[ci.publish]\ncovers = {{ "T-REQ-001-01" = {how} }}\n')
        run = project.speccheck("lint")
        assert run.code == 2 and message in run.err, (how, run.err)


@pytest.mark.parametrize(
    ("how", "message"),
    [
        pytest.param(
            '"' + "x" * 1001 + '"',
            "the explanation for T-REQ-001-01 is 1001 characters; the limit is 1000",
            marks=pytest.mark.covers(
                "SPC-REQ-002-06", "a CI job explanation of 1001 characters exits 2 naming the job's key and the ID"
            ),
            id="too-long",
        ),
        pytest.param(
            '"T-REQ-001-01"',
            "the explanation for T-REQ-001-01 is just the ID",
            marks=pytest.mark.covers(
                "SPC-REQ-002-06", "a CI job explanation that is the claimed ID exits 2 naming the job's key and the ID"
            ),
            id="the-id",
        ),
        pytest.param(
            '"Fixme"',
            "the explanation for T-REQ-001-01 is a placeholder ('Fixme')",
            marks=pytest.mark.covers(
                "SPC-REQ-002-06", "a CI job explanation of mixed-case Fixme exits 2 as a placeholder"
            ),
            id="mixed-case-placeholder",
        ),
        pytest.param(
            '"..."',
            "the explanation for T-REQ-001-01 is a placeholder ('...')",
            marks=pytest.mark.covers("SPC-REQ-002-06", "a CI job explanation of three dots exits 2 as a placeholder"),
            id="dots",
        ),
        pytest.param(
            '"  tBd \\n"',
            "the explanation for T-REQ-001-01 is a placeholder ('tBd')",
            marks=pytest.mark.covers(
                "SPC-REQ-002-06", "a CI job explanation of tBd padded with spaces and a newline exits 2"
            ),
            id="padded",
        ),
        pytest.param(
            '"TODO"',
            "the explanation for T-REQ-001-01 is a placeholder ('TODO')",
            marks=pytest.mark.covers(
                "SPC-REQ-002-06", "a CI job explanation of upper-case TODO exits 2 as a placeholder"
            ),
            id="todo",
        ),
        pytest.param(
            '"-"',
            "the explanation for T-REQ-001-01 is a placeholder ('-')",
            marks=pytest.mark.covers(
                "SPC-REQ-002-06", "a CI job explanation of a lone hyphen exits 2 as a placeholder"
            ),
            id="hyphen",
        ),
        pytest.param(
            '"t-req-001-01"',
            "the explanation for T-REQ-001-01 is just the ID",
            marks=pytest.mark.covers(
                "SPC-REQ-002-06", "a CI job explanation that is the claimed ID written in lower case exits 2 as the ID"
            ),
            id="the-id-in-lower-case",
        ),
    ],
)
def test_more_ci_job_explanations_that_are_refused(project: Project, how: str, message: str):
    """The same refusals as a test's explanation, found when the config is loaded, and naming the job and the ID."""
    project.write("speccheck.toml", CONFIG + f'[ci.publish]\ncovers = {{ "T-REQ-001-01" = {how} }}\n')
    run = project.speccheck("lint")
    assert run.code == 2
    assert f"`ci.publish.covers.T-REQ-001-01`: {message}" in run.err, run.err


@pytest.mark.covers(
    "SPC-REQ-002-06",
    "a CI job explanation of exactly 1000 characters loads and passes lint, where 1001 is the first length refused",
)
def test_a_ci_job_explanation_at_the_length_limit_is_accepted(project: Project):
    """The limit is inclusive: 1000 characters is fine, so only a longer one is the problem."""
    project.spec("- T-REQ-001-01: One.")
    project.write("speccheck.toml", CONFIG + f'[ci.publish]\ncovers = {{ "T-REQ-001-01" = "{"x" * 1000}" }}\n')
    run = project.speccheck("lint")
    assert run.code == 0 and run.err == "", run.err


@pytest.mark.covers(
    "SPC-REQ-002-06",
    "check fails on a CI job explanation that copies a spec bullet, naming the job and the copied requirement",
)
def test_ci_job_explanation_that_copies_a_requirement(project: Project):
    """The spec-dependent rule (003-09) is checked when the specs are read."""
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: The image MUST build.")
    project.write("speccheck.toml", CONFIG + '[ci.publish]\ncovers = { "T-REQ-001-01" = "the image must build" }\n')
    project.results("r.jsonl", "unit", [("t", ["T-REQ-001-02"], "collected")])
    run = project.speccheck("check", "r.jsonl")
    assert run.code == 1
    assert (
        "speccheck.toml: `ci.publish.covers`: the explanation for T-REQ-001-01 is the text of T-REQ-001-02" in run.err
    )


@pytest.mark.covers(
    "SPC-REQ-002-07",
    "a config whose `specs =` line has no value exits 2 saying speccheck.toml is not valid TOML",
)
def test_invalid_toml_names_the_file(project: Project):
    """A TOML syntax error is a config error that names the file."""
    project.write("speccheck.toml", "specs = \n")
    run = project.speccheck("lint")
    assert run.code == 2 and "speccheck.toml: not valid TOML" in run.err


@pytest.mark.covers(
    "SPC-REQ-002-07",
    "a broken pyproject.toml found without --config, and a broken file passed with --config bad.toml, each exit 2 naming that file as not valid TOML",
)
def test_invalid_toml_names_the_file_however_it_was_found(project: Project):
    """`find` reads a pyproject to look for its table, and `--config` loads a file directly: both name the file."""
    (project.root / "speccheck.toml").unlink()
    project.write("pyproject.toml", "[tool.speccheck\n")
    run = project.speccheck("lint")
    assert run.code == 2 and "pyproject.toml: not valid TOML" in run.err
    project.write("bad.toml", "specs = \n")
    run = project.speccheck("lint", "--config", "bad.toml")
    assert run.code == 2 and "bad.toml: not valid TOML" in run.err
