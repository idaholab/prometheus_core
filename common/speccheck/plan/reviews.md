# speccheck: reviews for each step

Before a step's PR is merged, run the review panel on it: `/review-panel <PR number> with
<reviewers>`. The skill lives in `.claude/skills/review-panel/` (on `devel`). It runs one
fresh-context agent per reviewer in parallel, checks each blocker and major finding against the
code, and writes one report that can be posted as a PR comment. It holds the reviewer briefs, so
they are not repeated here.

## How to run it

- Name the reviewers from the table below in the request, for example
  `/review-panel 380 with technical, CI and tests, security, AI skills`. Naming them skips the
  question about who should review.
- Name the step's file (`common/speccheck/plan/<step>.md`) and `design.md` as background, so the
  reviewers know what the step promised. It is context, not the thing under review.
- Reviewer names are the panel's: user, agent developer, technical, frontend, backend, agent,
  CI and tests, security, rollout, Linux/WSL, AI skills.

## Which reviewers each step needs

| Step | Reviewers | Why |
|---|---|---|
| 1 speccheck | technical, CI and tests, security, AI skills | new package and pytest plugin; new workflow and composite actions; parses untrusted artifacts; agents will write markers and read `--json` |
| 2 Build specs | technical, CI and tests, security, rollout, user | lock and workflow changes to platformctl; `workflow_run` across workflows; the specs are written for users |
| 3 sdk adoption | technical, CI and tests, agent developer, AI skills, rollout | renames every sdk ID; changes `test.yml` and `sdk-docker`; agent authors and skills cite these IDs |
| 4 sdk evidence | technical, CI and tests, agent (008 to 012), agent developer | whether each claim proves its requirement |
| 5 vitest | frontend, technical, CI and tests, security | a TypeScript reporter in the frontend's toolchain |

A step can add reviewers or drop one. Update this table when a step's scope changes.
Linux/WSL is not listed: nothing here is a command users run by hand on their machines. Add it if
that changes.

## What this plan adds to the briefs

The panel's briefs are general. When a step touches one of these, say so in the request, so that
the reviewer looks at it:

- **Technical:**
  - the action layout matches platformctl's (`NAME`, `HELP`, `SECTION`, `ORDER`, `add_arguments`,
    `run`), and adding a command is adding a file;
  - the outcome merge across setup, call and teardown, and that only `passed` counts;
  - the plugin does nothing until configured, and never changes a test's outcome;
  - Python 3.10 (`tomli`) and the newest Python both work;
  - the results format is versioned, and a reader rejects an unknown version instead of guessing.
- **CI and tests:**
  - above all, a test or job that claims a requirement without proving it. The checker sees
    that a test claims an ID and passed, not that it asserts what the requirement says;
  - the final job runs when a test job fails (`!cancelled()`), and fails when a producer didn't
    upload (`--complete`, `if-no-files-found: error`);
  - a skipped, deselected or xfailed claim really fails `verify`, tested end to end with
    `pytester`, not only in units;
  - coverage still counts the plugin's import-time lines (`coverage run -m pytest`);
  - path filters include `common/speccheck/**` and the spec folder in every workflow that uses
    them;
  - the job links open the right job, including on a re-run attempt.
- **Security:**
  - results files and artifacts are untrusted: parsed as JSON only, size-limited, paths never
    opened, control characters escaped in logs, markdown escaped in the report and summary;
  - the composite actions and `speccheck-report.yml` have read-only permissions, no secrets and
    `persist-credentials: false`; `workflow_run` doesn't hand a fork's artifacts anything with
    write access;
  - actions are pinned by hash, zizmor and actionlint are clean.
- **AI skills:**
  - `--json` output is stable and complete (schema version, statuses, problems, exit codes);
  - problem messages say what to do, so an agent can fix a spec or a marker from the message
    alone;
  - the docs and skills that tell agents how to claim a requirement match the marker, and none
    still teach the docstring form.
- **Agent developer / agent (steps 3 and 4):** the `SDK-` rename reaches every place an agent
  author reads an ID (sdk docs, agent template, skills), and each claim in the agent specs
  (008 to 012) is proven by a test of the agent behaviour, not of a helper.
- **Rollout (steps 2 and 3):** the ID rename and the marker switch land in one PR per folder,
  open PRs that cite old IDs are listed, and the final job is not made required until it has been
  green on `devel` for a while.
- **User (step 2):** the build and run specs read as promises to someone running the platform,
  not as implementation notes.
- **Frontend (step 5):** the reporter and helper fit the frontend's vitest setup, lockfile and
  Docker build, and don't slow `npm run test` noticeably.
