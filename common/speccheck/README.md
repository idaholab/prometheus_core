# speccheck

Checks a folder of SDD specs against the tests and CI jobs that prove them. The spec format is
[`sdk/docs/SDD_SPEC_AUTHORING.md`](../../sdk/docs/SDD_SPEC_AUTHORING.md); this tool enforces the
traceability rules in it and in
[`SDD_TESTING_STANDARD.md`](../../sdk/docs/SDD_TESTING_STANDARD.md).

Standard library only, Python 3.10 or newer, one file. It has no dependencies, so a project uses it
by path and nothing is added to its `uv.lock`.

```sh
python3 common/speccheck/speccheck.py --specs build/specs            # from the repository root
python3 common/speccheck/speccheck.py --specs build/specs --report   # also list each ID's evidence
```

Problems go to stderr as `path:line: message`, and the exit code is 1 if there are any (2 for a
usage error). `--report` prints one line per ID on stdout: `test`, `ci` or `implements` with where
it's cited, or `untested`, `planned` or `retired`.

## What it reads

**Specs.** Every `NNN-name.md` in the folder, plus `000-index.md`, which must list each spec's
number. Each spec has a title `# NNN - Name`, a `status:` line (`draft`, `implemented` or
`retired`) and a `tests:` line naming where its IDs may be cited:

```markdown
# 003 - Secrets

status: draft
sources: platform/ctl/platformctl/output.py
tests: platform/ctl/tests, .github/workflows/platformctl.yml
depends-on: 002
```

`tests:` paths are relative to `--root` (default: the current folder), comma-separated, or `none`.
A path that doesn't exist is a problem, so a moved test folder can't silently drop every citation.

**Bullets.** `- REQ-NNN-XX: text` and `- BEH-NNN-XX: text`, where `NNN` is the spec's own number. A
bullet may wrap onto lines indented by two spaces. Markers at the end of the text:

| Marker | Means |
|---|---|
| `⚠ untested` | No test yet, and none is planned. Say why under Open questions |
| `(planned: step 3b)` | Agreed, and delivered by a later step of a plan. That step removes it |
| Text starting `Retired.` | No longer applies. The ID stays for history and is never cited |

A whole spec with `status: retired` counts as retired.

**Citations.** Any mention of a full ID in a file under the spec's `tests:` paths, in any language:

```python
def test_set_refuses_secret_keys():
    """Covers REQ-003-04: --set names .env instead of taking the value."""
```

A line with `Implements` before the ID counts as a pointer to the behaviour, not a test of it; the
report shows the difference. Caches (`__pycache__`, `node_modules`, `.venv`, ...) and binary files are
skipped.

**Workflows.** In `.github/workflows/*.yml`, an ID only counts in a comment inside a job, below its
key, starting with `Covers` (the job checks the requirement) or `Implements` (the job is the
behaviour, such as a publish job):

```yaml
jobs:
  compose-config-unchanged:
    # Covers REQ-007-12: the merged compose config is identical to the old Makefile's
    runs-on: ubuntu-26.04
```

Jobs are found by indentation under `jobs:`, so a citation in a deleted or renamed job, at the top of
the file, or in a step's text is a problem rather than silent evidence.

## What fails

- A requirement that no test cites and that is neither `⚠ untested`, planned nor retired.
- `⚠ untested` or `(planned: ...)` on a requirement that a test cites: remove the marker.
- A requirement that is both planned and untested.
- A citation of an ID that is in no spec, is retired, or belongs to a spec whose `tests:` don't
  include the citing file.
- A duplicate ID, a malformed bullet, an ID numbered for another spec, a missing or unknown
  `status:`, a missing `tests:`, a title without the number, a file not named `NNN-name.md`, or a
  spec the index doesn't list.

`draft` doesn't relax anything: a draft spec's requirements are planned, untested or cited, like any
other. What the checker can't tell is whether a citing test really proves the requirement; that is a
review question.

## Use it from a project

Run it from one of the project's own tests, so it fails with the rest of them. For example, in a
pytest project:

```python
def test_specs():
    """The build and run specs and their citations follow common/speccheck's rules."""
    repo = Path(__file__).resolve().parents[N]
    done = subprocess.run(
        [sys.executable, "-I", str(repo / "common/speccheck/speccheck.py"), "--specs", "build/specs"],
        cwd=repo, capture_output=True, text=True, check=False,
    )
    assert done.returncode == 0, done.stderr
```

Add `common/speccheck/**` and the spec folder to that project's CI `paths:` filter, if it has one,
so a change to the checker or the specs reruns it.

## Tests

```sh
cd common/speccheck
python3 -m unittest -v
uvx ruff@0.17.3 check . && uvx ruff@0.17.3 format --check .
```

CI (`.github/workflows/speccheck.yml`) runs them on Python 3.10 and 3.14 and requires 100% line and
branch coverage (`.coveragerc`).
