---
title: GitHub & PR Workflow
footer: Day 1 · GitHub & PR workflow
accent: gh
index:
  time: '1:00'
  heading: GitHub &amp; PR workflow
  color: var(--violet)
  blurb: Where your code goes (a team repo on github.com), the branching model, forking, the daily loop with <code>git pull --rebase</code>, conflicts and force-pushes, commits, PRs with JIRA, review, the practice PR.
---

# GitHub overview &<br>PR workflow {.title kicker="Day 1 · 1:00 pm" pills="All participants | 45 min | github.com"}
Where your code goes, how to branch and rebase, and how to get a PR reviewed and merged.

---

## By the end you can… {eyebrow="This session"}

:::: grid 3
::: card acc
<div class="kpi"><span class="v">1</span></div>

### Find your repo

{.small}
Know where your code goes (your team's repo) and why you fork it.
:::

::: card acc
<div class="kpi"><span class="v">2</span></div>

### Work on a branch

{.small}
Branch, commit, stay current with `git pull --rebase`, and push safely.
:::

::: card acc
<div class="kpi"><span class="v">3</span></div>

### Get merged

{.small}
Open a PR reviewers can act on, and review someone else's.
:::
::::

::: callout info
You'll do all three for real at 3:30 pm, with a practice PR. On Day 2 every team works the same way.
:::

---

## One repo per team, owned by one teammate {eyebrow="Where your code goes"}

::: grid 2 gap=30px
```text {.sm}
github.com/<owner>/<team>-agent   # the team repo
├── agent.py                      # scaffolded by
├── agent_card.json               #   setup_agent.py
├── pyproject.toml · Dockerfile · Makefile
├── tests/
│   └── fixtures/                 # practice files
└── README.md
     ▲ PRs to main
github.com/<teammate>/<team>-agent  # each teammate's fork
```

|||

- **One teammate owns the repo**: scaffolds the agent, pushes it to github.com, and **reviews and merges** every teammate's PR.
- Teammates **fork** the owner's repo and open PRs from their forks. The owner's own PRs are reviewed by a teammate.
- Private repo? The owner invites the teammates and the judges (read access is enough to fork and review).
- `idaholab/prometheus_core` (platform, SDK, template, these slides) is read-only for this hackathon. Contributing later? Fork it too and open PRs to `devel`.
:::

---

# Branching strategy {.section num="02"}
Git Flow: a production branch, an integration branch, short-lived feature branches, and release/hotfix lanes.

---

##  {eyebrow="Our model · develop = devel in prometheus_core" content="center" content-style="flex:1; min-height:0" nofit style="gap:10px"}

<img alt="Git Flow branching strategy diagram" class="fit" src="assets/git_branches.png" style="max-height:740px"/>

---

## You work on feature branches {eyebrow="What it means for you"}

::: grid 2 gap=30px
| Branch | Who touches it |
|---|---|
| `feature/<desc>` | **you**: one per piece of work, in your fork {.hl} |
| `main` (your team repo)<br>`devel` (prometheus_core) | the integration branch: PRs only |
| `release/*`, `hotfix/*`, platform `main` | maintainers, for releases |

|||

- Name branches `feature/<team>-<what>`: `feature/neutron-plot-skill`.
- Branch from the latest integration branch, keep it short-lived, delete it after the merge.
- Never commit to `main` or `devel` directly.
:::

---

## Fork and clone: `origin` is yours, `upstream` is the owner's {eyebrow="Once"}

:::: cols 1.35fr 1fr gap=28px
```bash {.sm}
gh repo fork <owner>/<team>-agent --clone=false

cd ~/prometheus
git clone git@github.com:<you>/<team>-agent.git
cd <team>-agent
git remote add upstream \
  git@github.com:<owner>/<team>-agent.git

git config pull.rebase true
git config rebase.autoStash true
```

|||

{.sm}
- `origin` = your fork: you push here.
- `upstream` = the owner's repo: PRs go here, and you pull updates from here.
- Check with `git remote -v`.

::: callout
Each teammate forks separately. Everyone's PRs meet in the owner's repo. The owner works in a clone of the team repo and opens PRs from feature branches.
:::

::: callout info
No `gh`? Install it (deck 02 bonus) or use the **Fork** and **Compare & pull request** buttons on the web.
:::
::::

---

## The daily loop {eyebrow="Every piece of work"}

::: cols 1.35fr 1fr gap=28px
```bash {.sm hl=8}
git fetch upstream
git switch -c feature/neutron-plot-skill upstream/main

# edit, test, commit small steps
git add -p
git commit -m "Add the plot skill with a column form"

git pull --rebase upstream main   # stay current
git push -u origin HEAD

gh pr create --repo <owner>/<team>-agent \
  --base main --head <you>:feature/neutron-plot-skill
```

|||

{.sm}
1. **Branch** from the latest `upstream/main`
2. **Commit** small, logical steps
3. **Rebase** onto upstream before pushing
4. **Push** to your fork
5. **Open a PR** to the owner's repo

{.small}
For the platform repo the integration branch is `devel`: `git pull --rebase upstream devel`, `--base devel`.
:::

---

## `git pull --rebase upstream main`, visually {eyebrow="What rebase does"}
> In your team repo. For the platform the same picture applies to `upstream/devel`.

<svg aria-label="Rebase diagram" height="380" role="img" viewbox="0 0 1400 380" width="1400">
<style>
        .ln{stroke:#9aa8ba;stroke-width:4;fill:none}
        .dv{fill:#d8c93a;stroke:#fff;stroke-width:3}
        .ft{fill:#6b4fbb;stroke:#fff;stroke-width:3}
        .ftn{fill:#fff;stroke:#6b4fbb;stroke-width:3;stroke-dasharray:4 3}
        .lb{font:600 17px 'JetBrains Mono',monospace;fill:#35455b}
        .tt{font:700 22px Archivo,sans-serif;fill:#0e1b2c}
        .cm{font:15px 'JetBrains Mono',monospace;fill:#66768c}
      </style>
<text class="tt" x="20" y="34">Before</text>
<path class="ln" d="M60 110 H600"></path>
<path class="ln" d="M200 110 C240 110 240 180 280 180 H440" style="stroke:#6b4fbb"></path>
<circle class="dv" cx="100" cy="110" r="15"></circle><circle class="dv" cx="200" cy="110" r="15"></circle>
<circle class="dv" cx="400" cy="110" r="15"></circle><circle class="dv" cx="520" cy="110" r="15"></circle>
<circle class="ft" cx="320" cy="180" r="15"></circle><circle class="ft" cx="430" cy="180" r="15"></circle>
<text class="lb" x="560" y="94">upstream/main</text>
<text class="lb" x="460" y="186">feature/x</text>
<text class="cm" x="300" y="224">A</text><text class="cm" x="422" y="224">B</text>
<text class="cm" x="385" y="80">C</text><text class="cm" x="507" y="80">D</text>
<text class="tt" x="720" y="34">After</text>
<path class="ln" d="M760 110 H1260"></path>
<path class="ln" d="M1220 110 C1250 110 1250 180 1280 180 H1340" style="stroke:#6b4fbb"></path>
<circle class="dv" cx="800" cy="110" r="15"></circle><circle class="dv" cx="900" cy="110" r="15"></circle>
<circle class="dv" cx="1060" cy="110" r="15"></circle><circle class="dv" cx="1220" cy="110" r="15"></circle>
<circle class="ft" cx="1290" cy="180" r="15"></circle><circle class="ft" cx="1345" cy="180" r="15"></circle>
<text class="lb" x="1040" y="80">upstream/main</text>
<text class="cm" x="1045" y="150">C</text><text class="cm" x="1207" y="150">D</text>
<text class="cm" x="1266" y="224">A′</text><text class="cm" x="1330" y="224">B′</text>
<text class="lb" x="1150" y="258">feature/x</text>
<text class="cm" x="20" y="300">Your commits A and B are replayed on top of the new tip D as new commits A′ and B′ (new SHAs).</text>
<text class="cm" x="20" y="328">That is why the next push needs --force-with-lease, and why rebasing an open PR restarts review.</text>
</svg>

:::: grid 2
::: card
#### Tidy before review

```bash {.xs}
git rebase -i upstream/main
# squash fixups, reword
git commit --fixup <sha>
git rebase -i --autosquash …
```

{.tiny}
Interactive rebase needs a terminal editor.
:::

::: card
#### Repeated conflicts

```bash {.xs}
git config rerere.enabled true
```

{.small}
git remembers how you resolved a conflict and reapplies it on the next rebase.
:::
::::

---

## Conflicts and force-pushes {eyebrow="After a rebase"}

:::: grid 3
::: card
#### A conflict during rebase

```bash {.xs}
git status          # which files
# fix them, then
git add <file>
git rebase --continue
git rebase --abort  # start over
```
:::

::: card
#### Pushing a rebased branch

```bash {.xs}
git push --force-with-lease
```

{.small}
A rebase rewrites your commits, so the push must be forced. `--force-with-lease` refuses if someone else pushed in the meantime. Never plain `--force`.
:::

::: card
#### Once review has started

{.small}
Don't rebase any more: **merge** the integration branch in (`git merge upstream/main`) and push new commits, so reviewers see only the delta. Any new push clears approvals.
:::
::::

::: callout warn
Force-push only **your own** feature branch, never a branch a teammate also works on.
:::

---

## Commit messages people can read later {eyebrow="Commits"}

::: grid 2 gap=30px
- **Imperative subject, under 72 characters**: "Add…", "Fix…", "Handle…".
- **The body explains why**; the diff shows what.
- One topic per commit.
- **Never commit `.env`**, keys, or tokens. Check `git status` before every commit.

|||

#### Good {.acc}

```text {.sm}
Handle thousands separators in table cells
Ask for the x column when none was given
Return the matched caption with the table id
```

#### Not helpful {.acc}

```text {.sm}
wip
fix
changes
```
:::

---

## A description reviewers can act on {eyebrow="Opening a PR"}

::: cols 1.2fr 1fr gap=28px
```markdown {.sm}
refs PPLT-123             # project convention

## Reason
"plot this" on a CSV used to fail.

## Design
Plot skill asks for columns when none are given.

## Impact
No API change. Tested: uv run pytest, ruff;
chat upload → "plot this" → form → plot rendered.
```

|||

{.sm}
- **Title** like a commit subject.
- **Small and focused**: one topic per PR.
- The sections of prometheus_core's PR template: **Reason, Design, Impact**. Say how you tested it.
- In project work, reference the **JIRA task** (`PPLT-…`).
- Still in progress? `gh pr create --draft`.
:::

---

## Reviewing, and being reviewed {eyebrow="Code review"}

:::: grid 2 gap=30px
::: card
### As an author

{.sm}
- Reply to every comment: "Fixed in `a1b2c3d`", or why not.
- Push fixes as new commits during review.
- Never approve your own PR (you can't).
:::

::: card
### As a reviewer

{.sm}
- Be concrete: which line, which input breaks it.
- Separate "must fix" from "nit".
- Check the tests test what they claim.
:::
::::

::: callout good
The Day 2 gate needs every merged PR **reviewed**: the owner approves teammates' PRs, a teammate approves the owner's.
:::

---

## Your practice PR, in your neighbour's repo {eyebrow="Practice at 3:30"}

:::: grid 2 gap=30px
```bash {.xs}
# 1 · your hello agent becomes your repo
cd ~/prometheus/hello-<you>
git init -b main
git status                     # NO .env in the list!
git add . && git commit -m "Scaffold hello-world agent"
gh repo create hello-<you> --public --source=. --push

# 2 · fork your neighbour's repo, change it
cd ~/prometheus
gh repo fork <neighbour>/hello-<neighbour> --clone
cd hello-<neighbour>           # origin = you, upstream = them
git switch -c feature/better-greeting
# edit agent_card.json: a sharper skill description
git commit -am "Describe when to call the greeting skill"
git push -u origin HEAD
gh pr create --repo <neighbour>/hello-<neighbour> \
  --base main --title "Describe the greeting skill" \
  --body "Dry-run PR. Tested: uv run pytest."
```

|||

{.sm}
1. Your neighbour reviews the PR you opened: one inline comment, you answer it and resolve it.
2. You review the PR you received the same way, **approve**, and merge it.
3. Rebase exercise: back in your own repo, `git pull --rebase` after the merge.

{.small}
This is the Day 2 setup in small: one owner, teammates who fork, the owner reviews and merges.

::: callout warn
`gh repo create --source=.` pushes everything `git add` staged. Check `git status`: `.env` holds your platform's secrets and must not be listed (the scaffold's `.gitignore` excludes it).
:::
::::

---

## Git & gh commands on one page {eyebrow="Cheat sheet"}

::: grid 3 gap=18px
```bash {.xs}
# setup (once)
gh auth login
gh repo fork <owner>/<repo> --clone=false
git clone git@github.com:<you>/<repo>.git
git remote add upstream \
  git@github.com:<owner>/<repo>.git
git config pull.rebase true
git config rebase.autoStash true
git config rerere.enabled true
```

|||

```bash {.xs}
# every feature
git fetch upstream
git switch -c feature/<desc> upstream/main
#   (upstream/devel for the platform)
git commit -m "Imperative subject"
git pull --rebase upstream main
git push -u origin HEAD
git push --force-with-lease
gh pr create --repo <owner>/<repo> \
  --base main --head <you>:feature/<desc>
```

|||

```bash {.xs}
# during review
gh pr status
gh pr view --comments
gh pr checks
gh pr diff
git rebase --continue | --abort
git log --oneline --graph \
  upstream/main..HEAD

# after merge
git switch -d upstream/main
git branch -D feature/<desc>
git push origin --delete feature/<desc>
```
:::

::: callout
Next: **Your local platform** (1:45 pm). Keep your platform running; we look at what it runs for you.
:::

---

# Bonus: catch-up slides {.section .bonus num="+"}
For participants who could not finish the homework: GitHub access, SSH keys, and fresh clones.

---

## Getting in: account, git, and the base image {eyebrow="Bonus · Access"}

:::: grid 3
::: card tag="1 · github.com account"
#### Access to `prometheus_core`

{.small}
You need a **github.com** account with read access to `idaholab/prometheus_core`. Give the organizer your username before Day 1.

{.small}
You **fork** it and open PRs from your fork; you cannot push branches to `idaholab/prometheus_core`.
:::

::: card tag="2 · git transport"
#### SSH key or gh credential helper

{.small}
Add a key at `github.com/settings/keys`, then:

```text {.xs}
ssh -T git@github.com
```

{.small}
Or use HTTPS and let `gh` handle credentials:

```bash {.xs}
gh auth login
```
:::

::: card tag="3 · base image"
#### Built locally

{.small}
The `prometheus_api` base image is built from `sdk/` in your clone. One line in `platform/.env`:

```bash {.xs}
LOCAL_SDK=true
```
:::
::::

::: callout info
**`gh`, the GitHub CLI**, is used in these slides. Install it with `brew install gh` (needs admin rights), or copy the release binary from `github.com/cli/cli/releases` into `~/.local/bin` (no admin). Then `gh auth login`. Without `gh`: the **Fork** button and **Compare & pull request** on the web do the same.
:::

::: callout warn
No access yet? Tell a mentor now. Repo admins can add you; waiting until 3:30 pm will cost you the dry run.
:::

---

## Fresh start: fork, then clone. `origin` is yours, `upstream` is idaholab {eyebrow="Bonus · Fork & clone conventions"}

:::: grid 2 gap=30px
```bash {.sm}
# 1. fork in the web UI, or:
gh repo fork idaholab/prometheus_core --clone=false

# 2. clone YOUR fork
git clone git@github.com:<you>/prometheus_core.git
cd prometheus_core

# 3. add the org repo as "upstream"
git remote add upstream \
  git@github.com:idaholab/prometheus_core.git
git fetch upstream
git remote -v
#   origin    …:<you>/prometheus_core  (push here)
#   upstream  …:idaholab/prometheus_core (PR target)

# 4. make rebase the default for pull
git config pull.rebase true
git config rebase.autoStash true
```

|||

::: card
#### Why fork?

{.small}
**Always fork the platform**: you can't push branches to `idaholab/prometheus_core`, so the PR goes from `<you>:feature/x` to `idaholab:devel`. Your team's repo works the same way.
:::

::: card
#### One clone, three directories

{.small}
The template and the SDK live inside the platform repo, so there is nothing else to clone. `setup_agent.py` finds `../platform/.env` and copies its secrets into your new agent.

```text {.xs}
~/prometheus/
├── prometheus_core/
│   ├── platform/        # make up here
│   ├── sdk/
│   └── agent-template/  # setup_agent.py
└── <team>-agent/       # your team repo (clone)
```
:::
::::

---

## Clone the platform monorepo {eyebrow="Bonus · Homework"}

```bash
cd ~/prometheus
git clone git@github.com:idaholab/prometheus_core.git
# no SSH key? use HTTPS and let gh handle credentials:
gh auth login
git clone https://github.com/idaholab/prometheus_core.git
ls prometheus_core    # agent-template  platform  sdk  README.md  CODEOWNERS
```

::: callout
The agent template is `prometheus_core/agent-template/`; there is no separate repo to clone any more. Already cloned `prometheus_agent_template` for an earlier homework? That repo is archived now; use `agent-template/` in the monorepo.
:::

---

# Appendix: reference {.section .appendix num="A"}
Reference material behind the talk. Skipped in the session; use it when you need the details.

---

## What you will be able to do afterwards {eyebrow="This session"}

:::: grid 3
::: card acc
### Find your way

{.sm}
- Know the monorepo (`platform/`, `sdk/`, `agent-template/`) and what lives where
- Understand how the SDK reaches every agent (the local `prometheus_api` base image)
- Know which branch each repo integrates on
:::

::: card acc
### Work safely

{.sm}
- Fork, clone, add `upstream`
- Branch `feature/<desc>` from the integration branch
- Stay current with `git pull --rebase upstream devel`
- Push with `--force-with-lease` to *your fork*
:::

::: card acc
### Get merged

{.sm}
- Run the local checks (they *are* the CI for most repos)
- Open a PR with `gh pr create` against the right base
- Pass review: 1 approval, all threads resolved
:::
::::

::: callout info
Hands-on is at 3:30 pm: you will put your hello agent in your own repo and open a practice PR to a neighbour's, the same setup your team uses on Day 2. Nothing today touches the platform's `devel` or `main`.
:::

---

## `github.com/idaholab/prometheus_core` {eyebrow="The repository"}
> The public home of Prometheus: one monorepo on github.com, default branch `devel`.

:::: grid 2 gap=30px
::: card
#### 🚀 prometheus_core

{.small}
Three directories, each with its own `Makefile` and tests:

{.xs}
- `platform/`: orchestration, agent registry, frontend, core agents
- `sdk/`: `prometheus_api`, the agent base class, LLMClient and storage helpers
- `agent-template/`: start your own agent here
- `hackathon/`: these slides, the challenge files, and Claude Code skills for participants
:::

::: callout info
It replaces the internal repos `prometheus_platform`, `prometheus_api` and `prometheus_agent_template`. Their history was carried over, with rewritten commit hashes.
:::

|||

### What else you may hear about {.acc}

| Where | What |
|---|---|
| JIRA project `PPLT` | Issues and work items; **reference the task in project PRs** (e.g. `PPLT-123`) |
| Confluence, space "Prometheus" | Design and planning documents |
| `github.inl.gov/genesis` | Other agent repos (gmsh, bim, …); INL network only |

::: callout
For the hackathon you need only `prometheus_core` and a github.com account. Your team's agent lives in a repo of your own (next slides).
:::
::::

---

## Agent repos on the INL network {eyebrow="Repository map · github.inl.gov/genesis"}

::: grid 3 gap=16px
#### Core platform {.acc}

<table class="t xs">
<tr><td><b>prometheus_core</b></td><td>github.com/idaholab, default <code>devel</code>: <code>platform/</code>, <code>sdk/</code> (v0.13.0), <code>agent-template/</code>, <code>hackathon/</code></td></tr>
<tr><td>prometheus_platform, prometheus_api, prometheus_agent_template</td><td>superseded by the monorepo</td></tr>
</table>

<h4 class="acc" style="margin-top:6px">Tooling</h4>

<table class="t xs">
<tr><td>mcps</td><td>FastMCP server template</td></tr>
<tr><td>a2a-tester</td><td>debug UI (still A2A v0.3)</td></tr>
<tr><td>reactor-dt-modules</td><td>digital-twin library</td></tr>
<tr><td>pythia</td><td>surrogate model repo</td></tr>
</table>

|||

#### Agents (A2A / PrometheusAgent) {.acc}

<table class="t xs">
<tr><td><b>gmsh_agent</b></td><td>STEP → tet mesh</td></tr>
<tr><td><b>bim_agent</b></td><td>"Alchemy" IFC4 BIM</td></tr>
<tr><td><b>requirements_agent</b></td><td>plant sizing + reqs</td></tr>
<tr><td>muninn</td><td>RAVEN UQ</td></tr>
<tr><td>open_pronghorn-agent</td><td>RANS CFD</td></tr>
<tr><td>pythia-agent</td><td>ATR valve surrogate</td></tr>
<tr><td>component_*_agent (×3)</td><td>inspection · QA · testing reports</td></tr>
<tr><td>data-catalog-search-agent</td><td>DeepLynx search</td></tr>
<tr><td>aegis</td><td>safety analysis</td></tr>
</table>

|||

#### More agent work {.acc}

<table class="t xs">
<tr><td>system-thermal-hydraulics</td><td>TH network solver</td></tr>
<tr><td>cubit-energy-agent</td><td>Cubit meshing (ADK)</td></tr>
<tr><td>amsc-client-agent</td><td>American Science Cloud</td></tr>
<tr><td>am-print-planner</td><td>preform/slicer agents</td></tr>
<tr><td>nuclear_safety_agent</td><td>Chainlit app (not A2A)</td></tr>
<tr><td>cad-agent</td><td>build123d CAD app</td></tr>
<tr><td>multiphysics-uq-agent</td><td>empty</td></tr>
</table>

<div class="callout" style="font-size:16px">Everything except <b>prometheus_core</b> is in <code>github.inl.gov/genesis</code> and needs INL network access. Those repos take PRs directly into <code>main</code>.</div>
:::

---

## One SDK, delivered as a base image {eyebrow="How the directories relate"}

<div class="dg">
<div class="row" style="gap:0; align-items:stretch">
<div class="box navy" style="width:330px"><b>sdk/</b><span class="small">package <code>prometheus-api</code></span><span class="small">in your clone</span></div>
<div class="arrow-h" style="width:160px"><span>make base-image</span></div>
<div class="box violet" style="flex:1"><b>Base image</b><span class="mono">prometheus_api:local</span><span class="small">Python 3.12 + uv + git + prometheus_api + a2a-sdk/starlette/uvicorn/litellm/httpx/redis/fsspec + CA bundle</span></div>
</div>
<div class="grid g2" style="gap:24px"><div class="arrow-v"><span>FROM prometheus_api:local</span></div><div class="arrow-v"><span>FROM prometheus_api:local</span></div></div>
<div class="row" style="gap:24px">
<div class="box sky" style="flex:1"><b>platform/</b><span class="small">backend, client-agent, and every <code>agents/*</code> image</span><span class="small"><code>LOCAL_SDK=true</code> in <code>platform/.env</code>: <code>make up</code> builds the image first</span></div>
<div class="box orange" style="flex:1"><b>agent-template/ → your agent</b><span class="small"><code>agent-template/agent_template/Dockerfile</code></span><span class="small"><code>setup_agent.py</code> writes the local image into your <code>.env</code></span></div>
</div>
</div>

:::: grid 3
::: card
#### Not a pip dependency

{.small}
Agent `pyproject.toml` files must **not** list `prometheus_api`, a2a-sdk, starlette, or uvicorn. The image has them, and `uv sync --inexact` keeps them.
:::

::: card
#### Not git submodules

{.small}
The platform's `.gitmodules` is empty. External agents are separate repos that **register at runtime** with the platform backend's agent registry.
:::

::: card
#### Local venvs

{.small}
For IDE and tests outside Docker, install the SDK from your clone:

```bash {.xs}
uv pip install -e \
  ~/prometheus/prometheus_core/sdk
```
:::
::::

::: callout
Change something in `sdk/`? The next `make up` in `platform/` rebuilds `prometheus_api:local`, and every service picks it up. Agents rebuild on their next `make up`.
:::

---

## Where things live {eyebrow="Inside the monorepo"}

::: grid 3 gap=18px
```text {.xs}
platform/  (prometheus_core, devel)
├── Makefile             # up, restart, logs…
├── docker-compose.yml   # core services
├── .env.example
├── frontend/            # React + Vite
├── backend/             # FastAPI + registry
├── agents/
│   ├── client-agent/    # orchestrator
│   ├── form-filler-agent/
│   ├── synthesis-agent/
│   ├── debug-agents/*/
│   └── optional/osti-research-agent/
├── tests/  # infrastructure/, system/
├── docs/   # zensical site
├── AGENTS.md · CLAUDE.md
└── README.md
```

|||

```text {.xs}
sdk/  (formerly prometheus_api)
├── prometheus_api/
│   ├── agent/        # PrometheusAgent,
│   │                 #  identity, registry,
│   │                 #  artifacts, worker
│   ├── llm_client/   # LLMClient
│   ├── llm_configs/  # *.yaml profiles
│   ├── storage_client/ # DeepLynx
│   ├── credentials/
│   └── contract.py · a2a_stream.py
├── specs/  # 000–014, REQ-/BEH- IDs
├── docs/agent/  # GUIDE, MIGRATIONS
├── examples/
├── Dockerfile · Makefile
├── llm_config.example.yaml
└── (certs: ../common/certs/)
```

|||

```text {.xs}
agent-template/
├── setup_agent.py     # scaffolder
├── TUTORIAL.md        # 1,200+ lines
├── README.md
├── success_message.txt
├── tests/test_setup_agent.py
└── agent_template/
    ├── agent.py
    ├── agent_card.json
    ├── Dockerfile · Makefile
    ├── docker-compose.yml
    ├── docker-compose.net_internal.yml
    ├── docker-compose.net_external.yml
    ├── .env.example · pyproject.toml
    ├── prompts/  workflows/
    └── tests/
```
:::

{.small}
Each subtree has its own toolchain: `uv` + `ruff` + `mypy` + `pytest` for Python, `npm` + `eslint` + `tsc` for the frontend. Never hand-edit the generated `docker-compose.agents.yml`; `make generate` rewrites it.

---

## Five kinds of branches {eyebrow="Branch roles"}

{widths="230px|330px|"}
| Branch | Cut from → merges into | Rules |
|---|---|---|
| **`main`** | merges only | Production. Never commit directly. Every merge gets a version tag (`v1.0`, `v1.1`…). If it is in `main`, it is deployable. |
| **`develop`**<br><span class="small">= <code>devel</code> in prometheus_core</span> | integration branch | All day-to-day work flows through here. It is "what the next release will look like": not always stable, but **always buildable**. {.hl} |
| **`feature/<desc>`** | `develop` → `develop` | Short-lived, one piece of work, deleted after merge. Never touches `main`. Name it `feature/login`, `feature/mesh-qa-agent`… |
| **`release/<x.y>`** | `develop` → `main` **and** `develop` | Freezes scope. Only bug fixes, docs, and version bumps. The double merge is critical and easy to forget. |
| **`hotfix/<desc>`** | `main` → `main` **and** `develop` | The emergency lane, the only branch cut from `main`. Skipping the merge back to `develop` makes the bug resurface in the next release. |

::: callout
Only `release/*` and `hotfix/*` ever merge into `main`, and both always merge back into `develop`. Everything else flows through `develop` exclusively.
:::

---

## Which base branch do I target? {eyebrow="Applied to our repos"}

::: grid 2 gap=30px
| Repo | Integration branch | Your PR base |
|---|---|---|
| **prometheus_core** (`platform/`, `sdk/`, `agent-template/`) | `devel` (default branch) | `--base devel` {.hl} |
| your team's agent repo | `main` | `--base main` {.hl} |
| agent repos on github.inl.gov (gmsh_agent…) | `main` | `--base main` |

{.small}
In the commands on the next slides, substitute `main` for `devel` when you work on a repo without a `devel` branch.

|||

#### Where we are today {.acc}

{.sm}
- `devel` carries all recent work; `main` lags behind. The first formal release is still ahead of us.
- There are no version tags or `release/*` / `hotfix/*` branches yet. SDK versions live in `sdk/pyproject.toml` (0.13.0) plus `sdk/docs/agent/AGENT_MIGRATIONS.md`.
- Existing branch names are mixed (`admin_setup_ui`, `fix/certs`, `task/…`, `feat/…`). **New branches: `feature/<short-desc>`**.
:::

---

## You cloned `idaholab` directly. Now add your fork. {eyebrow="Fork & clone conventions"}

:::: grid 2 gap=30px
```bash {.sm}
# in your existing clone of idaholab/prometheus_core
cd ~/prometheus/prometheus_core

# 1. the org repo becomes "upstream"
git remote rename origin upstream

# 2. create your fork and make it "origin"
gh repo fork idaholab/prometheus_core --clone=false
git remote add origin \
  git@github.com:<you>/prometheus_core.git
git fetch --all
git remote -v
#   origin    …:<you>/prometheus_core  (push here)
#   upstream  …:idaholab/prometheus_core (PR target)

# 3. make rebase the default for pull
git config pull.rebase true
git config rebase.autoStash true
```

|||

::: card
#### Why fork?

{.small}
**Always fork the platform**: you can't push branches to `idaholab/prometheus_core`, so the PR goes from `<you>:feature/x` to `idaholab:devel`. Your team's repo works the same way.
:::

::: card
#### One clone, three directories

{.small}
The template and the SDK live inside the platform repo, so there is nothing else to clone. `setup_agent.py` finds `../platform/.env` and copies its secrets into your new agent.

```text {.xs}
~/prometheus/
├── prometheus_core/
│   ├── platform/        # make up here
│   ├── sdk/
│   └── agent-template/  # setup_agent.py
└── <team>-agent/       # your team repo (clone)
```
:::
::::

---

## Feature branch → rebase → push → PR {eyebrow="Day-to-day loop"}

```bash {.sm hl=10}
# start from the latest integration branch
git fetch upstream
git switch -c feature/mesh-qa-agent upstream/devel

# work, commit in small logical steps
git add -p
git commit -m "Add mesh quality report skill"

# before review: replay your commits on top
git pull --rebase upstream devel
# after review comments: merge instead
#   git merge upstream/devel

# run the local checks (next slides), then publish
git push -u origin HEAD                # first push
git push --force-with-lease            # after a rebase

# open the PR against idaholab
gh pr create --repo idaholab/prometheus_core \
  --base devel --head <you>:feature/mesh-qa-agent \
  --title "Add mesh quality report skill" \
  --body-file pr.md
```

---

## Why rebase, and how to push after one {eyebrow="Day-to-day loop"}

:::: grid 3 gap=22px
::: card acc
#### Why rebase, not merge?

{.small}
**Before review**, your branch stays a straight line of *your* commits on top of the current `devel`. **Once reviewers have commented**, `DEVELOPMENT.md` asks you to merge `devel` in instead: a rebase rewrites the commits they already read.
:::

::: card
#### `--force-with-lease`, never `--force`

{.small}
A rebase rewrites your branch, so the push must be forced. `--force-with-lease` refuses if the remote has commits you have not seen, for example a reviewer's suggestion you accepted in the web UI.
:::

::: callout warn
Force-pushing is only for **your own feature branch**. Never force-push `devel` or a team repo's `main`.
:::
::::

---

## When to rebase an open PR {eyebrow="Rebase and review"}

:::: grid 2 gap=30px
{.body}
The repos use **rulesets** that interact with force-pushes:

{.sm}
- **Dismiss stale approvals on push**: any new push, including a rebase, clears existing approvals.
- **Require approval of the most recent push**: whoever pushed last cannot be the approver.
- **All review threads resolved** before merge.

::: callout good
**The rhythm in `DEVELOPMENT.md`**<br>① Rebase onto `upstream/devel` freely and tidy *before* review starts.<br>② Once reviewers have commented, push **new commits**, and **merge** `devel` in rather than force-pushing a rebase.<br>③ Must force-push anyway? `--force-with-lease`, and say so in the PR.
:::

|||

#### How maintainers merge today {.acc}

{.sm}
| Repo | Allowed merge methods |
|---|---|
| prometheus_core | **merge commit** (every branch commit lands in `devel`) |
| your team repo | your choice; merge commits keep the history |

{.small}
So squash "fix typo" and "address review" commits into the commit they fix **before approval**: the history that lands on `devel` should read cleanly.
::::

---

## Commit messages people can read later {eyebrow="Commits"}

:::: grid 2 gap=30px
- **Imperative subject, under 72 characters**, capitalized, no trailing period.
- **The body explains *why***; the diff already shows what.
- One topic per commit. No "update file" or "fix bug".
- Never commit `.env`, keys, or tokens. Every repo gitignores `.env`; check `git status` anyway.
- Lockfile changed? Commit `uv.lock` with the `pyproject.toml` change.

{.small}
Based on `platform/AGENTS.md` (subject under 72 chars, body explains why, no "update file"/"fix bug") plus the style of recent commits. The platform AGENTS.md also asks you to prefix any PR review reply written by a coding agent with 🤖.

|||

#### Real subjects from prometheus_core {.acc}

```text {.sm}
Add per-user chat history: list, rename,
    soft-delete, resume
Check in INL certificate and fix cert install
Drop HS256 identity support; RS256 only,
    split keys by role in compose
Configure agents by LLM profile, not by
    MODEL_NAME
Register the anl_asksage LLM config profile
```

::: callout bad
Avoid: `wip`, `fix`, `changes`, `address comments` as the only description of a change.
:::
::::

---

## Local checks per repo {eyebrow="Before you push"}

{.sm widths="280px|520px|"}
| Repo / area | Commands | Notes |
|---|---|---|
| **Your generated agent** | `uv run pytest && uv run ruff check .` | The template's tests use mocked `RequestContext` and `EventQueue`, and check that your card loads. {.hl} |
| **`platform/`** infra | `make test-static` and `make check-markings` | No Docker needed. `make test-integration` and `make test-system` need the stack running. |
| `platform/frontend/` | `cd frontend && make install && make check` | eslint + tsc |
| `platform/agents/<name>` | `cd agents/<name> && uv run pytest` | client-agent: <code class="wrap">PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -p pytest_asyncio.plugin tests</code> |
| **`sdk/`** | `make check && make test`<br>`make hooks` (once) | `check` = ruff lint + ruff format --check + mypy. The hooks run ruff on commit and mypy + unit tests on push. |
| `agent-template/` | `make check && make test` | Tests `setup_agent.py` itself. |
| **Any `pyproject.toml` change** | `uv lock`, commit `uv.lock` | CI runs `uv lock --check`; agent builds fail on a missing or stale lockfile. New `.py`/`.ts` files: `python3 platform/scripts/add_markings.py`. |

::: callout warn
Your team repo has **no CI**: these local checks are all there is. prometheus_core runs them in CI as well.
:::

---

## What runs where {eyebrow="Continuous integration"}

:::: grid 2 gap=30px
#### prometheus_core · `.github/workflows/` {.acc}

{.small}
On GitHub-hosted runners, for PRs to `devel` and `main` and the merge queue:

{.sm}
| Workflow | Does |
|---|---|
| `test.yml` | gitleaks, ruff, copyright markings, `uv lock --check`, image pins, hadolint + shellcheck, SDK/template/agent/backend/frontend tests, Docker builds, `compose config`, a full `make up`, slides up to date |
| `lint-workflows.yml` | actionlint + zizmor on `.github/` changes |
| codecov | **100% of changed lines covered**, project coverage may not drop |

{.small}
Run the local checks on the previous slide before you push; CI repeats them.

|||

#### Your team repo {.acc}

{.sm}
| What | CI |
|---|---|
| The scaffolded agent | **none** by default. `uv run pytest` and `uv run ruff check .` on your laptop are the checks the judges repeat. |

::: callout warn
**Fork PRs** to prometheus_core may need a maintainer to approve the workflow run before the checks report.
:::
::::

Note: The merge_group trigger exists in test.yml; whether the merge queue is switched on is a branch setting. Uncovered changed lines are annotated inline in the PR diff.

---

## Who can merge where {eyebrow="Branch protection"}

| Branch | Who merges | How you contribute |
|---|---|---|
| **prometheus_core `devel`** | maintainers, once CI passes and a **code owner** approves | fork, then a PR to `idaholab:devel` {.hl} |
| prometheus_core `main` | maintainers, for releases | — |
| **your team repo `main`** | the repo owner, after reviewing the PR | teammates fork it and open PRs {.hl} |

:::: grid 3
::: card
#### PR required

{.small}
Nobody pushes to `devel` or a team repo's `main` directly. Every change arrives as a PR from a fork.
:::

::: card
#### Someone else approves

{.small}
You cannot approve your own PR. In a team repo the owner reviews everyone's PRs, and a teammate reviews the owner's.
:::

::: card
#### Reviewers and template

{.small}
prometheus_core requests reviewers from `CODEOWNERS` and pre-fills a PR template (next slide). Your team repo has neither.
:::
::::

Note: CONTRIBUTING.md: "Reviewers are requested automatically from CODEOWNERS ... merged once CI passes and a code owner approves it." /hackathon/ and /agent-template/ are owned by dschwen and maxnezdyur.

---

## A description reviewers can act on {eyebrow="Opening a PR"}

::: cols 1.3fr 1fr
```markdown {.sm}
refs PPLT-123

## Reason
Meshes from `geometry_meshing` go to MOOSE
unchecked; bad elements fail late.

## Design
A `mesh_quality_report` skill reads an Exodus
artifact and reports scaled Jacobian and
aspect-ratio histograms.

## Impact
- New env var `MESHQA_MAX_ELEMENTS` (default 2e6)
- Tested: `uv run pytest` (6 passed), ruff; chat
  "check the mesh I just made" → report renders.

## Checklist / AI assistance
- [x] targets devel, one logical change …
- [x] AI tools were used: Claude Code, tests
```

|||

- **Title**: an imperative sentence, like the commit subject ("Add…", "Fix…", "Stop…").
- **Reference the issue or JIRA task** (`refs #123`, `closes #123`, `PPLT-…`).
- `.github/PULL_REQUEST_TEMPLATE.md` pre-fills **Reason / Design / Impact**, a checklist, and an **AI assistance** box: you remain responsible for every line.
- **Small and focused.** One topic. Split refactors from behavior changes.
:::

---

## More PR conventions {eyebrow="Opening a PR"}

::: grid 2 gap=30px
- List the **commands you ran**, and any env var, Docker image, credential, or DeepLynx behavior change (`sdk/AGENTS.md`).
- **SDK (`sdk/`) API changes**: bump the version (`make bump-minor`/`bump-patch`), add a section to `docs/agent/AGENT_MIGRATIONS.md`, and update `specs/` with tests that cite the REQ IDs.
- UI change? Add a screenshot.
- Open as **draft** (`gh pr create --draft`) while it is still in progress.

|||

#### Handy commands {.acc}

```bash {.xs}
gh pr view --web          # open in browser
gh pr checks              # CI status
gh pr ready               # draft → ready
```
:::

---

## What reviewers look for, and how to respond {eyebrow="Code review"}

:::: grid 2 gap=24px
::: card
### As an author

{.sm}
- Reply to **every** thread. "Fixed in 8e46a68: …" with the commit SHA and a sentence of explanation.
- Disagree with reasons. Maintainers push back too, sometimes with a table of cases.
- Resolve threads only when the reviewer is satisfied, or after replying.
- Accepted a GitHub suggestion in the web UI? `git pull` before your next push.
- `devel` moved during review? Merge it in; don't force-push a rebase.
:::

::: card
### As a reviewer

{.sm}
- Be concrete: file:line, the scenario that breaks, ideally a failing test.
- Check the tests enforce what they claim. In `sdk/`, reviewers check that tests citing a `REQ-…` ID actually test it.
- Check the lockfile, the version bump, and the migration note.
- Separate "must fix" from "nit".
:::
::::

---

## The project stance, and the bar {eyebrow="Code review"}

:::: cols 1fr 1fr gap=24px
::: card
### Project stance

{.tiny}
From the Prometheus project philosophy.

{.sm}
- Experimental project: **breaking changes are fine**.
- No backward-compatibility shims, deprecation warnings, or workarounds. Fix root causes.
- When docs and code disagree, fix the docs in the same PR.
- Agent-authored review text is marked with 🤖.
:::

|||

::: callout
A real example: platform PR #98 had about 10 inline findings, each reproduced with a small test. The author answered each one with the fixing commit. That is the bar.
:::
::::
