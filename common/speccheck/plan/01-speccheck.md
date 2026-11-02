# 1: speccheck

> **Status: In review (2026-11-01)**

## Goal

Build the reworked speccheck as a package in `common/speccheck/`, with its own specs, proven by its
own test runs in its own workflow. Nothing outside speccheck uses it yet: no other project, spec
folder or workflow changes. Branch from `devel`, not from #355.

## Work

- **Package** (`design.md`, "Location", "Structure", "Packaging"): `pyproject.toml`
  (`prometheus-speccheck`, `requires-python >=3.10`, `tomli` below 3.11, a `speccheck` console
  script, a `pytest11` entry point), `uv.lock` with the dev tools (pytest, pytest-cov or coverage,
  ruff) pinned with hashes, `README.md`, `run.py`, `.gitignore`, copyright markings on every new
  `.py` file.
- **`specs.py`:** port #355's spec parsing and its tests, minus citations and the `tests:` line, with
  the prefix taken from the config. Keep the `path:line: message` problems and the
  control-character escaping.
- **`config.py`:** `speccheck.toml` or `[tool.speccheck]`, with the keys in `design.md`, "Config".
  Unknown keys, unknown producers and bad paths are errors with the file and key.
- **`results.py`:** write, read, validate and merge `speccheck-results/1` files, with a size limit.
  Include a JSON Schema for the format in `speccheck/schema/`, for runners in other languages.
- **`ci.py`:** read the GitHub Actions context and build run and job URLs. **Find out first** whether
  `${{ job.check_run_id }}` is available on our runners, and write the outcome into `design.md`
  ("Job links").
- **`pytest_plugin.py`:** the `covers` marker, the collection check, outcome merging across phases,
  writing only when asked, xdist-safe (writing from the controller only).
- **Actions:** `lint`, `check`, `verify` (`--complete`), `report` (`--output`, `--json`),
  `record`. `lint`, `check` and `verify` take `--summary`. Shared `--config`, `--json`, `--quiet`, `--verbose`, `--version`.
- **Composite actions:** `.github/actions/speccheck-upload/` and `.github/actions/speccheck-verify/`.
- **speccheck's own specs** `common/speccheck/specs/` (prefix `SPC`): the index and specs 001 to 008
  from `design.md`, with requirements, every one claimed by a test or by a `[ci.*]` job.
- **speccheck's own config** `common/speccheck/speccheck.toml`: its specs, its `speccheck-unit`
  producer, and a CI-job claim for the requirement that `speccheck-verify` runs as a final job.
- **Workflow** `.github/workflows/speccheck.yml`, path-filtered on `common/speccheck/**`, both
  composite actions, and the workflow itself, with:
  - `unit`: Python 3.10, 3.11, 3.12, 3.13 and 3.14; ruff on one leg; 100% line and branch coverage;
    results uploaded per leg;
  - `speccheck`: the final job, `needs: unit`, `verify --complete` on its own results, the
    failures in the step summary and the report as an artifact.
  It is not a required check.
- **Dependabot** entry for `common/speccheck` (uv).
- **Tests mirror the code**, and a docstring test, as in platformctl.
- **Test the parts that can only fail in a real run**, not just their units: a `pytester` run
  where an inner test is skipped, deselected, xfailed, fails in teardown, and passes, then
  `verify` on the file it wrote; the same with `-p xdist -n 2`; and a `record` run with a fake CI
  environment.

## Output

- `lint`/`check`/`verify`: the problems, then one summary line. `verify` also names the
  producers that reported and those that are missing.
- `--summary` (on `lint`, `check`, `verify`): one line of counts with a link to the report, then
  the problems, and nothing else. The full report goes into the artifact.
- `--json` everywhere.

## Done when

- `speccheck.yml` passes on every Python version and its final job verifies speccheck's own specs
  completely, with the report as an artifact and job links that open the right job (or the run,
  if job IDs turned out not to be available).
- Breaking a test that claims an SPC requirement, or skipping it, fails the final job, and the
  report shows that requirement as `failed`.
- Nothing outside `common/speccheck/`, `.github/actions/speccheck-*/`,
  `.github/workflows/speccheck.yml` and `.github/dependabot.yml` changed.

## As built

What differs from the plan above, or settles something it left open:

- **Job links:** `${{ job.check_run_id }}` exists on github.com, so jobs pass it as
  `SPECCHECK_JOB_ID` and links go to the job itself (`design.md`, "Job links").
- **Artifact names:** results are `speccheck-results-<name>`, not `speccheck-<name>`, so the
  report artifact is never read as results. Retention is 30 days for results and 90 for the report.
- **A `claimed` status** for `check`, which sees claims but not outcomes. `report` and `--json`
  show it.
- **`not run` covers unreported test producers too** (in `verify`): a requirement nobody claims,
  while a test producer that may claim it hasn't reported, is `not run` (waiting on that producer),
  not `unclaimed`. Otherwise a partial check would fail on requirements whose producer simply
  didn't run.
- **The self-check job** (`speccheck-self-check`) runs `speccheck-verify` on the requirements legs'
  results, checks that the report and summary were written, and checks that `speccheck-upload`
  refuses an empty folder. Then it records SPC-REQ-007-03, 007-04 and 007-06 and uploads with
  `speccheck-upload`. The final job's `verify --complete` therefore fails if either action or
  `record` breaks.
- **Two test suites** (decided 2026-11-01, after the first version):
  - `tests/unit/` mirrors the package and claims nothing. It is the only suite run under coverage,
    and it alone reaches 100% line and branch coverage (combined across 3.10 to 3.14).
  - `tests/requirements/` has one file per spec. It proves each SPC requirement through what a
    user sees: the CLI, real inner pytest runs and the files they write. Every test there claims
    what it proves, and none of it counts toward coverage.
  - A collection rule in `tests/conftest.py` fails on a mark in the unit suite, or a missing one in
    the requirements suite. `tests/rules/` (rules about the code base, run beside the unit tests
    and not measured) checks that the unit files mirror the package and the requirements files
    mirror the specs.
  - Unit tests build their inputs in memory (`tests/unit/conftest.py`) and call one module
    directly: no CLI round trip, no subprocess, and only two small pytester runs for the plugin's
    wiring. The command line and real runs are the requirements suite's job.
  - The producer is `speccheck-requirements`, uploaded by the `requirements` job. The `unit` job
    uploads only coverage data.
  - Why: a requirement claimed from a helper's unit test proves the helper, not the promise, and
    coverage from end-to-end tests hides untested units.
- **Coverage** is traced into subprocesses (`patch = ["subprocess"]`), so pytester subprocess runs
  and xdist workers in the unit suite count. Each leg's data is combined in a `coverage` job, as in
  platformctl.
- **`check` and unreported producers:** a requirement nothing claims is `unclaimed` in `check`,
  even when a producer is missing from its inputs. A collect-only run sees every claim. Only
  `verify` calls it `not run` while a producer that may claim it hasn't reported.
- **Spec review (2026-11-02):** the requirements were reviewed for overlap, for focus on users,
  and for decisions that would be hard to undo. SPC-BEH-005-01 and the old 007-05 were removed as
  duplicates, the retired 008-06 was dropped (nothing was merged yet), and 001-10 became 008-06,
  which covers all output. Requirements that named a mechanism (module layout, uv,
  `tomli`, the xdist controller, `check_run_id`) now state what the user gets. 005-01 says "by
  default", so an "every leg must pass" option can come later. The GitHub specifics moved into
  007-07, and the results-file header gained `ci.provider`. Readers now ignore unknown keys, so
  fields can be added within `speccheck-results/1`, the same rule `--json` follows. The pytest
  outcome mapping moved to 003-07, and 004-03 defines the outcomes independently of the runner.
- **How each claim proves its requirement (2026-11-02, after the review panel):** a claim is
  `covers(ID, how)`, one mark per ID, with a required plain-text explanation of up to 1000
  characters, whitespace collapsed. The report shows it under each table. Decided with it:
  - **Marks go on one test only:** a plain function, or one `pytest.param` of the test's single
    `parametrize`. Class, module and function-on-parametrized marks, a second `parametrize` and
    parametrized fixtures fail collection. This reverses the old SPC-REQ-003-02 ("marks from every
    level add up"), so that every explanation describes exactly one test.
  - **No repeats:** a test claims an ID once; no two claims share an explanation (at collection,
    and across all results in `check` and `verify`); an explanation can't be a placeholder, the
    ID, or any requirement's text; and no two requirements in a folder share text (`lint`).
    Texts are compared ignoring whitespace, case and a trailing full stop.
  - **Results format:** `covers` became a list of `{"id", "how"}` objects within
    `speccheck-results/1`, since nothing outside speccheck reads it yet. `[ci.<job>] covers`
    became a table from ID to explanation.
  - **Step summary shows only failures:** `report --summary` (and SPC-REQ-006-04) are gone. `lint`,
    `check` and `verify` take `--summary`, writing one counts line with a `--report-url` link to
    the artifact, then the problems. `speccheck-verify` uploads the report before `verify` runs,
    so it has the link.
  - New and changed requirements: 001-10, 002-06, 003-02, 003-04, 003-05, 003-08 to 003-11,
    004-01, 004-09, 005-10, 006-01, 006-03, 007-01, 007-04, 007-07, 008-07 to 008-09.
- **The report, one section per requirement (2026-11-02, from the first CI report):** the table
  per spec read badly once the text was long. The report now has a table of specs, then per spec
  its Purpose and a status table, then a section per requirement and a subsection per claiming
  test or job. Decided with it:
  - **Jobs by display name, not matrix value:** `SPECCHECK_LEG` and `ci.leg` are gone, since a
    matrix value can't name a job with two axes or none. `speccheck-verify` looks up the run's job
    names from the jobs API (now `actions: read` as well as `contents: read`) and passes them to
    `report` and `verify` as `--job-names`, which is optional.
  - **Source links:** each requirement links to its spec line, and each test to its line, at the
    tested commit. The results header gained `root`, so a test's file is known from the
    repository's root.
  - **Lighter escaping** outside code spans.
  - New and changed requirements: 004-08, 004-10, 006-01, 006-02, 006-03, 006-07, 007-04, 008-10.
- **The second review panel (2026-11-02):** fixes are the `review-panel <ID>:` commits after the
  per-requirement report. One changes a requirement:
  - **An unconfigured plugin is inert (TECH-3):** the shape checks (003-02, 003-04, 003-08, 003-10,
    003-11) ran on every run, so installing speccheck broke a project with a `covers` marker of its
    own. They now run only when `speccheck_config` is set or the run asks for a results file.
    003-05 says so.
- **Not done here:** actionlint and zizmor weren't run locally (not installed). `lint-workflows.yml`
  runs both on the PR.

## Adopting

What will surprise a project that adopts speccheck (steps 3 and 4), to repeat in the migration
steps and in the PR that adds it:

- **A half-migrated suite breaks local pytest.** With `speccheck_config` set, collection checks every
  claim in the spec folder on every run, locally too. One malformed, unknown or retired ID, or one
  the producer may not claim, stops pytest before any test runs. Migrate a whole spec at a time, and
  use `pytest -o speccheck_config=` to iterate meanwhile. That turns every check off only when no
  results file is asked for.
- **Docstring and comment citations stop counting, silently.** Only
  `@pytest.mark.covers("ID", "how")` counts. Until a test carries the marker, its requirement is `unclaimed`, and `verify` fails on it,
  but nothing complains about the old citation.
- **The job name is the producer.** `record` takes the job from `$GITHUB_JOB`, which is the job's key
  in the workflow, and looks it up as `[ci.<job>]` in the config. Renaming the job without the
  config entry makes `record` fail.
- **Every claim needs its own explanation.** Converting a citation means writing how that test
  proves the requirement, and a parametrized test whose citation covered every case needs a
  `pytest.param(..., marks=...)` per case, each saying something different. Class and module
  marks have to move down to the tests.
- **Two workflow pieces are needed.** A job that runs `record` needs the `speccheck-install` step.
  The workflow needs a final job, `needs:` every producer, with `if: ${{ !cancelled() }}` and
  `speccheck-verify`. Without it nothing checks the results.

## Reviewers

technical, CI and tests, security, AI skills. See `reviews.md` for what to point each at.
