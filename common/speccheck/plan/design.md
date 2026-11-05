# speccheck: design

## Goals

- A requirement is met only when a test or CI job that claims it **ran and passed** in CI. A
  claim that was skipped, deselected, xfailed or never run does not count.
- Tests claim requirements with a pytest marker, which pytest itself checks (a typo or an unknown
  ID fails collection, locally as well as in CI).
- Each test run writes a results file that the job uploads as an artifact. A final job merges
  them, checks every spec, and publishes a report that links each requirement to the CI jobs that
  proved it.
- A CI job that is itself the evidence (a publish, an image build, an install smoke test) can
  claim requirements too, and is checked the same way.
- One tool for every spec folder in the repository, configured per folder, with its own specs
  checked by itself.
- Room for vitest (and any other runner) later: a runner only has to write the same results file.

Not goals: deciding whether a test really proves what it claims (that stays a review question),
tracing requirements to source code, or replacing coverage.

## What changes from #355

#355 read evidence from source text. That needed a lot of rules about where a mention counts
(test docstrings but not helpers, `# Covers` comments, workflow comments found by YAML
indentation), and it still could not see whether the test ran. All of that goes. What carries
over:

- The spec format and its parsing: `NNN-name.md` files, `000-index.md` linking each spec,
  `REQ-`/`BEH-` bullets, the ID prefix, malformed-bullet detection, fenced code skipped, and the
  `path:line: message` problem format with control characters written out. #355's `status:`
  header, `⚠ untested`, `(planned: <step>)` and `Retired.` were carried over too, and replaced
  later in step 1 (see "Requirement states").
- Its 34 tests, where they test that parsing.

Changed:

- The `id-prefix:` line moves from `000-index.md` into the config.
- The spec's `tests:` header line goes. Which tests may claim which specs is set in the config
  (see "Producers"), so a spec file is only about requirements.
- No more `Covers`/`Implements` in text. A docstring may still say what a test proves, for the
  reader, but the checker ignores it.

## Location

`common/speccheck/`, a package beside `common/certs/`. It is shared by every project and owned
by none.

```
common/speccheck/
  pyproject.toml            # name prometheus-speccheck, import name speccheck
  uv.lock
  README.md                 # usage, and the spec format (moved from sdk/docs in step 3)
  speccheck.toml            # speccheck's own config (its specs, its producers)
  speccheck/
    __init__.py, __main__.py
    cli.py                  # parser built from actions/, top-level error handling
    context.py              # Context: config, output, root, CI environment
    output.py               # text output and problems
    jsonout.py              # the versioned --json envelope
    config.py               # load and validate speccheck.toml / [tool.speccheck]
    specs.py                # spec folder parsing (from #355)
    claims.py               # a claim (ID and how) and the rules for its explanation
    results.py              # the results file format: read, write, validate, merge
    evidence.py             # claims + outcomes -> one status per requirement
    markdown.py             # escaping and the only links allowed, for the report and summary
    summary.py              # --summary: the failures-only step summary
    ci.py                   # GitHub Actions context: run, job, attempt, URLs
    pytest_plugin.py        # the `covers` marker, collection check, results writer
    actions/
      __init__.py           # discover(), SECTIONS
      lint.py
      check.py
      verify.py
      report.py
      record.py
  specs/                    # speccheck's own specs, prefix SPC
    000-index.md
    001-...md
  tests/                    # mirrors speccheck/, plus fixtures/
  plan/                     # this plan
.github/actions/speccheck-upload/   # upload a job's results files
.github/actions/speccheck-verify/   # the final job's steps: download, verify, report
.github/workflows/speccheck.yml
```

**Where speccheck's own specs live:** `common/speccheck/specs/`. They move with the tool and
nothing else claims them. Sample spec folders used as test inputs stay under `tests/fixtures/`,
so a fixture can never be read as one of speccheck's requirements.

## Structure

The same as platformctl (`platform/plans/platformctl/design.md`, "Structure" and "Extending and
changing commands"):

- **One module per command in `actions/`.** Each exports `NAME`, `HELP`, `SECTION`, `ORDER`,
  `add_arguments(parser)` and `run(ctx, args) -> int`. `actions.discover()` finds them with
  `pkgutil`, and `cli.py` builds the parser and the sectioned `--help` from them. Adding a
  command is adding a file.
- **Sections:** `check` (`lint`, `check`, `verify`) and `ci` (`report`, `record`).
- **Global options:** `--config PATH` (default: `speccheck.toml` in the current folder, then
  `[tool.speccheck]` in `pyproject.toml`), `--json`, `--quiet`, `--verbose`, `--version`.
- **Exit codes:** 0 fine, 1 problems found, 2 usage or config error. `verify` uses 1 for any
  failing requirement.
- **Output:** problems on stderr as `path:line: message`, so editors and CI logs link them; a
  one-line summary at the end ("12 requirements: 10 passed, 2 unimplemented"). `--json`
  prints one object with `schema_version`, `command`, `ok`, the result, and `problems`.
- **Step summary:** `lint`, `check` and `verify` take `--summary FILE` (see "Step summary").
- Only `cli.py` exits; actions return a code. Nothing but `results.py`, `summary.py` and `report.py` writes
  files.

### Shared code with platformctl

Not shared yet, on purpose (decided in review of #365, finding TECH-8). Of speccheck's
`actions/__init__.py`, `jsonout.py`, `output.py` and `context.py`, only `discover()` is identical to
platformctl's, about eight lines. The rest differs for a reason:

- `jsonout.py` and `output.py` keep CI log commands (`::`, `##[`), control characters and bidi
  overrides out of what is printed, and escape `--json` with `ensure_ascii`. platformctl's instead
  has error codes, a `platform` block, and a secret scrubber. Merging them risks weakening one.
- `context.py` holds different things (a spec folder and its config, against a platform's paths,
  adapters and target).
- A shared package would be a dependency of the agent template, and a path dependency breaks the
  template's Dockerfile (DEV-1 in the #365 review).

The trigger to extract is a **third consumer** of the same pieces. Until then, `discover()` carries
a comment pointing at platformctl's copy, so an edit to one reminds the editor of the other.

## Commands

| Command | Reads | Fails when |
|---|---|---|
| `lint` | the spec folder | a spec breaks the format (the #355 rules, minus `tests:` and citations) |
| `check` | specs, config, results files (from a collect-only run or a real one) | a requirement that isn't unimplemented has no claim; a claim names an unknown or removed ID, or one its producer may not claim; a claimed requirement is still marked unimplemented |
| `verify` | specs, config, the results files from a CI run | everything `check` fails on, plus: a claimed requirement with no passing result among the producers that reported; with `--complete`, a requirement no reported producer claims, or an expected producer that didn't report |
| `report` | the same as `verify` | never, unless the inputs are malformed: it writes the full markdown report (`--output`) or `--json` |
| `record` | config, the CI environment | the job has no `[ci.<job>]` entry; writes a results file with one passed result for each ID the job claims |

`check` is what you run locally:

```sh
pytest --collect-only -q --speccheck-results=.speccheck/collect.jsonl
speccheck check .speccheck/
```

## Config

TOML, read with `tomllib` (Python 3.11 or newer) or `tomli` on 3.10, which is a one-line
conditional dependency. One config describes one spec folder. Paths are relative to the config
file. It is `speccheck.toml`, or `[tool.speccheck]` in a project's `pyproject.toml` when a spec
folder belongs to one project.

```toml
specs = "specs"                 # the spec folder
id-prefix = "SPC"               # IDs are SPC-REQ-NNN-XX; "" for bare IDs
require-index = true            # 000-index.md must link every spec

[producers.speccheck-unit]      # a test run or a CI job that can provide evidence
specs = "all"                   # or ["001", "004"]: the specs it may claim
workflows = ["speccheck"]       # the workflows it runs in, for verify --complete

[ci.speccheck-self-check]       # a CI job that is itself evidence; `record` reads this
covers = { "SPC-REQ-007-02" = "the self-check job records only the IDs listed here" }

[report]
title = "speccheck requirements"
```

Decisions:

- **Producers are declared**, so `verify --complete` can tell "this job didn't upload" from
  "nothing claims this requirement", and so a job's `specs` limit replaces the old `tests:` line.
  A results file from an undeclared producer is a problem.
- **CI-job claims live in the config, not the workflow.** `record` looks up its job's IDs
  there, and `check` reads the same table, so the static check needs no YAML parser and there is
  one place to change. Renaming or deleting the job means `verify --complete` fails on a missing
  producer, so a claim can't outlive its job.
- No matrix setting: by default, one passing result in any job or leg is enough (agreed
  2026-11-01; "by default" leaves room for an "every leg" option later). The
  report lists every result.

## Claiming a requirement

```python
@pytest.mark.covers("SPC-REQ-004-01", "writes a results file and reads it back unchanged")
@pytest.mark.covers("SPC-BEH-004-02", "an unknown key in a result line is ignored, not rejected")
def test_results_file_round_trips():
    """A written results file reads back the same."""
```

- **One mark per ID, with how the test proves it** (decided 2026-11-02). The report shows the
  explanation next to each result, so a reviewer can tell whether the evidence fits the
  requirement without opening the test. It is required and positional: `covers(ID, how)`.
- **Where a mark may go:** on a test function that isn't parametrized, or on one
  `pytest.param(..., marks=...)` of the test's own single `@pytest.mark.parametrize`. A mark on a
  class or module, on the function of a parametrized test, on a test with two `parametrize`s, or
  on a test that uses a parametrized fixture fails collection. Every mark then lands on exactly
  one test, so "one explanation, one test" holds, and each case of a parametrized test says what
  it proves:

  ```python
  @pytest.mark.parametrize(
      ("body", "outcome"),
      [
          pytest.param(
              "assert False",
              "failed",
              marks=pytest.mark.covers("SPC-REQ-005-02", "a claiming test that fails makes the requirement failed"),
              id="failed",
          ),
          pytest.param(
              'pytest.skip("no")',
              "skipped",
              marks=pytest.mark.covers("SPC-REQ-005-02", "a skipped claiming test isn't evidence"),
              id="skipped",
          ),
      ],
  )
  def test_a_claim_that_didnt_pass_fails_verify(project, body, outcome): ...
  ```

  `marks=` takes a list when one case proves several requirements. The alternative, marks on
  every level with each claim recording where its mark was written, was dropped: it needs a
  `from` field from every writer, and a class-wide sentence says less than one per test.
- **The explanation:** whitespace is collapsed to single spaces, so a long one can span lines in
  the decorator. It is plain text, at most 1000 characters, and escaped wherever it is shown.
  Like node IDs, it goes into CI artifacts, so keep secrets out of it.
- **Rules, at collection** (SPC-REQ-003-02 to 003-16, on any run, locally too):
  - a mark takes exactly two strings;
  - the explanation isn't empty, too long, the ID itself, or a placeholder (`TODO`, `TBD`,
    `FIXME`, `...`, `-`);
  - a test claims each ID once;
  - no two claims in the session share an explanation, whatever their IDs;
  - with `speccheck_config` set in the pytest ini options (agreed 2026-11-01): the ID is
    well-formed, known, not removed and allowed for the producer, and the explanation isn't the
    text of any requirement in the folder.

  Texts are compared after collapsing whitespace, ignoring case and dropping a trailing full
  stop. `check` and `verify` repeat the uniqueness rule across every results file and
  `[ci.<job>]` entry, since one session sees only its own claims. Whether an explanation is a
  good one is left to review.
- The plugin registers the marker, so `--strict-markers` accepts it.
- A test with no `covers` mark is fine and is not recorded.
- **Requirement text is unique too:** `lint` fails on two requirements in one folder with
  the same text, compared without the unimplemented suffix (SPC-REQ-001-10).

## Results files

The interface between runners and the checker, so it is language-neutral and versioned. JSON
Lines: one header, then one line per claiming test.

```json
{"schema": "speccheck-results/1", "producer": "sdk-python", "runner": "pytest 8.4.1",
 "ci": {"provider": "github", "server": "https://github.com", "repository": "idaholab/prometheus_core",
        "workflow": "test", "job": "sdk-python", "job_id": 456,
        "run_id": 123, "run_attempt": 1, "job_url": "https://github.com/.../job/456",
        "sha": "abc..."},
 "root": "sdk", "started": "2026-11-01T12:00:00Z"}
{"test": "tests/test_llm_client.py::test_chat_proxy", "file": "tests/test_llm_client.py",
 "line": 181, "covers": [{"id": "SDK-REQ-006-08", "how": "a chat call goes through the proxy URL"}],
 "outcome": "passed"}
```

- **`covers`** is a list of `{"id", "how"}` objects. This changed within `speccheck-results/1`
  (2026-11-02), since nothing outside speccheck read the file yet. A reader rejects a result that
  claims an ID twice, or whose `how` is empty, over 1000 characters, or has a line break.

- **Outcomes:** `passed`, `failed`, `error`, `skipped`, `xfailed`, `xpassed`, `deselected`,
  `collected` (a `--collect-only` run). Only `passed` is evidence. `xpassed` is not, since the test
  says the behaviour is broken.
- A test's outcome merges its setup, call and teardown reports: a teardown error makes it `error`,
  a skip in setup makes it `skipped`.
- **Deselected and skipped tests are written too**, so `verify` can say "claimed here but didn't
  run" instead of "not claimed".
- `ci` comes from `GITHUB_*` variables, plus `SPECCHECK_JOB_ID`; `producer` comes from
  `SPECCHECK_PRODUCER`, which the workflow sets. Outside CI, `ci` is null and the file is only
  useful to `check`. There is no `leg`: a matrix value names one axis of one kind of job, so jobs
  are named by their display name instead, looked up by the final job (see "Job names").
- **`root`** is the folder `file` paths are relative to (pytest's root), as a path from the
  repository's root: `GITHUB_WORKSPACE` in CI, else git's top level, else null. The report uses it
  to link each test to its file.
- The file is written only when asked: `--speccheck-results=PATH` or `SPECCHECK_RESULTS`. A plain
  local `pytest` writes nothing.
- It is written atomically at session end, so a crashed run leaves no file. `verify --complete`
  then reports the producer as missing, and the job has already failed anyway.
- **pytest-xdist:** the controller sees every worker's reports, so the plugin writes from the
  controller only. Tested in step 1 even though nothing uses xdist yet.
- **Docker** (`sdk-docker` runs pytest inside the image): the results path must be in the mounted
  checkout. The CI variables are passed into the container with `-e`, except `GITHUB_WORKSPACE`,
  a host path; `SPECCHECK_ROOT` gives pytest's root in the repository instead (`sdk`), or the
  report loses every test link.

**Job links.** The report links each result to its job. The run URL
(`$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID/attempts/$GITHUB_RUN_ATTEMPT`)
is always available. A job-level URL needs the job's numeric ID, which the job's own environment
doesn't provide as a `GITHUB_*` variable. Step 1 checked whether `${{ job.check_run_id }}` is
available on our runners and, if so, passes it in as `SPECCHECK_JOB_ID`. Otherwise `verify` can
look up job IDs from the run's jobs API (`actions: read`) by name. If neither works, the link is the
run plus the job name.

**Outcome (2026-11-01, step 1):** GitHub documents `job.check_run_id` ("the check run ID of the
current job") in the `job` context on github.com. It is not available on GitHub Enterprise Server,
which we don't use. The check run ID is the number in a job's URL
(`.../actions/runs/<run>/job/<check_run_id>`). So every job that writes results sets
`SPECCHECK_JOB_ID: ${{ job.check_run_id }}`, and the results file's `job_url` links the job
directly. Each attempt's job has its own ID, so a re-run links its own job. When the variable is
missing or not a number, `job_url` falls back to the run attempt's URL. The jobs API lookup isn't
needed. Confirmed when `speccheck.yml` first runs: the report's job links open the right job.

**Job names (decided 2026-11-02).** A result is labelled with the display name of the job that
produced it, such as `speccheck: requirements python 3.12`, the name on the run page. A job can't
read its own display name (the `job` context has no name, and `GITHUB_JOB` is the job's ID), so
`speccheck-verify` looks them up once from the run's jobs API, which needs `actions: read`, and
writes a map of job ID to name. `report` and `verify` take it as `--job-names FILE` and find each
result's name by its `ci.job_id`. The map is optional: without it, or for a job not in it, a
result is named by its producer. The names come from GitHub, not from a results file, so a pull
request can't name a job it didn't run; they are escaped all the same. The alternative, each
workflow setting `SPECCHECK_JOB_NAME` to the same expression as its job's `name:`, needed no
permission but would drift when a job is renamed.
The report trusts only the shape and the base of a results file's URL. It links one only when it
is under the report job's own `GITHUB_SERVER_URL/GITHUB_REPOSITORY`; outside CI nothing is linked.

## How a requirement's status is decided

For each requirement, from the specs, the config and every results file in the inputs:

| Status | Means | Fails `verify`? |
|---|---|---|
| `passed` | at least one result for it passed | no |
| `failed` | claimed by a test that reported, and none passed (failed, skipped, deselected, ...) | yes |
| `not run` | claimed only by producers that didn't report in these inputs | only with `--complete` |
| `unclaimed` | nothing claims it, and it isn't unimplemented | yes |
| `unimplemented` | the spec marks it `(unimplemented: <reason>)`, and nothing claims it | no |
| stale suffix | marked unimplemented, but claimed | yes |

A removed ID isn't a requirement and has no status: it is a problem only when something claims it.

### Requirement states

Decided 2026-11-03, in review of #365. A requirement is in one of two states, so a requirement
without a test is always part of a plan:

- **Implemented**: no suffix. It needs a claim.
- **Unimplemented**: its text ends with `(unimplemented: <reason>)`, and the reason is required
  (a plan step, or anything that says why). The suffix may wrap with the bullet, and a full stop
  may come before or after it. Anywhere else in the text it is plain text. The report and
  `--json` show the text without the suffix and the reason beside the status, and duplicate
  texts are compared without it.

There is no "untested": behaviour that exists but has no test gets a test. More states can be
added later as more known words in the same `(<state>: <reason>)` form. Only known words are read,
so a trailing `(default: 30s)` stays text.

A requirement that goes is **deleted**, not retired, and its ID is listed on the spec's `removed:`
header line, which may wrap like a bullet. A listed ID can't be a requirement again, so it is
never reused, and a claim of it says which spec removed it. A whole spec that goes is listed by
number on `000-index.md`'s `removed:` line, and a file with that number is a problem.

The spec's `status:` line goes too: with `retired` gone and `draft` checked like `implemented`, it
said nothing. Every spec needs at least one requirement, and a planned spec marks each of its
bullets unimplemented. `lint` reports a leftover `status:` line, `⚠ untested`, `(planned: ...)`
and `Retired.`, each saying what replaces it.

`not run` is how path-filtered workflows and jobs that run only on `devel` (`publish-images`) fit
in. A PR checks what its jobs ran, and a complete check runs where every producer has reported
(see "Evidence across workflows").

## CI pattern

In each job that runs claiming tests:

```yaml
    env:
      SPECCHECK_PRODUCER: sdk-python
      SPECCHECK_RESULTS: ${{ github.workspace }}/.speccheck/sdk-python-${{ matrix.python }}.jsonl
    steps:
      # ...
      - run: uv run --frozen pytest
      - uses: ./.github/actions/speccheck-upload
        if: ${{ !cancelled() }}
        with:
          name: sdk-python-${{ matrix.python }}
```

And at the end of the workflow:

```yaml
  speccheck:
    needs: [sdk-python, sdk-docker, sdk-install]
    if: ${{ !cancelled() }}
    runs-on: ubuntu-26.04
    steps:
      - uses: actions/checkout@...
      - uses: ./.github/actions/speccheck-verify
        with:
          config: sdk/pyproject.toml
          complete: ${{ github.event_name != 'pull_request' }}
```

- **`speccheck-upload`** wraps `actions/upload-artifact` with the `speccheck-results-` name
  prefix (not `speccheck-`, so the report artifact and other `speccheck-*` artifacts are never
  read as results), 30 days' retention, and `if-no-files-found: error`, so a job that should have
  written results and didn't fails.
- **`speccheck-verify`** downloads every `speccheck-results-*` artifact of the run, writes the
  report (`report --output` and `--json`), uploads it as the `speccheck-report` artifact, then runs
  `verify --summary "$GITHUB_STEP_SUMMARY" --report-url <the upload's artifact-url>`. It runs even
  when a test job failed, so the report shows what was proven. Its exit code is `verify`'s.
- Both are composite actions in this repository, pinned like every other action in them, and
  checked by zizmor and actionlint.

## Requirements proven by CI jobs

Some requirements are a CI job rather than a test: an image builds for both architectures, the
wheel installs into a clean venv, devel images are published. #355 let a workflow comment claim
them, but a comment proves nothing ran.

Instead, the job claims them in the config (`[ci.<job>] covers = { "<ID>" = "<how>" }`, an
explanation per ID, checked like a test's) and records them as its last step, which runs only when the steps before it succeeded:

```yaml
      - uses: ./.github/actions/speccheck-install
      - name: Record speccheck evidence
        run: speccheck record --config sdk/pyproject.toml
      - uses: ./.github/actions/speccheck-upload
        if: ${{ !cancelled() }}
```

- `record` writes a results file with one `passed` result claiming each of the job's IDs with its
  explanation, with `test` set to the job name and `kind: "ci"`. The report shows it as a job, not a test.
- The `speccheck-install` action installs the `speccheck` command with `uv tool install` from the
  checkout, so a job that never set up uv for its own work can still record. (This replaced a
  `run.py` that ran the package from the checkout with the system Python.)
- A job that failed never reaches the step, so its IDs are `not run`. On a complete check they fail.
- **What this can't prove:** that the job checks what the requirement says. A job that records
  "image builds for arm64" could stop building arm64 and still record it. As with tests, the CI
  reviewer checks that the job really does what it claims.

## Evidence across workflows

A workflow's final job sees only its own run's artifacts. That is enough for a spec folder whose
evidence all comes from one workflow (speccheck, and the sdk in `test.yml`), but not for the build
and run specs, whose evidence comes from `platformctl.yml`, `test.yml` and `publish-images`.

For those, a separate workflow (`speccheck-report.yml`, added in step 2 when it is first needed)
runs on `workflow_run` completion of the listed workflows on `devel`, and on a schedule. For one
commit, it finds the latest successful run of each, downloads their `speccheck-*` artifacts with
`gh run download`, and runs `verify --complete` and `report`. It runs with `actions: read` only,
and treats every downloaded file as untrusted data (see "Security").

PRs keep the per-workflow, partial check. That is answer (b) from 2026-11-01: static checks on
every run, the runtime check in the final job, complete where every producer reports.

## Report

`report` writes one markdown document, one section per requirement (decided 2026-11-02, after a
first version with one table per spec read badly with long text):

- the title, a summary line and a count per status;
- **Specs:** a table with a link to each spec, its number of requirements and its count per status;
- **one section per spec** (`##`): its title, its Purpose paragraph, and a table of its
  requirements' IDs (each linking to its section) and statuses, `failed`, `unclaimed` and
  `not run` first;
- **one section per requirement** (`###`, in spec order): `ID ✅ status` as the heading, the full
  text quoted, and a link to its line in the spec file;
- **one section per claiming test or CI job** (`####`): the test's name linking to its line in its
  file, then the file's path; **How:** and the explanation; then one line per result, worst
  outcome first, naming the job by its display name and linking to it;
- a requirement with no claims says what it waits on, or to claim it or add
  `(unimplemented: <reason>)`;
- an unimplemented requirement shows its reason beside its status;
- the inputs it was built from: commit, run, and which producers reported or were missing.

```markdown
### SPC-REQ-001-01 ✅ passed

> A spec file MUST be named `NNN-short-name.md`, and its first line MUST be its title, …

In [`common/speccheck/specs/001-spec-format.md:12`](…/blob/<sha>/common/speccheck/specs/001-spec-format.md#L12)

#### Test [`test_file_names_and_titles`](…/blob/<sha>/…/test_001_spec_format.py#L22) in `common/speccheck/tests/requirements/test_001_spec_format.py`

**How:** lint reports a `Notes.md` in the folder as misnamed, and a spec titled `# 2 -` instead of `# 002 -` at line 1

- ✅ passed in [speccheck: requirements python 3.10](…/job/125530458936)
- ✅ passed in [speccheck: requirements python 3.11](…/job/125530459354)
```

**Escaping.** Everything from a results file, a spec or the job names is written so it can only
be text: code spans are kept as written (with any backtick that would close one dropped), and
outside them only what can make a link, image, autolink, HTML or emphasis is escaped, plus a
leading `#`, `>`, `-` or `1.` where text starts a line. The first version escaped every `.` and
`-`, which was safe but hard to read in the raw file.

**Source links.** In CI, spec and test lines link to `<server>/<repository>/blob/<sha>/<path>#L<n>`,
where the server, repository and commit are the run's own (`GITHUB_SERVER_URL`,
`GITHUB_REPOSITORY`, `GITHUB_SHA`), never a results file's. A spec's path is the config's folder
from the repository's root; a test's is the results file's `root` plus its `file`. A path is
linked only when it is plain (letters, digits, `.`, `_`, `-`, `/`, no `..`). Outside CI nothing is
linked. A parametrized test's cases all link to the line pytest gives, the `parametrize` (or its
first decorator), since pytest doesn't track each `pytest.param`'s line.

The report is the artifact and the place to read everything. `--json` gives the same data for
other tools, with each requirement's `path` and `line` and each result's `job_name`.

## Step summary

The step summary shows only what failed (decided 2026-11-02). `lint`, `check` and `verify` take
`--summary FILE` and append one line, then one list entry per problem, and nothing else:

> **speccheck:** 2 problems. 48 requirements: 1 failed, 1 unclaimed, 2 not run, 38 passed, 6 unimplemented. Full report: [speccheck-report](…)
>
> - SPC-REQ-004-01 failed in `tests/requirements/test_004_results.py::test_round_trip` ([job](…))
> - SPC-REQ-006-03 is not claimed; add `@pytest.mark.covers("SPC-REQ-006-03", "…")` to a test that proves it

- On a pass, the line alone, without the problem count. It is the way to the artifact from the
  run page, and an empty summary would look like a step that never ran.
- The counts are the terminal's summary line. `check` shows `claimed` where `verify` shows
  `passed`. `not run` without `--complete` is counted but not listed, since it isn't a failure.
- `--report-url URL` links the report, only when it has the form of an artifact link on the run's
  own server and repository. Otherwise the line has no link.
- Everything is escaped as in the report and the whole stays under GitHub's 1 MiB limit, cut
  after a whole entry, with a note, when it doesn't fit.
- `report --summary` is gone: one summary format, written by the commands that decide failure.

## speccheck's own specs

`common/speccheck/specs/`, prefix `SPC`, in the same format as every other folder, written in
step 1 alongside the code:

| Spec | Covers |
|---|---|
| 001 Spec format | files, index, bullets, the unimplemented suffix, removed IDs, prefix, what `lint` rejects |
| 002 Config | file discovery, keys, validation, errors |
| 003 Claims | the `covers` marker, where it may go, explanations, the collection check |
| 004 Results files | format, outcomes, merging phases, xdist, writing only when asked |
| 005 Evidence and verify | the status table above, partial and complete checks |
| 006 Report | the per-requirement layout, job names, source links, escaping, `--json` |
| 007 CI jobs | `record`, the two composite actions |
| 008 The command line | actions, global options, exit codes, `--json` envelope, the step summary |

speccheck's requirements tests (`tests/requirements/`, one file per spec) claim them with the
marker, and `speccheck.yml` ends with the same `speccheck-verify` job as every other workflow. Its
unit tests (`tests/unit/`) claim nothing and are the only tests measured for coverage. A requirement such as "a skipped test is not
evidence" is proven by a test that runs the plugin through `pytester` on a skipped inner test,
while the outer run records that test as passed.

**Coverage with its own plugin:** pytest loads entry-point plugins before pytest-cov starts, so the
plugin's import-time lines would be missed. speccheck's unit tests run under `coverage run -m pytest`,
which starts first.

## Packaging

- Distribution `prometheus-speccheck`, import name `speccheck`, console script `speccheck`, and a
  `pytest11` entry point for the plugin. The plugin does nothing until a project sets
  `speccheck_config` or passes `--speccheck-results`.
- Each project that uses it adds `prometheus-speccheck = { path = "../../common/speccheck" }` (or
  the right relative path) to its dev dependency group and `[tool.uv.sources]`. Its `uv.lock`
  changes (agreed 2026-11-01). Projects that copy the sdk into a Docker image need the path inside
  the image too. Step 3 deals with that for `sdk-docker`.
- `requires-python >= 3.10`. Dependencies: `tomli; python_version < "3.11"`. pytest is not a
  dependency, since the plugin is only imported by pytest.
- Dependabot watches `common/speccheck` for its dev tools, as in #355.

## Python versions

CI runs platformctl's tests on 3.10 to 3.14 and the sdk, agent template and backend on 3.12 to
3.14. speccheck runs inside those pytest sessions, so it supports 3.10 and newer, and its own
workflow tests every version from 3.10 to 3.14. The only 3.10-specific code is the TOML import.

## Security

- Results files and downloaded artifacts are untrusted data, since a PR controls what its tests
  write. They are parsed as JSON only, with a size limit, and never executed. Paths in them are
  never opened.
- Everything printed from them goes through the control-character escaping (CI logs act on lines
  starting with `::`), and everything put into markdown is escaped.
- `speccheck-verify` and `speccheck-report.yml` run with `contents: read` (and `actions: read`
  where they download another run's artifacts), no secrets, `persist-credentials: false`.
- `workflow_run` runs with the base repository's permissions on artifacts a fork may have written.
  It must keep to read-only permissions and treat the artifacts as data, and the review checks
  both.

## Vitest (later, step 5)

Possible without changing the checker: a vitest reporter writes the same results file.

- **The reporter:** vitest's custom reporter API reports each test case's result at the end of a
  run, so a small reporter module (shipped from `common/speccheck/vitest/`, or as a local npm
  package) can map vitest states (`pass`, `fail`, `skip`, `todo`) onto the outcomes above and
  write the file.
- **The claim:** vitest has no markers. Options, to choose in step 5 against the vitest version in
  use then (the frontend is on vitest 4.1):
  1. per-test metadata (vitest has a task `meta` object a reporter can read), set by a
     `covers("FE-REQ-001-01", "how")` helper inside the test;
  2. the ID in the test's name or tag, which every reporter can read.

  Option 1 is closer to the pytest marker. It needs checking that the metadata reaches the
  reporter for tests that are skipped or filtered out, not just ones that ran. Either way the
  pytest rules carry over: an explanation per ID, a claim inside one `it`/`test` (never on a
  `describe`), one per case of `test.each`, and unique explanations.
- **The collection check** happens in `speccheck check` instead of at collection, unless vitest's
  reporter hooks run early enough.
- **Before any of this:** the frontend has no spec folder yet. Step 5 starts by writing one, or is
  deferred until someone does.

## Other spec folders in the repository

Found on `devel` as of 2026-11-01:

| Folder | What | Plan |
|---|---|---|
| `sdk/specs/` | 14 SDD specs, about 260 REQ/BEH IDs, 20 marked `⚠ untested` and 7 `Retired.`; about 43 IDs are cited in tests, in docstrings or in plain comments | step 3 (step 4 folded in) |
| `build/specs/` (on #355/#361 only) | the build and run specs: index and 8 platformctl specs | step 2 |
| `sdk/docs/SDD_SPEC_AUTHORING.md`, `SDD_TESTING_STANDARD.md` | the format and the testing rules | step 3 moves the checked rules into speccheck's README and points these docs at it |
| `platform/backend/CONTRACT.md`, `platform/frontend/AGENT-CONTRACT.md` | wire contracts in prose, with no IDs | out of scope. They could become spec folders later, which is when step 5 matters |

## Open questions

- Artifact retention for `speccheck-*` (30 days?), and whether the report artifact is kept longer.
- Whether `speccheck` (the final job) becomes a required check, and when. Not before step 3.
  `speccheck.yml` is path-filtered, so it can't be required as it stands: a path-filtered required
  check stays "Expected" forever on a PR that touches none of those paths, and blocks it. Promotion
  needs the path filter dropped or an always-run job that reports for every PR, such as a job that
  skips its work when no speccheck path changed but still passes.
- Whether `verify --complete` on `devel` pushes is enough, or a nightly run is also wanted.
- **Promotion criterion** for making `speccheck` a required check (after step 3 and the path-filter
  change above). "Green on `devel` for a while" can't be counted in days, because the workflow runs
  on `devel` only when a speccheck path changes. It is met when:
  - the last 10 runs of `speccheck.yml` on `devel` that touched speccheck paths are green, and
  - the final job of every adopter's workflow (step 3 onward) has been green on its last 10 `devel`
    runs, or, if the nightly run above is added, on 14 nightly runs in a row.
  A scheduled run would make the second condition a count of days, and is the alternative if the
  adopters' runs are too sparse.
- Whether the report is also published somewhere permanent (the docs site, a PR comment), not
  just as an artifact.
