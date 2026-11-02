# speccheck

Checks a folder of SDD specs against the test runs that prove them. A requirement counts as met
only when a test (or CI job) that claims it **ran and passed** in CI. A docstring or a comment that
mentions an ID is not evidence.

- Tests claim requirements with a pytest marker, `@pytest.mark.covers("SPC-REQ-004-01")`.
- Each test run writes a results file, which the CI job uploads as an artifact.
- The last job of each workflow downloads the results, runs `verify`, and publishes a markdown
  report of where each requirement is proven, with links to the CI jobs.

The design and its decisions are in [`plan/design.md`](plan/design.md). speccheck's own
requirements are in [`specs/`](specs/000-index.md), proven by `tests/requirements/` and checked by
speccheck itself in [`speccheck.yml`](../../.github/workflows/speccheck.yml). Its unit tests are in
`tests/unit/`.

## Quick start

```sh
# What a project runs locally: collect, then check that every requirement is claimed
pytest --collect-only -q --speccheck-results=.speccheck/collect.jsonl
speccheck check .speccheck/

# What the final CI job runs on the downloaded results
speccheck verify --complete results/
speccheck report results/ --output report.md --summary "$GITHUB_STEP_SUMMARY"
```

Python 3.10 or newer. At runtime it needs only the standard library, plus `tomli` on 3.10.
A project adds it as a path dev dependency, so its `uv.lock` changes:

```toml
[dependency-groups]
dev = ["prometheus-speccheck"]

[tool.uv.sources]
prometheus-speccheck = { path = "../common/speccheck" }
```

Installing it registers the pytest plugin, which does nothing until it is configured (see "Claiming a
requirement"). As a command on its own, install it as a uv tool, which puts `speccheck` on `PATH`:
`uv tool install ./common/speccheck`. In CI, the `speccheck-install` action does that (see "In CI").

## Commands

| Command | Reads | Fails (exit 1) when |
|---|---|---|
| `lint` | the spec folder | a spec breaks the format |
| `check [RESULTS...]` | specs, config, results files (a collect-only run is enough) | a requirement that isn't planned, untested or retired has no claim; a claim names a malformed, unknown or retired ID, or one its producer may not claim; a marker is left on a claimed requirement |
| `verify [RESULTS...]` | the same, from a real run | everything `check` fails on, plus a claimed requirement with no passing result. With `--complete`, also a producer that didn't report, and a requirement nothing that reported claims |
| `report [RESULTS...]` | the same as `verify` | never on the requirements; writes markdown to stdout, `--output FILE` and `--summary FILE` (appended), or `--json` |
| `record` | config, the CI environment | the job has no `[ci.<job>]` entry (exit 2) |

`RESULTS` are results files, or folders searched for `*.jsonl` (symlinks are not followed).
`--complete --workflow NAME` expects only the producers that list that workflow.

Global options work before or after the command: `--config PATH` (default `speccheck.toml` here,
then `[tool.speccheck]` in `pyproject.toml`), `--json`, `--quiet`, `--verbose`, `--version`.
Exit codes: 0 fine, 1 problems, 2 usage or config error.

**Output.** Problems go to stderr as `path:line: message`, so editors and CI logs link them. Each
message says what to do. The last line is a summary, such as
`speccheck verify: 58 requirements: 1 failed, 57 passed; reported: speccheck-requirements; 1 problem`.
Control characters in anything printed are written out (`\n`, `\x1b`), and so are the GitHub
Actions log commands: a leading `::` becomes `\x3a:` and `##[` becomes `##\x5b`. So a file name,
spec text or results file can't start a `::error::` or `##[error]` line in a CI log. Files that
`report` writes keep the text as written, escaped for markdown instead.

**`--json`.** Exactly one object on stdout, on every exit path:

```json
{
  "schema_version": 1,
  "command": "verify",
  "ok": false,
  "problems": [{"path": "specs/002-config.md", "line": 18, "message": "SPC-REQ-002-04 has no passing result: ..."}],
  "counts": {"failed": 1, "unclaimed": 0, "not run": 0, "claimed": 0, "passed": 57, "planned": 0, "untested": 0, "retired": 0},
  "requirements": [
    {"id": "SPC-REQ-002-04", "spec": "002", "status": "failed", "text": "...", "waiting_on": [],
     "evidence": [{"test": "tests/requirements/test_002_config.py::test_the_prefix", "kind": "test", "file": "tests/requirements/test_002_config.py", "line": 70,
                   "outcome": "failed", "producer": "speccheck-requirements", "leg": "3.12", "job": "requirements", "url": "https://..."}]}
  ],
  "producers": {"reported": ["speccheck-requirements"], "missing": []}
}
```

A usage or config error has `"error": {"code": "usage", "message": "..."}` instead. Fields are only
added within a `schema_version`.

## Statuses

| Status | Means | Fails |
|---|---|---|
| `passed` | at least one claiming result passed (by default one is enough, in any producer or leg) | no |
| `failed` | claimed, and no claiming result passed: failed, error, skipped, xfailed, xpassed, deselected or collected | `verify` |
| `not run` | claimed only by producers that didn't report in these inputs | `verify --complete` |
| `unclaimed` | nothing claims it, and it isn't planned, untested or retired | `check`, `verify` |
| `claimed` | (`check` only) claimed; outcomes aren't looked at | no |
| `planned`, `untested`, `retired` | the spec says so, and nothing claims it | no |

A planned or untested requirement that is claimed is a problem, "remove the marker".

## The spec format

A spec folder holds `000-index.md` and one `NNN-short-name.md` per spec:

```markdown
# 004 - Results files

status: implemented

## Requirements

- SPC-REQ-004-01: A results file MUST be JSON Lines ...
- SPC-REQ-004-02: A reader MUST reject ... ⚠ untested
- SPC-BEH-004-01: GIVEN ... WHEN ... THEN ... (planned: step 3)
- SPC-REQ-004-03: Retired. Replaced by SPC-REQ-004-05.
```

- **Files.** `NNN-short-name.md`, whose first line is `# NNN - Name`. With `require-index` (the
  default), `000-index.md` must link every spec as a markdown link, such as
  `[004](004-results-files.md)`. A mention in prose doesn't count.
- **Header.** One `status:` line above the first `##`: `draft`, `implemented` or `retired`. An
  `implemented` spec needs at least one requirement. Other header lines (`sources:`,
  `depends-on:`) are free text.
- **Bullets.** `- <prefix>-REQ-NNN-XX: text` or `- <prefix>-BEH-NNN-XX: text`, where `NNN` is the
  spec's number. The prefix comes from the config, or is absent when `id-prefix = ""`. A bullet may
  wrap onto lines indented two spaces. A line that starts like an ID in any other form (`*`, bold,
  nested, missing prefix) is a problem, so it can't go unseen. IDs are unique across the folder.
- **Markers**, anywhere in the bullet's text: `⚠ untested` (no test yet, on purpose) or
  `(planned: <step>)` (a later plan step delivers it). Never both. Text starting `Retired.` or
  `Retired:`, or a `retired` spec, retires a requirement. A retired ID stays in the spec and must
  not be claimed.
- Fenced code blocks are skipped.
- The old checker's `tests:` line (in a spec) and `id-prefix:` line (in the index) are problems that
  point at the config.

## Config

One config per spec folder, `speccheck.toml` or `[tool.speccheck]` in a project's `pyproject.toml`.
Paths are relative to the config file. Unknown keys in the config are errors.

```toml
specs = "specs"                 # the spec folder
id-prefix = "SPC"               # IDs are SPC-REQ-NNN-XX; "" for bare IDs
require-index = true

[producers.speccheck-requirements]      # a test run that provides evidence
specs = "all"                   # or ["001", "004"]: the specs it may claim
workflows = ["speccheck"]       # the workflows it runs in, for verify --complete --workflow

[ci.speccheck-self-check]       # a CI job (by its job id) that is itself evidence
covers = ["SPC-REQ-007-03"]
workflows = ["speccheck"]

[report]
title = "speccheck requirements"
```

A results file from an undeclared producer is a problem, and its results don't count.

## Claiming a requirement

```python
@pytest.mark.covers("SPC-REQ-004-01", "SPC-BEH-004-02")
def test_results_file_round_trips():
    """A written results file reads back the same."""
```

- Works on a function, a class (every method), a module (`pytestmark = pytest.mark.covers(...)`) or
  one parameter (`pytest.param(..., marks=pytest.mark.covers(...))`). Marks add up.
- The plugin registers the marker, so `--strict-markers` accepts it.
- With `speccheck_config` in the project's pytest ini options, collection fails (on every run,
  locally too) on a malformed, unknown or retired ID, or one the producer may not claim. The
  producer is `SPECCHECK_PRODUCER`, or `speccheck_producer` in the ini options:

  ```toml
  [tool.pytest.ini_options]
  speccheck_config = "pyproject.toml"
  speccheck_producer = "sdk-python"
  ```

- A `covers` mark with no IDs, a non-string ID or keyword arguments always fails collection.
- Only the marker counts. A docstring may still say what a test proves, for the reader.
- Whether a test really proves what it claims is a review question. speccheck sees only that it
  claims an ID and passed.

**Which tests claim.** Claim a requirement only from a test that proves its observable behaviour:
what a user of the thing sees, such as a command's output and exit code, a file it writes, or a
response. A unit test of a helper claims nothing, even when the helper exists for a requirement. It
proves the helper, not the promise. speccheck keeps the two apart in its own tests, and a project
can do the same:

| | `tests/unit/` | `tests/requirements/` |
|---|---|---|
| Tests | one module at a time, mirroring the package | one spec per file, through the public interface |
| `covers` marks | none (collection fails on one) | every test (collection fails without one) |
| Coverage | the only suite measured, held at 100% | not measured |
| In CI | the `unit` job | the `requirements` job, whose results file is the evidence |

Coverage then says how much code the unit tests exercise, and the report says which promises are
kept. Neither one can stand in for the other.

## Results files

`speccheck-results/1`, JSON Lines: a header, then one line per claiming test. The JSON Schema is
[`speccheck/schema/speccheck-results-1.schema.json`](speccheck/schema/speccheck-results-1.schema.json),
for runners in other languages.

```json
{"schema": "speccheck-results/1", "producer": "sdk-python", "runner": "pytest 9.2.0", "started": "2026-11-01T12:00:00Z",
 "ci": {"provider": "github", "server": "https://github.com", "repository": "idaholab/prometheus_core", "workflow": "test", "job": "sdk-python",
        "leg": "3.12", "run_id": 123, "run_attempt": 1, "job_id": 456, "sha": "...", "ref": "...", "event": "push",
        "run_url": ".../actions/runs/123/attempts/1", "job_url": ".../actions/runs/123/job/456"}}
{"test": "tests/test_llm_client.py::test_chat_proxy", "file": "tests/test_llm_client.py", "line": 181,
 "covers": ["SDK-REQ-006-08"], "outcome": "passed"}
```

- The plugin writes one only when asked, with `--speccheck-results=PATH` or `SPECCHECK_RESULTS`. A
  plain `pytest` writes nothing.
- It is written atomically when the session ends. An interrupted session leaves no file, so
  `verify --complete` reports the producer as missing.
- A test's outcome merges setup, call and teardown. An error in setup or teardown makes it `error`,
  a skip makes it `skipped`, and an expected failure makes it `xfailed`. Skipped, deselected and
  (`--collect-only`) collected claims are written too, so `verify` can say "claimed but didn't run".
- Under pytest-xdist the run writes one file, with every worker's results.
- `ci` says which CI provider ran it (`provider`), and where. GitHub Actions is the only provider so
  far: its block comes from `GITHUB_*`, plus `SPECCHECK_LEG` and `SPECCHECK_JOB_ID`, which the
  workflow sets. Outside CI it is null.
- A reader treats every file as untrusted. It parses JSON only, with size limits (16 MiB a file,
  64 KiB a line), and every field is checked. A file with another `schema`, a wrong type or an
  unknown outcome is rejected whole. Keys it doesn't know are dropped unread, so fields can be
  added within `speccheck-results/1`. Paths in the file are never opened.

## In CI

In each job that runs claiming tests:

```yaml
    env:
      SPECCHECK_PRODUCER: sdk-python
      SPECCHECK_LEG: ${{ matrix.python }}
      SPECCHECK_JOB_ID: ${{ job.check_run_id }}     # so the report links the job, not just the run
      SPECCHECK_RESULTS: ${{ github.workspace }}/.speccheck/sdk-python-${{ matrix.python }}.jsonl
    steps:
      - run: uv run --frozen pytest
      - uses: ./.github/actions/speccheck-upload
        if: ${{ !cancelled() }}
        with:
          name: sdk-python-${{ matrix.python }}
```

A job that is itself the evidence (`[ci.<job>]` in the config) records as its last step, which
runs only when the steps before it passed:

```yaml
      - uses: ./.github/actions/speccheck-install
      - run: speccheck record --config sdk/pyproject.toml
      - uses: ./.github/actions/speccheck-upload
        if: ${{ !cancelled() }}
        with:
          name: sdk-install
```

And at the end of the workflow:

```yaml
  speccheck:
    needs: [sdk-python, sdk-install]
    if: ${{ !cancelled() }}
    runs-on: ubuntu-26.04
    steps:
      - uses: actions/checkout@...
        with:
          persist-credentials: false
      - uses: ./.github/actions/speccheck-verify
        with:
          config: sdk/pyproject.toml
          complete: ${{ github.event_name != 'pull_request' }}
```

- **`speccheck-install`** installs `common/speccheck` from the checkout with `uv tool install`
  and puts `speccheck` on `PATH`. It sets up uv with no cache and leaves the job's own environment
  alone. A job that runs `pytest` in its own uv environment doesn't need it: the plugin comes with
  the project's dev dependencies.
- **`speccheck-upload`** uploads `.speccheck/` (or `path`) as `speccheck-results-<name>`, kept 30
  days, and fails the job when there is nothing to upload.
- **`speccheck-verify`** installs speccheck with `speccheck-install`, then downloads every `speccheck-results-*` artifact of the run. It writes the
  report and appends the short form (counts, problems and the rows that need attention, under
  the 1 MiB limit) to the step summary. It uploads `report.md` and `report.json` as
  `speccheck-report`, kept 90 days, then runs `verify` and fails with it. It needs `contents: read`
  only, and no secrets. With `complete`, it expects the producers that list the workflow's name.
- Job links use `${{ job.check_run_id }}`, the job's check run ID, which is also the ID in its
  URL. Without it, the link is the run attempt.
