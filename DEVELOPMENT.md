# Development and pull request practices

[CONTRIBUTING.md](CONTRIBUTING.md) covers the basic workflow: fork, branch from
`devel`, run the checks, open a pull request. This guide explains how we scope
work, structure pull requests, and review them, and why. It applies to
maintainers and outside contributors alike.
Coding standards (style, types, errors, logging, dependencies) are in
[STANDARDS.md](STANDARDS.md).

Component-specific setup and commands live with each component:
[sdk/DEVELOPMENT.md](sdk/DEVELOPMENT.md), [platform/README.md](platform/README.md),
[platform/backend/README.md](platform/backend/README.md),
[platform/frontend/README.md](platform/frontend/README.md), and
[agent-template/README.md](agent-template/README.md).

## Principles

- **Small and single-purpose.** One logical change per pull request. Small PRs
  get reviewed sooner and more carefully, and they're easier to revert.
- **`devel` always works.** Every PR passes CI on its own. Don't merge something
  broken that a later PR will fix.
- **Say what changed.** A refactor doesn't change behavior. A behavior change
  says so, and lists who is affected.
- **Tests and docs come with the change,** not in a follow-up PR.

## Scoping a change

### What counts as one logical change

A PR should be describable in one sentence without "and". These are each their
own PR:

- a bug fix
- a refactor or rename (no behavior change)
- a new feature or endpoint
- a dependency or tooling bump
- reformatting or lint cleanups
- a documentation pass

If you find an unrelated problem along the way, note it in a Jira ticket or fix
it in a separate PR. Don't fold it into the current one.

### Size

There's no hard limit, but aim for a diff a reviewer can read in one sitting:
roughly a few hundred changed lines, not counting lockfiles, generated files,
and snapshots. Larger PRs are fine when the change can't be split (a new page, a
new agent), but say in the description why it's one piece.

### Splitting larger work

Plan bigger efforts as an ordered series of PRs, each one mergeable on its own.
A typical order:

1. **Safety net first.** Add the tests that pin down current behavior (for
   example, a snapshot or characterization test).
2. **Refactors** that make the change easy, with no behavior change.
3. **The behavior change** itself, now small.
4. **Cleanup:** remove the old code path, compatibility shims, dead config.

When a change crosses components (for example, an SDK API used by the
platform), land the SDK side first. Then update the callers in a following PR,
unless both sides have to change together to keep CI green.

For a series of more than two or three PRs, open a Jira ticket that lists
them and check them off as they merge.

### Stacked pull requests

When PR B builds on PR A before A has merged, branch B from A's branch and open
it against `devel` anyway (a fork can't target another fork's branch). Until A
merges, B's diff also contains A's commits, so start B's description with a note
like this:

```markdown
> **Depends on #123.** This branch is stacked on #123. Until it merges, this
> diff also contains its commits. Review only `abc1234` (*Add the widget model*).
> I'll update this branch from `devel` once #123 lands.
```

Keep stacks shallow (two or three deep). Once the parent merges, merge or rebase
`devel` into the child so its diff shrinks to its own commits, and update the
note.

## Branches and commits

### Branch names

Use a short, descriptive, lowercase name with hyphens. Prefix it with the kind of
change, and include the ticket key if there is one:

| Prefix | Use for |
|--------|---------|
| `feat/` | new behavior |
| `fix/` | bug fixes |
| `refactor/` | restructuring with no behavior change |
| `docs/` | documentation only |
| `chore/` | tooling, CI, dependencies, tests only |

Examples: `fix/sse-reconnect-loop`, `feat/PPLT-198-workflow-graph`.

### Commits

The commit message format is in [CONTRIBUTING.md](CONTRIBUTING.md#4-write-good-commit-messages).
Beyond that:

- **Each commit should build and pass tests.** That keeps `git bisect` useful.
- **Split commits by step** when that helps review, for example "Move X to Y"
  followed by "Change X". Pure moves and renames are easy to review on their own
  and hard to review mixed with edits.
- **Squash "fix typo" and "address review" commits** into the commit they fix
  before the PR is approved, so the history that lands on `devel` reads cleanly.
  Pull requests are merged with a merge commit, so every commit on the branch
  ends up in `devel`.

### Keeping a branch up to date

- **Before review starts,** rebase onto `devel` freely
  (`git fetch upstream && git rebase upstream/devel`).
- **Once reviewers have left comments,** prefer merging `devel` into your
  branch over force-pushing a rebase. A rebase rewrites the commits reviewers
  already commented on, and GitHub then can't show them what changed since their
  last review.
- If you must force-push during review, use `git push --force-with-lease` and
  mention it in a comment.

## Writing the pull request

The [PR template](.github/PULL_REQUEST_TEMPLATE.md) asks for **Reason**,
**Design**, and **Impact**. A good description lets a reviewer understand the
change before opening the diff:

- **Reason:** the problem, with a concrete example if possible (an error
  message, a request that fails, a confusing UI state). Link the Jira ticket.
- **Design:** the approach, and any alternatives you rejected and why. Point
  reviewers at the important file or function if the diff is large.
- **Impact:** what existing users, agents, or deployments will notice. Write
  "No behavior change" when that's true; it tells the reviewer what to check.
- **Testing:** what you ran and what you checked by hand. For UI changes, add a
  screenshot or short recording.

Title the PR like a commit summary: imperative and specific ("Retry SSE
reconnects with backoff", not "SSE fixes"). Prefix the ticket key if there is
one (`PPLT-198: ...`).

### Drafts and labels

- Open a **draft** PR to share work in progress or get early feedback on an
  approach. Say in the description what kind of feedback you want.
- Mark it **ready for review** when CI passes and you'd be happy for it to
  merge as is. Maintainers add the `pr: ready for review` label.
- `pr: ready for merge` means it's approved and waiting on nothing else.
  `do not merge` blocks a PR on something outside it (an upstream release, a
  coordinated deploy); say what in a comment.

## Tests and checks

[CONTRIBUTING.md](CONTRIBUTING.md#5-run-the-checks) lists the commands for each
component. A few rules matter when you plan a change:

- **New and changed lines must be covered.** Codecov requires 100% patch
  coverage and no drop in project coverage, and it annotates uncovered lines in
  the PR diff. The `fail_under` floors in each `pyproject.toml` may be raised,
  never lowered.
- **Test the behavior, not the implementation.** A refactor should pass the
  existing tests without changing their assertions. If you have to change an
  assertion, the behavior changed; say so in the PR.
- **A bug fix includes a test** that fails without the fix.
- **Don't skip or delete a failing test** to get CI green. Fix it, or explain in
  the PR why it's wrong.
- **Integration tests** that need DeepLynx or a running stack are excluded from
  the default `make test`. Run them when you touch those paths, and say so in the
  PR.

## Behavior and interface changes

Some changes reach beyond the code in the diff. Call them out under **Impact**
and handle them as follows.

### Backend HTTP API

`platform/backend/openapi/openapi.json` is the backend's committed OpenAPI
document: its routes, methods, parameters, schemas and their documentation. After
changing a route, a model or the API's documentation, regenerate it with
`uv run python scripts/export_openapi.py` in `platform/backend` and commit the
diff. CI's `platform: backend openapi` job fails if it's out of date. If the diff
changes more than wording, your change altered the API: either fix the change, or,
if it's intentional, explain the difference in the PR. The frontend mirrors the
wire contract in TypeScript, so update both together. See "OpenAPI document" in
`platform/backend/README.md`.

### SDK (`prometheus_api`)

Agents outside this repository depend on the SDK, so:

- **Bump the version** in `sdk/pyproject.toml` (`make bump-patch`, `bump-minor`,
  or `bump-major`) when the change affects the public API or base-agent behavior,
  and state the new version in the PR.
- **Write migration notes.** When downstream agents have to change anything, add
  a section to [sdk/docs/agent/AGENT_MIGRATIONS.md](sdk/docs/agent/AGENT_MIGRATIONS.md)
  under the new version, with steps and a short code example.
- **Keep the specs current.** Capabilities are specified in [sdk/specs/](sdk/specs/)
  with requirement IDs (`REQ-010-03`). Add or update the requirement with the
  change, and reference the IDs in the tests.
- **Update callers in this repository** (platform agents, `agent-template/`,
  `hackathon/`), in the same PR or in a follow-up linked from it.

### Configuration and deployment

New environment variables go in the relevant `.env.example` with a comment, and
in the component's docs. Changes to Docker Compose files, images, or ports go in
**Impact**, because they affect everyone running the stack.

## Review

### For authors

- **Review your own diff first.** Read it on GitHub before requesting review;
  you'll catch leftovers, debug prints, and unrelated changes.
- **Answer every comment,** even if only with "Done" or a link to the commit
  that fixes it. If you disagree, say why. A reviewer's suggestion is a starting
  point for discussion, not an order.
- **Leave resolving to the reviewer** when there was a discussion, so they can
  confirm the fix.
- **Push follow-up fixes as new commits** during review so reviewers can see
  what changed, then squash before merge if needed.
- **Keep the description accurate.** If review changes the design, update the
  description to match.

### For reviewers

- **Respond promptly.** Aim for a first pass within two working days. If you
  can't, say so, or ask another code owner to take it.
- **Review the change, not the person.** The
  [Code of Conduct](CODE_OF_CONDUCT.md) applies in review.
- **Say how much each comment matters.** Prefix optional ones with `nit:` or
  "optional:". Everything else is expected to be resolved before merge.
- **Look past style.** Linters handle formatting. Spend your attention on
  correctness, edge cases, tests, naming, error handling, security, and whether
  the change belongs in this PR.
- **Ask for a split** when a PR mixes unrelated changes or is too large to review
  well. That's a normal request, not a rejection.
- **Approve when it's good enough to merge,** not when it's how you'd have
  written it. Leftover nits can be follow-ups.

## Merging and afterwards

A PR merges once CI passes and a code owner approves it. Merging is done with a
merge commit, and the branch is deleted automatically.

After merging:

- Update or close the linked Jira ticket.
- Update any stacked PRs that depended on this one.
- If the change needs a deploy, an image rebuild, or a `PROMETHEUS_API_BASE_IMAGE_HASH`
  bump in `platform/Makefile`, make sure someone owns that step.

## AI-assisted development

The rules in [CONTRIBUTING.md](CONTRIBUTING.md#ai-assisted-contributions) apply.
In practice, coding assistants tend to produce large, sprawling diffs, so be
especially strict about splitting their output into small PRs, removing
unrelated edits, and checking that the tests actually exercise the change.
Point your assistant at the `AGENTS.md` and `CLAUDE.md` files in each component,
and at this guide.
