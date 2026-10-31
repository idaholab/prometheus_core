# platformctl: reviews for each step

Before a step's PR is merged, run the review panel on it: `/review-panel <PR number> with
<reviewers>`. The skill lives in `.claude/skills/review-panel/` (on `devel`). It runs one
fresh-context agent per reviewer in parallel, checks each blocker and major finding against the
code, and writes one report that can be posted as a PR comment. It holds the reviewer briefs, so
they are not repeated here.

## How to run it

- Name the reviewers from the table below in the request, for example
  `/review-panel 330 with technical, CI and tests, security`. Naming them skips the question
  about who should review. The skill's own proposal is a fallback.
- Name the step's file (`platform/plans/platformctl/<step>.md`) as background, so the reviewers
  know what the step promised. It is context, not the thing under review.
- Reviewer names are the panel's: user, agent developer, technical, CI and tests, security,
  rollout, Linux/WSL, AI skills.

## Which reviewers each step needs

| Step | Reviewers |
|---|---|
| 1 Scaffold | technical, CI and tests, security, Linux/WSL, AI skills |
| 2 Port the scripts | all eight |
| 3a Forward compose | all eight |
| 3b Labels, your agents | all eight |
| 3c Groups and docs | all eight |
| 4 Doctor | all eight |
| 5 Contributor docs | user, technical, AI skills |
| 6 Fix existing docs | user, agent developer, AI skills |
| 7 Agent folders | all eight |
| 8 k3d target | technical, CI and tests, security, rollout, Linux/WSL |
| 9 Platform images | technical, CI and tests, security, rollout, agent developer |

A step can add reviewers (the panel also has frontend, backend and agent), or drop one. Update
this table when a step's scope changes.

## What this plan adds to the briefs

The panel's briefs are general. When a step touches one of these, say so in the request, so that
the reviewer looks at it:

- **Technical:** precedence (defaults < environment < `.env` < `--set`, Make's variables via
  `MAKEFLAGS`), the compose entry file and `.platform.env`, labels, signals and the terminal, and
  that actions are tested against the fake target with the Compose argv pinned only in the
  compose target.
- **Security:** the secrets canary (`tests/unit/test_secrets_canary.py`) covers every new command
  and code path; `--verbose`, `--dry-run`, `--json` and `--debug` never print a secret.
- **AI skills:** `--json` output stays stable and complete (schema version, fields, errors, exit
  codes), and every new command runs without a terminal (`--yes`, no following, timeouts).
- **Rollout:** `breaking-changes.md` is complete for the step, and nothing switches docs or
  slides to a command from a later step.
