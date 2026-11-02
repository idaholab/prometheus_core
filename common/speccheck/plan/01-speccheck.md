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
- **Actions:** `lint`, `check`, `verify` (`--complete`), `report` (`--output`, `--summary`,
  `--json`), `record`. Shared `--config`, `--json`, `--quiet`, `--verbose`, `--version`.
- **Composite actions:** `.github/actions/speccheck-upload/` and `.github/actions/speccheck-verify/`.
- **speccheck's own specs** `common/speccheck/specs/` (prefix `SPC`): the index and specs 001 to 008
  from `design.md`, with requirements, every one claimed by a test or by a `[ci.*]` job.
- **speccheck's own config** `common/speccheck/speccheck.toml`: its specs, its `speccheck-unit`
  producer, and a CI-job claim for the requirement that `speccheck-verify` runs as a final job.
- **Workflow** `.github/workflows/speccheck.yml`, path-filtered on `common/speccheck/**`, both
  composite actions, and the workflow itself, with:
  - `unit`: Python 3.10, 3.11, 3.12, 3.13 and 3.14; ruff on one leg; 100% line and branch coverage;
    results uploaded per leg;
  - `speccheck`: the final job, `needs: unit`, `verify --complete` on its own results, the report
    in the step summary and as an artifact.
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
- `report --summary`: counts per status and the problem rows. The full report goes into the
  artifact.
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
  refuses an empty folder. Then it records SPC-REQ-007-03 to 007-05 and uploads with
  `speccheck-upload`. The final job's `verify --complete` therefore fails if either action or
  `record` breaks.
- **Two test suites** (decided 2026-11-01, after the first version):
  - `tests/unit/` mirrors the package and claims nothing. It is the only suite run under coverage,
    and it alone reaches 100% line and branch coverage (combined across 3.10 to 3.14).
  - `tests/requirements/` has one file per spec. It proves each SPC requirement through what a
    user sees: the CLI, real inner pytest runs and the files they write. Every test there claims
    what it proves, and none of it counts toward coverage.
  - A collection rule in `tests/conftest.py` fails on a mark in the unit suite, or a missing one in
    the requirements suite. `test_rules.py` checks that the requirements files mirror the specs.
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
- **Not done here:** actionlint and zizmor weren't run locally (not installed). `lint-workflows.yml`
  runs both on the PR.

## Reviewers

technical, CI and tests, security, AI skills. See `reviews.md` for what to point each at.
