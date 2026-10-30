# platformctl: reviews for each step

Before a step's PR is merged, it gets the same kind of independent review
the plan itself got: a set of reviewer agents, each with one perspective,
that read the step's change with fresh context. This file holds their
briefs and says which reviewers each step needs.

## How to run them

- **One agent per reviewer**, in parallel, read-only (a `Plan` or
  `Explore`-type agent). Give each the shared context below plus its own
  brief. Don't give them your own conclusions or the other reviewers'
  findings.
- **What they review:** the step's diff (`git diff upstream/devel...HEAD`)
  and its step file. The rest of `platform/plans/platformctl/` is background,
  not the thing under review.
- **Check it ran, not only read.** For a step with code, reviewers run the
  unit tests (`cd platform/ctl && uv run pytest`) and, where Docker is
  available, the live tests (`uv run pytest --live`) and the commands they
  review, against a throwaway project (`--set COMPOSE_PROJECT_NAME=review-<n>`
  and their own ports), never a stack someone is using.
- **Verify before acting.** The person running the review checks each
  blocker and major finding against the code before changing anything, and
  says which ones were checked.
- **Record the result** in the PR: the reviewers that ran, and each finding
  as fixed, deferred (to which step) or rejected (why).

## Shared context

Give every reviewer this, filled in for the step:

> Repo: `prometheus_core` (a multi-agent "Prometheus" platform run with
> Docker Compose). `platformctl` is a standard-library Python 3.10+ CLI in
> `platform/ctl/`, run through the `platform/platformctl` shim, that is
> replacing the Docker Compose logic in `platform/Makefile`; the Make targets
> forward to it. The plan is in `platform/plans/platformctl/` (README.md,
> design.md, commands.md, breaking-changes.md, one file per step).
>
> You are reviewing **step `<n>`** (`<step file>`), the change in
> `git diff upstream/devel...HEAD`. Steps `<done>` are already merged.
>
> Rules: don't modify files; never print secrets (never `cat` a `.env`,
> never run `docker compose config` or `docker inspect` on a real stack;
> read `.env.example`); only start containers in a throwaway project with
> your own project name and ports, and remove them when done.
>
> Return findings only, at most ~700 words (technical: ~900): top 3 issues
> first; then each finding with severity (blocker / major / minor), where
> (file and line, or plan section), the problem in one or two sentences, and
> a concrete fix; then at most 3 bullets of what works well. Cite file
> paths. No preamble.

## Reviewers

### 1. User

You are a new, not very technical user with Docker Desktop on a Mac,
following the slides, who just wants to chat with the agents. You copy and
paste commands and get confused by jargon.

For what this step changes: is it easier and more intuitive than before?
Walk through the journeys it touches (first setup, starting, "it broke",
restarting after a change, stopping, coming back the next day, a port in
use). For each, what do you type and what do you see, before and after?
Run the commands if you can, and judge the real output: is it clear, too
long, missing the next step? Where is it more complex or confusing (names,
questions, two ways to do one thing, generated files)? What would you
expect that isn't there?

Read: the step's diff; the user guide (`platform/docs/docs/platformctl/`);
`platform/README.md`; the hackathon `troubleshooting.md`, `environment.md`,
`run-and-register.md` and deck 03.

### 2. Agent developer

You are a developer, not a platform expert, with your own agent scaffolded
by `setup_agent.py`, in your own git repo (next to a `prometheus_core`
clone, as a submodule, or elsewhere). You edit, rebuild, test in the chat
UI, and debug "my agent isn't being called".

For what this step changes: is that loop easier? Walk through scaffolding,
the first run against the platform, editing and rerunning, platform
restarts (registration), finding why the orchestrator doesn't call your
agent, `.env` syncing, an agent in a separate repo, a teammate cloning your
repo, upgrading the platform. What gets harder or stays painful? What would
surprise you? Check against the actual template code, and try it with a
scaffolded agent if Docker is available.

Read: the step's diff; `agent-template/` (`setup_agent.py`, README,
TUTORIAL, `agent_template/`); the hackathon "Your agent" checks in
`checks.md` and the `create-agent` skill.

### 3. Technical

Review the architecture and the tests:

1. **Extensibility:** is it still easy to add a command, a subcommand, a
   check, a setting, a target, a platform source? Did this step leak an
   abstraction (an action calling Docker directly, a second place deciding
   images, a setting outside the registry)? Is anything over-engineered?
2. **Correctness:** precedence (defaults < environment < `.env` <
   `--set`, Make's variables via `MAKEFLAGS`), the compose entry file and `.platform.env`,
   labels, signals and the terminal, argparse behaviour. Verify claims with
   small experiments in a temp folder rather than trusting the plan.
3. **Tests:** run them. Is the coverage meaningful or does it restate the
   implementation? Are actions tested against the fake target and the
   Compose argv pinned only in the compose target? What's untested?
4. **Consistency:** contradictions between the code, the step file and the
   other plan files; anything the step file promised that isn't there.

Read: the step's diff; `design.md`; the code it replaces (`platform/Makefile`,
`platform/scripts/`, the compose files).

Also return a short list of contradictions (file:section vs file:section).

### 4. CI and tests

Review what is tested, and above all **what would break for a user that no
test would catch**:

1. **Gaps that matter to users.** For each command or behaviour this step
   touches, how would a user notice it broke (the platform doesn't start,
   an agent doesn't register, the wrong ports, a secret printed, a slide
   command that fails)? Is there a test that fails first? If not, propose
   the **simplest test that would**, preferring a unit test over a live
   test and a live test over a full-stack CI job, and say where it goes.
2. **New coverage, not just kept coverage.** What can be tested now that
   couldn't be before (because the logic is in Python, or because of
   `--json`, `--dry-run`, `doctor`, the entry file, `up <service>`)? Propose
   concrete tests or CI jobs that cover user-visible behaviour we never
   tested, such as every documented command parsing, the first-run
   experience, a second checkout, a port clash, a Mac with Python 3.9 as
   `python3`.
3. **Nothing silently lost.** What does CI test today about this area, and
   does the step keep all of it (moved tests, jobs switched from `make`,
   the `make` path itself)?
4. **Cost and flakiness.** Runtime, network pulls, timing-dependent
   checks; which tests should run on every PR and which only on `devel`.

Read: the step's diff; `.github/workflows/test.yml`; `platform/ctl/tests/`;
`platform/tests/`; `agent-template/tests/`.

### 5. Security and secrets

Where could this step leak or mishandle a secret, or act on something it
shouldn't?

- reading and writing `.env`, agent `.env` files and the generated files:
  permissions, atomic writes, git-ignore
- output: steps, `--verbose`, `--dry-run`, `--json`, `config show`,
  `doctor` evidence, errors, tracebacks; does the canary test cover every
  new command and code path?
- `compose --` and `compose --print`; `--set` (shell history)
- labels and what they reveal; which containers the tool restarts or stops
- copying values between folders (`config sync`), platform discovery
  (submodule, pointer, sibling)
- prompts, and running without a terminal (CI)

Run the canary test, and try the new commands with `--verbose`, `--dry-run`
and `--json` against a throwaway `.env` with sentinel values.

Read: the step's diff; `design.md` "Secrets"; `platform/.env.example`;
`platform/docs/docs/dev-docs/encryption-and-keys.md`; the hackathon
`CLAUDE.md` rules and `conventions.md`.

### 6. Rollout and migration

- **This PR:** is it reviewable, does it leave `devel` working, can it be
  reverted on its own, does it depend on something not merged yet (docs or
  slides switched to a command from a later step)?
- **People mid-migration:** someone with an existing `.env`, a stack
  started by an earlier version, an agent scaffolded earlier, or old muscle
  memory. What breaks or confuses them? Is there a "what changes for you"
  block, and is it right?
- **`breaking-changes.md`:** complete and accurate for this step?
- **Timing:** anything participants or other teams rely on right now
  (events, freezes, open PRs that touch the same files)?

Read: the step's diff and its step file; `README.md` (steps, ground
rules); `breaking-changes.md`; `git log --oneline -20`.

### 7. Linux and WSL

What in this step behaves differently or fails on:

- **Linux** with Docker Engine (not Desktop): the docker group, rootless,
  no containerd image store, distro Python and Compose versions;
- **WSL2**: Docker Desktop integration vs Engine inside WSL, `/mnt/c`
  checkouts, line endings, the executable bit;
- **macOS** edge cases: Python versions, BSD tools, Rosetta.

Look at the shim, port checks, terminal and Ctrl-C handling, paths, labels,
`host-gateway`, proxies and architecture where the step touches them. Where
should it add CI legs, live tests or a manual WSL checklist item?

Read: the step's diff; `design.md` "Runtime" and the system adapters;
`platform/docs/docs/windows-wsl2-setup.md`; `.github/workflows/test.yml`.

Tag each finding with its platform.

### 8. AI assistants and skills

AI assistants run these commands, above all the hackathon skills
(`hackathon/.claude/skills/`). For what this step changes:

- Can the skills' shell one-liners use the new commands instead? Which
  still need raw commands, and why?
- Is the `--json` output this step adds or changes stable and complete
  enough to rely on (schema version, fields, errors, exit codes)?
- Does it help or hurt the "never show a secret" rules?
- Can an assistant run every new command without a terminal and safely
  (`--yes`, `--confirm`, no following, timeouts)?
- Do the skills' text and `allowed-tools` match the commands after this
  step? Do they still work against an older clone?

Read: the step's diff; the hackathon `CLAUDE.md`; the `diagnose`, `how` and
`create-agent` skills; `platform/CLAUDE.md`.

## Which reviewers each step needs

| Step | Reviewers |
|---|---|
| 1 Scaffold | technical, CI, security, Linux/WSL, AI skills |
| 2 Port the scripts | all eight |
| 3a Forward compose | all eight |
| 3b Labels, your agents | all eight |
| 3c Groups and docs | all eight |
| 4 Doctor | all eight |
| 5 Contributor docs | user, technical, AI skills |
| 6 Fix existing docs | user, agent developer, AI skills |
| 7 Agent folders | all eight |
| 8 k3d target | technical, CI, security, rollout, Linux/WSL |
| 9 Platform images | technical, CI, security, rollout, agent developer |

A step can add reviewers, or drop one with a sentence in the PR on why.
Update a brief here when it stops fitting (for example, the rollout
reviewer's timing questions once there's no event coming up).
