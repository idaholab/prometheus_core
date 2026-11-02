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

The header lines are read only above the first `##`, so an example further down can't override them,
and a second `status:` or `tests:` line is a problem.

`tests:` paths are relative to `--root` (default: the current folder), comma-separated, or `none`.
A path that doesn't exist is a problem, so a moved test folder can't silently drop every citation.

**IDs and the prefix.** An ID is `REQ-NNN-XX` or `BEH-NNN-XX`, where `NNN` is the spec's own number.
Two folders that both number their specs from 001 would reuse the same IDs, so a folder can give its
IDs a prefix with an `id-prefix:` line in `000-index.md`, above its first `##`:

```markdown
id-prefix: BLD
```

Its IDs are then `BLD-REQ-NNN-XX` and `BLD-BEH-NNN-XX`, in the specs and in every citation. The
prefix is capital letters and digits, starting with a letter. With a prefix, a bare `REQ-004-07` in a
test is not one of this folder's IDs and is ignored, and without one a prefixed ID is ignored. Folders
with no `id-prefix:` line (such as `sdk/specs/`) keep bare IDs.

**Bullets.** `- REQ-NNN-XX: text` and `- BEH-NNN-XX: text`, with the prefix if the folder has one. A
bullet may wrap onto lines indented by two spaces. Markers at the end of the text:

| Marker | Means |
|---|---|
| `⚠ untested` | No test yet, and none is planned. Say why under Open questions |
| `(planned: step 3b)` | Agreed, and delivered by a later step of a plan. That step removes it |
| Text starting `Retired.` or `Retired:` | No longer applies. The ID stays for history and is never cited |

A whole spec with `status: retired` counts as retired.

A list item that starts with an ID in any other style (`* REQ-...`, `- **REQ-...**`, `+ REQ-...`, or
a nested `  - REQ-...`) is reported as a malformed bullet instead of being skipped, so a requirement
can't escape the checker by its formatting. Fenced code blocks (``` or ~~~) are ignored, so a spec
can show the format as an example.

**Citations.** A full ID in a file under the spec's `tests:` paths counts only where a reader would
look for it, so a stray mention can't pass for a test:

- **Python:** the docstring of a `test_*` function or method, or a `# Covers` comment. A module
  docstring, a helper's docstring, a string, or any other comment is not a citation. A file that
  doesn't parse is a problem, because its citations can't be read.
- **Any other language:** a line with `Covers` before the ID, such as `// Covers BLD-REQ-003-04`.
- **Workflows:** see below.

```python
def test_set_refuses_secret_keys():
    """Covers BLD-REQ-003-04: --set names .env instead of taking the value."""
```

Caches (`__pycache__`, `node_modules`, `.venv`, ...) and binary files are skipped.

`Implements` is only for a workflow job that is the behaviour. In a test file it is a problem, not
evidence, so an author who writes it learns that a test cites with `Covers`.

A citation shows that a test names the requirement, not that it skipped, asserts anything or proves
it; that stays a review question. Specs that share a `tests:` folder share its evidence, so name the
narrowest files and folders on each spec's `tests:` line.

**Workflows.** In `.github/workflows/*.yml`, an ID only counts in a comment inside a job, below its
key, starting with `Covers` (the job checks the requirement) or `Implements` (the job is the
behaviour, such as a publish job):

```yaml
jobs:
  compose-config-unchanged:
    # Covers BLD-REQ-007-12: the merged compose config is identical to the old Makefile's
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
- `Implements` before an ID in a test file.
- A duplicate ID, a malformed bullet (including one without the folder's prefix), an ID numbered for
  another spec, a malformed `id-prefix:`, a missing, repeated or unknown `status:`, a missing `tests:`, a title without the number, a file not named `NNN-name.md`, or a
  spec the index doesn't list.

`draft` doesn't relax anything: a draft spec's requirements are planned, untested or cited, like any
other. What the checker can't tell is whether a citing test really proves the requirement, or is
skipped; that is a review question.

## Use it from a project

Run it from one of the project's own tests, so it fails with the rest of them. For example, in a
pytest project:

```python
def test_specs():
    """The build and run specs and their citations follow common/speccheck's rules."""
    repo = Path(__file__).resolve().parents[N]
    done = subprocess.run(
        [sys.executable, "-I", str(repo / "common/speccheck/speccheck.py"), "--specs", "build/specs"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
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
