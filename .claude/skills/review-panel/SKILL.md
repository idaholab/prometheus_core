---
name: review-panel
description: Reviews a prometheus_core change from several perspectives at once, with one independent reviewer agent per perspective (user, agent developer, technical, frontend, backend, agent, CI and tests, security, rollout, Linux/WSL, AI skills). It proposes the reviewers that fit what the change touches, lets you confirm or add more, runs them in parallel, checks their blocker and major findings against the code, and writes one report in a fixed format that can be posted as a PR comment. Use it whenever someone wants a review from more than one angle or from a named perspective, such as "run the review panel", "get the reviewers on PR 312", "review this branch as a user and from security", "have the frontend and backend people look at this", or "review this plan step", even when the word "panel" isn't used. For a quick single-pass bug check of a diff, the built-in /code-review fits better.
argument-hint: "[PR number, branch, range, or path] [with <reviewers>]"
---

# /review-panel

Review a change with one fresh-context agent per perspective. The argument: `$ARGUMENTS`

Next to this file:
- `reviewers/`: one brief per reviewer.
- `shared-context.md`: given to every reviewer.
- `report-template.md`: the format of the final report and the PR comment.

## 0. Check the model

A panel is expensive. Every reviewer is a separate agent that reads the code and runs commands,
and by default each one runs on the same model as this session. In testing, a panel of two
reviewers used about 75k tokens, so a full panel of eight to eleven costs several times that.

If this session runs on an Opus model (or another large, expensive model), warn the user before
step 1, and ask (header `Model`): "This review panel runs one agent per reviewer on <model>,
which can be expensive. How should it run?" Options:
- "Run the reviewers on Sonnet (Recommended)": the reviewers get `model: "sonnet"`. This session
  still proposes the reviewers, checks their findings, and writes the report.
- "Stop, and I'll switch to Sonnet": say to run `/model sonnet` and then the same `/review-panel`
  command again.
- "Continue on <model>": no change.

On Sonnet, Haiku, or another smaller model, skip this step and don't mention it.

## 1. Find the change

Work out the target from the argument.

**A PR number.** Run `gh pr view <n> --repo idaholab/prometheus_core --json
number,title,body,state,headRefName,headRefOid,isCrossRepository,mergeCommit,commits`.
- The diff is `gh pr diff <n> --repo idaholab/prometheus_core`. `gh pr diff` has no `--stat`, so
  get the file stats with `gh pr diff <n> --repo idaholab/prometheus_core | git apply --stat`.
- The code under review is the head commit, `headRefOid`. A fork's branch or a deleted branch
  doesn't matter: `git fetch upstream pull/<n>/head` gets the commit either way.
- **Merged PR:** review it the same way, against its head commit. Fixes can only go in a
  follow-up PR, so say that in the report.
- **Draft PR:** review it the same way, and say "Draft" in the report intro.
- **Closed without merging:** say so, and ask whether to go on.

**No argument, a branch, or a range.** The diff is `git diff <base>...HEAD`,
`git diff <base>...<branch>`, or `git diff a...b`, and `--stat` works. `<base>` is
`upstream/devel` if that remote exists, else `origin/devel`. Fetch it first, so that the diff
isn't against a stale base.

**A path** (a plan, a doc folder): there's no diff. The reviewers review the files themselves.

**Is the code checked out here?** Yes when `git merge-base --is-ancestor <head commit> HEAD`
succeeds and the working tree is clean. If not, the `Checkout` question in step 3 offers:
- a throwaway worktree: `git worktree add --detach "$TMPDIR/review-<n>" <head commit>`, removed
  at the end with `git worktree remove`;
- the diff only. The reviewers can still read any file at the head commit with
  `git show <head commit>:<path>`, and run things in an export
  (`git archive <head commit> | tar -x -C "$TMPDIR/review-<n>-src"`). An export has no `.git`,
  so checks that call git fail there. The reviewers list those checks under "Not covered"
  and don't report them as findings.

**CI results.** Find out what CI already ran on the head commit, so that the reviewers don't
run it again. For a PR, use `gh pr checks <n> --repo idaholab/prometheus_core --json
name,bucket,link`. For a branch that has been pushed, use `gh run list --repo
idaholab/prometheus_core --commit <sha>`. Count only results for the commit under review, not
for an earlier push. Note each job as passed, failed, pending, or not run.

Collect: the changed files, the commit messages, the CI results, and the PR body if there is
one. Then write:
- a **short title**, up to about eight words (for example "PR 280: alembic check CI job"). Use it
  in the questions and the report heading;
- a **two-sentence summary** of what the change does, for the reviewers. Don't add your
  opinion of the change.

## 2. Propose reviewers

Match the changed paths against this table. A reviewer is proposed when any of its rows match.

| changed paths | reviewers |
|---|---|
| `platform/frontend/**` | frontend, technical, CI |
| `platform/backend/**` | backend, technical, CI |
| `backend/app/{auth,sessions,identity,crypto,signing_keys,oidc,passwords,security}*`, `routers/admin_*`, `routers/{auth,jwks,setup}*`, sign-in screens | + security |
| `platform/backend/alembic/**`, `backend/app/db/**` | + backend, rollout |
| `platform/agents/**`, `sdk/prometheus_api/agent/**`, `sdk/prometheus_api/llm_client/**` | agent, technical, CI |
| `agent-template/**`, `sdk/**` (public API) | agent, agent developer, rollout |
| a wire contract: `backend/app/contract.py`, `backend/CONTRACT.md`, `frontend/src/lib/api/**`, `sdk/prometheus_api/contract.py`, `sdk/prometheus_api/a2a_stream.py` | frontend, backend, agent, rollout |
| `**/docker-compose*.yml`, `**/Dockerfile`, `**/Makefile`, `**/scripts/**`, shell scripts | user, Linux/WSL, rollout, technical |
| `.env.example`, `init_env.py`, anything reading or writing `.env`, secrets, keys, tokens | security |
| `.github/workflows/**` | CI, security |
| `hackathon/.claude/**`, `**/CLAUDE.md`, `**/AGENTS.md`, any `SKILL.md` | AI skills |
| a `SKILL.md` whose `allowed-tools` changes | + security |
| `hackathon/**` (slides, KB) | user, AI skills, rollout |
| `platform/docs/**`, `**/README.md`, `TUTORIAL.md` | user (agent developer for agent docs), technical |
| `**/plans/**` | technical, rollout, and the reviewers for the areas the plan changes |

The table matches paths, but the reviewers should fit what the change *does*. Read the diff
before you finish the list. For example:
- a one-file CI change that adds a migration check is also a backend change;
- a compose edit that renames a service also breaks the hackathon commands;
- a frontend change to the sign-in screen is something every user sees.

Then adjust:

- **Code or docs.** Anything that runs counts as code: source, tests, workflow YAML, compose
  files, Dockerfiles, Makefiles, scripts. Markdown and slides are docs, even when they contain
  commands. When people copy shell commands from them, add Linux/WSL.
- **Code changes** always get technical and CI.
- **Docs-only changes** get at most technical, AI skills (if a skill or `CLAUDE.md` changes),
  and the reader of the docs: user for platform and hackathon docs, agent developer for
  `agent-template/` and agent-author docs, or both when both read them. One exception: hackathon material also gets rollout while an
  event is coming up, because what lands before it is what participants use.
- **Dependency bumps and lockfile-only changes** (Dependabot, `uv.lock`, `package-lock.json`):
  propose CI and security, plus the area reviewer (frontend, backend, agent) when the release
  notes list a breaking change. A full panel on a patch bump wastes the reviewers' time.
- If `platform/plans/<name>/reviews.md` names the reviewers for this step, propose those.
- Give each proposed reviewer a reason of a few words (the path or what the change does). The
  same reason goes in the question and on the reviewer's **Why:** line in the report.

## 3. Ask the user to confirm

**Reviewers named in the argument** (for example `312 with technical and CI`): that's the panel.
Don't ask about the reviewers. Do say which proposed reviewers it leaves out, so the user can
rerun with them. If step 1 needs the `Checkout` question, ask only that one.

**The user leaves the choice to you** ("whatever makes sense", "you pick", "all the relevant
angles"): the proposed reviewers are the panel. Print them with their reasons, and don't ask
about the reviewers. Ask only the `Checkout` question, if step 1 needs it.

**Otherwise,** first print the proposed reviewers with their reasons. Then make one
`AskUserQuestion` call with up to four questions. The dialog may hide your earlier text, so
each question names the change by its short title, and every option has a description. For a
proposed reviewer, the description is its reason. For the others, it's the reviewer's focus in
a few words. Put "(Recommended)" after each proposed reviewer's label, and list the proposed
ones first in each question. Ask all three reviewer questions even when one has no proposed
reviewer, so that the user can still add from it.

1. header `People`, `multiSelect: true`: "Which user-facing reviewers should review
   <short title>?" Options: User, Agent developer, AI skills.
2. header `Code`, `multiSelect: true`: "Which code reviewers should review <short title>?"
   Options: Technical, Frontend, Backend, Agent.
3. header `Ops`, `multiSelect: true`: "Which operations reviewers should review
   <short title>?" Options: CI and tests, Security, Rollout, Linux/WSL.
4. Only when the code isn't checked out: header `Checkout`, `multiSelect: false`:
   "<short title> isn't checked out here. Should the reviewers get a throwaway worktree of
   its head commit?" Options:
   - "Create a throwaway worktree (Recommended)": reviewers can run tests and commands. It's
     removed at the end.
   - "Review the diff only": nothing is checked out, and checks that need git are skipped.

The answers are the panel. An answer under "Other" may describe a new perspective, such as
"accessibility" or "performance". Then write a brief for it in the same shape as the files in
`reviewers/`: a persona or focus, numbered questions, what to run, and what to read. Use it
for this run. If the user wants to keep it, offer to save it as `reviewers/<name>.md` and add it
to the table above.

If no reviewer is selected, stop and say so.

## 4. Run the panel

- **One agent per reviewer, all in one message** so that they run in parallel. Use
  `subagent_type: "Plan"` (read-only, can run commands). If the user chose Sonnet in step 0,
  also pass `model: "sonnet"`.
- Each prompt is `shared-context.md` with the placeholders filled in, then the reviewer's
  file from `reviewers/`. Pass the reviewer's file as written. Don't add your conclusions,
  your guesses about problems, or other reviewers' findings.
- Reviewers **return their findings as text**. Subagents can't write report files, so don't ask
  them to.
- **Running things.** CI and tests runs the test suites of every touched component. The other
  reviewers run only the commands their brief names, so that the panel doesn't run the same
  suite eleven times. If Docker isn't running, the reviewers say so and skip the live checks.
- **Don't repeat CI.** A suite that passed in CI on the head commit isn't run again locally. Its
  result is in the shared context. A failed job gets its log read
  (`gh run view <run> --log-failed`), not a local rerun. Local runs are for what CI doesn't
  cover: a suite no job runs, a pending or missing result, an uncommitted change, and
  experiments that test a finding, such as a mutation or a live command.

## 5. Check and report

1. **Verify before reporting.** Read the code for every blocker and major finding, and run the
   command if one is named. Mark each one `confirmed`, `not reproduced` (say why), or
   `unchecked` (say why). Spot-check the minor findings.
2. **Outside my focus.** These notes aren't findings, so don't put them in a reviewer's
   findings as they are. Drop a note that another reviewer's findings already cover. When the reviewer
   who owns that area wasn't on the panel, name the note on the "Not on the panel" line as a
   reason to rerun with them. When no reviewer covered it, check it as you would a minor
   finding, and report it under the reviewer who raised it if it holds up.
3. **Duplicates.** When two reviewers found the same problem, give the full finding to the
   reviewer who showed it best (usually the one that ran something). The other reviewer's
   section gets a one-line "Same as CI-2" bullet, plus anything that reviewer added. If they rated
   it differently, keep the higher severity and give both ratings.
4. **Write the report** exactly as `report-template.md` describes. Show it in the terminal
   in that same format.
5. Remove any worktree or export you created, and any throwaway containers left over.
6. Ask (header `Next`) what to do: "Fix the confirmed findings", "Post the report to the PR",
   or "Nothing". Offer posting only for a PR target. Posting is outward-facing, so show the
   exact comment first. Then write it to `$TMPDIR/review-<n>.md` and run `gh pr comment <n>
   --repo idaholab/prometheus_core --body-file "$TMPDIR/review-<n>.md"`. When fixing
   findings, follow the report's last line: one commit per finding, with a subject that starts
   with `review-panel <ID>:`, such as `review-panel SEC-2: <what changed>`. Record each finding in the PR as fixed, deferred
   (to what), or rejected (why).
