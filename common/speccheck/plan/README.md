# speccheck: requirements proven by test runs

Rework the SDD spec checker so that a requirement counts as met only when a test that claims it
**ran and passed** in CI, not when a test's docstring mentions it. Tests claim requirements with a
pytest marker; every test run writes a results file that CI uploads as an artifact; a final job
in each workflow downloads them, checks every spec, and publishes a markdown report of where each
requirement is tested, with a link to the CI job that proved it.

- Design and decisions: [`design.md`](design.md)
- The review panel each step gets before merging, and which reviewers:
  [`reviews.md`](reviews.md)
- One file per step below. Each step is one pull request and leaves `devel` working.

Planned on 2026-11-01. This replaces the checker in idaholab/prometheus_core#355, which read
citations from source text (docstrings, `# Covers` comments, workflow comments) and so could not
tell a passing test from a skipped one or one that never ran. #355 and its follow-up #361 (the
platformctl requirements) are closed; their spec content is reworked onto this tool in step 2.

## Steps

| # | File | Summary | Depends on | Status |
|---|------|---------|------------|--------|
| 1 | [`01-speccheck.md`](01-speccheck.md) | The package: spec parsing, config, results files, the pytest plugin, `lint`/`check`/`verify`/`report`/`record`, the upload and verify actions, its own specs, its own workflow checked by itself | - | In review |
| 2 | [`02-build-specs.md`](02-build-specs.md) | Bring back the build and run specs (from #355/#361) and check platformctl against them | 1 | Not started |
| 3 | [`03-sdk-adopt.md`](03-sdk-adopt.md) | `sdk/specs` on speccheck: the `SDK-` prefix, markers instead of citations, results from the sdk jobs, the final job | 1 | Not started |
| 4 | [`04-sdk-evidence.md`](04-sdk-evidence.md) | Mark or test the sdk requirements nobody cites yet | 3 | Not started |
| 5 | [`05-vitest.md`](05-vitest.md) | Future: a vitest reporter and a `covers()` helper that write the same results files | 1 | Not started |

When a step is done, set its status here and in its file to `Done (<date>, #<PR>)`, and note
anything that differs from the plan.

## Ground rules

These follow the platformctl plan (`platform/plans/platformctl/README.md`), so the two tools are
built and reviewed the same way.

- **One module per command in `speccheck/actions/`**, found automatically, each exporting `NAME`,
  `HELP`, `SECTION`, `ORDER`, `add_arguments(parser)` and `run(ctx, args) -> int`, as in
  platformctl (`design.md`, "Structure"). `cli.py` builds the parser from them.
- **A real package**, added to each project that uses it as a path dev dependency (so each
  project's `uv.lock` changes). Runtime is the standard library plus `tomli` on Python 3.10. pytest
  is not a dependency: the plugin module is imported only by pytest.
- **Python 3.10 or newer**, the oldest Python any project that will use it supports
  (platformctl). CI tests speccheck on every version 3.10 to 3.14.
- **100% line and branch coverage**, from tests that never reach the network or a real CI.
- **Every function, global and class variable has its own brief docstring**, and **tests mirror the
  code** (`speccheck/actions/check.py` is tested in `tests/actions/test_check.py`), each enforced
  by a test, as in platformctl.
- **speccheck is checked by speccheck.** Its own requirements live in `common/speccheck/specs/`
  (`SPC-` prefix); its tests claim them with the marker; its workflow ends with the same final job
  every other project uses. A requirement of speccheck's that only a test run can prove is proved
  that way, not by a unit test of the checker alone.
- **Decoupled.** Step 1 touches only `common/speccheck/`, `.github/actions/speccheck-upload/`, `.github/actions/speccheck-verify/`,
  `.github/workflows/speccheck.yml` and Dependabot. No other project, spec folder or workflow
  changes until its own step.
- **Evidence is a passing result, never a mention.** No step brings back docstring or comment
  citations, even for a migration period.
- **Every step is reviewed before merging** with `/review-panel`, using the reviewers in
  `reviews.md`, each with fresh context.
- Every PR fills in `.github/PULL_REQUEST_TEMPLATE.md`, and lists what changes for spec authors
  and test authors.
