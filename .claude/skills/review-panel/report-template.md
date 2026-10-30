# Review panel report format

Every run produces one report in this format. It's shown in the terminal and is ready to post
as a PR comment, so use GitHub Markdown only: no terminal colours, and no HTML except
`<details>`.

## Rules

- **Heading:** `## Review panel: <short title>`.
- **Intro:** one or two sentences: what the change does, the target (the diff command and the
  head commit), and whether the code was checked out or only the diff was reviewed. For a
  merged PR, add "Merged: fixes go in a follow-up PR." For a draft PR, add "Draft."
- **Reviewer table:** one row per reviewer that ran, ordered from the most severe finding down.
  - **Why** takes a few words, not a sentence: the reason from step 2, or "named by the user".
  - **Ran** lists the commands or suites run locally, or "read only". Write a suite that wasn't
    rerun because it passed in CI as "CI: <job>" with a link.
  - **Findings** gives counts, such as `1 major, 2 minor`, or `none`.
- **Not on the panel:** one line with the proposed reviewers that didn't run, and how to rerun
  with them. Leave the line out when none were left out.
- **One `###` section per reviewer**, in the same order as the table:
  - A findings table, most severe first. IDs are `<prefix>-<n>` and stay stable, so that a
    reply can say "fixed SEC-1". The prefixes are `USER`, `DEV`, `TECH`, `FE`, `BE`, `AGENT`,
    `CI`, `SEC`, `ROLL`, `OS`, `AI`, and a short one for a custom reviewer.
  - **Severity** is `blocker`, `major`, or `minor`.
  - **Checked** says what you found when you verified the finding. A blocker or major
    finding is `confirmed` (with how), `not reproduced` (with why), or `unchecked` (with why).
    A minor finding can say `read` or `spot-checked`.
  - **A duplicate** gets one row: "Same as CI-2", plus anything this reviewer added.
  - **No findings:** write "No findings." in place of the table.
  - Then up to two lines, each only when there's something to say: **Works well:** (at most
    three short items) and **Not covered:** (checks this reviewer couldn't run, and why).
  - Technical also has **Contradictions:** (file:section vs file:section) when it found any.
- Keep a finding to one or two sentences, with a `file:line` in **Where**. Put long evidence,
  such as logs or a reproduction, in a `<details>` block under that reviewer's table.

## Example

```markdown
## Review panel: PR 280: alembic check CI job

Adds a `platform: backend alembic check` job that upgrades a pinned Postgres to head and runs
`alembic check`. Target: `gh pr diff 280` at `0c62494`, diff only (no worktree). Merged: fixes go
in a follow-up PR.

| Reviewer | Why | Ran | Findings |
|---|---|---|---|
| CI and tests | adds a CI job | alembic upgrade/check mutations on Postgres; CI: [backend python, alembic check](https://github.com/idaholab/prometheus_core/pull/280/checks) | 1 major, 2 minor |
| Security | `.github/workflows/**` | sentinel grep, zizmor | 2 minor |

Not on the panel: Backend, Rollout (proposed). Rerun with `/review-panel 280 with backend, rollout`.

### CI and tests

| # | Severity | Finding | Where | Fix | Checked |
|---|---|---|---|---|---|
| CI-1 | major | `alembic check` ignores server defaults, so a changed `server_default` without a migration passes. | `platform/backend/alembic/env.py:84` | Pass `compare_server_default=True` to `context.configure`. | confirmed: the mutation passes without the flag and fails with it |
| CI-2 | minor | The Postgres digest is copied from compose, and nothing keeps the copies equal. | `.github/workflows/test.yml:665` | Check it in `check_image_pins.py`. | read |
| CI-3 | minor | No `timeout-minutes`, so a hang runs for 6 h. | `.github/workflows/test.yml:650` | `timeout-minutes: 10` | read |

**Works well:** a 33 s job; it's a required check; actions and images are pinned.
**Not covered:** `check_image_pins.py` needs `.git`, and the export has none.

### Security

| # | Severity | Finding | Where | Fix | Checked |
|---|---|---|---|---|---|
| SEC-1 | minor | Same as CI-2. A Postgres security fix would also skip this job. | | | |
| SEC-2 | minor | The service port is published on every interface. | `.github/workflows/test.yml:671` | `127.0.0.1:5432:5432` | read |

**Works well:** `pull_request` (not `_target`), `contents: read`, no secrets in scope.
```
