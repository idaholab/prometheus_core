---
title: Welcome & Kickoff
footer: Day 1 · Welcome & kickoff · https://idaholab.github.io/prometheus_core/hackathon
accent: welcome
index:
  time: '12:15'
  heading: Welcome &amp; kickoff
  color: var(--navy)
  blurb: 'Agenda, mentors, the Day 2 challenge in brief, and how Prometheus works from an agent author''s view: the platform at a glance, one chat turn, eight terms, what the platform does for you, the repos you''ll touch.'
---

# Welcome & kickoff {.title kicker="Agent developer hackathon · Day 1 · 12:15 pm" pills="All participants | 45 min | Press N for notes · O for overview"}
What Prometheus is, how the pieces fit together, who is here to help, and what "done" looks like on Day 2.
Note: ANL welcoming address goes first. Then walk the agenda, the architecture overview, mentors, and the Day 2 acceptance criteria preview.

---

## You did the homework. Today you add… {eyebrow="Welcome"}

<div class="grid g4" style="margin-top:10px">
<div class="card acc"><div class="kpi"><span class="v">1</span></div><h3>Understanding</h3><p class="small">How the platform, the repos, and an agent fit together, and why.</p></div>
<div class="card acc"><div class="kpi"><span class="v">2</span></div><h3>A working agent</h3><p class="small">A "hello world" agent from the template, registered and called from the chat.</p></div>
<div class="card acc"><div class="kpi"><span class="v">3</span></div><h3>A reviewed PR</h3><p class="small">One practice pull request to a neighbour's repo: the way your team works on Day 2.</p></div>
<div class="card acc"><div class="kpi"><span class="v">4</span></div><h3>A team</h3><p class="small">4–5 people, a name, and a room for Day 2.</p></div>
</div>

::: callout info
We assume your platform already starts with `make up` and DeepLynx is set up. Not quite there? Each deck ends with **bonus catch-up slides**, and mentors will help.
:::

---

## Follow along online {eyebrow="Links"}
> Everything you see today is online. Open it on your laptop and keep it there.

<div class="grid g2" style="margin-top:10px">
<div class="card acc"><h3>These slides</h3><p><a href="https://idaholab.github.io/prometheus_core/hackathon">idaholab.github.io/prometheus_core/hackathon</a></p><p class="small">Every Day 1 deck, the Day 2 challenge and the cheat sheet.</p></div>
<div class="card acc"><h3>Platform documentation</h3><p><a href="https://idaholab.github.io/prometheus_core">idaholab.github.io/prometheus_core</a></p><p class="small">Architecture, deployment, the SDK, and the agent template.</p></div>
</div>

Note: Point out that the slide URL is also in the footer of every slide in this deck.

---

## Day 1 {eyebrow="Agenda" content-style="gap:0"}

::: agenda
- 12:15 | Welcome & kickoff | ANL welcome · agenda · mentors · Day 2 preview · how Prometheus works {.now}
- 1:00 | GitHub overview & PR workflow | The repos · branching · fork, branch, rebase · opening a PR · review
- 1:45 | Your local platform | What runs where · logs and health checks · LLM flavors · DeepLynx for files · when things break
- 2:30 | Break
- 2:45 | Building an agent | The code you write · the card that gets you called · files in, artifacts out · asking the user · LLMs · running and testing
- 3:30 | End-to-end dry run (hands-on) | Clone, deploy, edit the "hello world" agent, put it in your own repo, review a neighbour's practice PR. Mentors circulate.
- 4:30 | The challenge & team formation | The Day 2 challenge (a table-and-plot agent) · practice files · teams of 4–5 · team name and Day 2 room
:::

---

## Mentors {eyebrow="Your hosts"}
> Ask any of these people when you are blocked. During the dry run they will be walking the room.

:::: grid 4
::: card
### Daniel Schwen

<div class="row" style="gap:8px; flex-wrap:wrap"><span class="pill acc">Platform</span><span class="pill acc">Agent base class</span></div>
:::

::: card
### Brandon Biggs

<div class="row" style="gap:8px; flex-wrap:wrap"><span class="pill acc">Platform</span><span class="pill acc">LLMClient</span></div>
:::

::: card
### Isaac Huffman

<div class="row" style="gap:8px; flex-wrap:wrap"><span class="pill acc">DeepLynx</span></div>
:::

::: card
### Mengnan Li

<div class="row" style="gap:8px; flex-wrap:wrap"><span class="pill acc">Agents</span></div>
:::

::: card
### Mauricio Tano

<div class="row" style="gap:8px; flex-wrap:wrap"><span class="pill acc">Agents</span></div>
:::

::: card
### Zach Prince

<div class="row" style="gap:8px; flex-wrap:wrap"><span class="pill acc">Agents</span></div>
:::

::: card
### Chris Rubel

<div class="row" style="gap:8px; flex-wrap:wrap"><span class="pill acc">Git</span><span class="pill acc">Team building</span></div>
:::
::::

Note: The prometheus_core maintainers are the people who can merge platform PRs.

---

## Everyone builds the same agent {eyebrow="Day 2 preview"}
> Details at 4:30 pm. Here is the short version, so you can listen to every session with it in mind.

:::: grid 2 gap=30px
::: card acc tag="Skill 1"
### Extract a table from a markdown document

{.body}
The user uploads a document and says "the table with population data". Your agent finds it by its caption, parses it, and publishes it as an artifact.
:::

::: card acc tag="Skill 2"
### Plot tabular data

{.body}
From that table, or from an uploaded CSV, your agent draws the plot the user asked for, and asks which columns to use if it doesn't know.
:::
::::

:::: grid 3
::: card
#### 4–5 hours of building

{.small}
Teams of 4–5, the same practice file for everybody, one agent per team.
:::

::: card
#### A hidden test

{.small}
At the demo the judges bring a file and prompts nobody has seen: finding tables by caption, matching column names, plotting a CSV.
:::

::: card
#### Judging & awards

{.small}
A must-have gate, the hidden test, a rubric, and a set of "best agent in…" awards.
:::
::::

::: callout
What you will use from today: **uploads and artifacts** (01, 03), **DeepLynx** (03), **the agent card and routing** (04), **input-required** (04), **LLMClient** (04).
:::

---

# How Prometheus works {.section num="01"}
Just enough of the platform to build an agent tomorrow: what it does for you, and what happens when someone types into the chat.

---

## A chat front door to a team of specialist agents {eyebrow="Why Prometheus"}

:::: grid 2 gap=36px
{.body}
Engineering work needs many specialized tools: meshing, CFD, uncertainty quantification, requirements, literature search.

{.body}
Prometheus wraps each tool in an **agent**. A user just asks in a chat, and an **orchestrator** decides which agents to call, in what order, and with which files.

|||

::: card acc
### Your part this hackathon

{.body}
Write **one agent**: a Python class with a method that does the work, and a card that says what it can do. The platform handles everything around it.
:::
::::

---

## The platform at a glance {eyebrow="The big picture"}

<div class="dg">
<div class="row" style="align-items:stretch; gap:0">
<div class="box sky" style="flex:1"><b>Chat UI</b><span class="small">localhost:5150</span><span class="small">uploads, plots, forms</span></div>
<div class="arrow-h" style="width:50px"></div>
<div class="box navy" style="flex:1.3"><b>Orchestrator</b><span class="small">an LLM that calls agents' skills step by step, reading each result</span></div>
<div class="arrow-h" style="width:50px"></div>
<div class="box orange" style="flex:1.3"><b>Agents</b><span class="small">form-filler, OSTI research, synthesis… and <b>yours</b></span></div>
</div>
<div class="arrow-v"><span>supporting services</span></div>
<div class="row" style="gap:20px; align-items:stretch">
<div class="box gray" style="flex:1"><b>Registry</b><span class="small">agents announce themselves at startup</span></div>
<div class="box gray" style="flex:1"><b>LLM profile</b><span class="small">one key, many models</span></div>
<div class="box teal" style="flex:1"><b>DeepLynx</b><span class="small">stores uploads and result files</span></div>
<div class="box gray" style="flex:1"><b>State store</b><span class="small">conversations, artifacts, background tasks</span></div>
</div>
</div>

{.small}
All of it runs on your laptop in Docker. The backend is also the agent registry; each agent calls its LLM provider directly, picked by `LLM_CONFIG_PROFILE`. The appendix lists every container.

---

## "Plot the population of Brie Basin from this report" {eyebrow="One chat turn"}

::: steps
#### The upload is stored

{.small}
`report.md` goes to DeepLynx and becomes an **artifact** in the conversation.

#### The orchestrator picks a skill

{.small}
Its LLM sees every registered skill as a tool, and calls your `extract_table` with the artifact id and "population".

#### Your agent works

{.small}
It reads the file, finds the table, publishes it as a new artifact, and returns its id.

#### The orchestrator chains

{.small}
It reads your result and calls `plot_table` with the new id. Missing a column? The user gets a form.

#### The chat shows the plot

{.small}
The PNG artifact renders in the conversation, with the orchestrator's summary.
:::

---

## Eight words you will hear all day {eyebrow="Vocabulary"}

{widths="230px|"}
| Term | Meaning |
|---|---|
| **Agent** | A small Python service, a subclass of `PrometheusAgent` |
| **Skill** | One thing an agent can do. Each skill is one tool for the orchestrator. |
| **Agent card** | `agent_card.json`: the skills, described for the orchestrator's LLM |
| **Orchestrator** | The client agent: an LLM loop that calls skills and chains them |
| **Artifact** | A file or data result in the conversation (an upload, a table, a plot) |
| **DeepLynx** | INL's data store, where uploads and result files live |
| **Registry** | Where running agents announce themselves (the backend's `/v1/agents`) |
| **Flavor** | The kind of LLM you ask for in code: `small`, `medium`, `large`, `vision`… |

---

## What the platform does for your agent {eyebrow="What you get for free"}

{widths="470px|"}
| Service | You use it via |
|---|---|
| Registration and discovery | nothing: it happens at startup |
| Routing the user's request to your skill | a good card |
| File storage, upload handling, viewers | artifacts, DeepLynx |
| Forms for missing inputs and follow-up questions | `required` parameters, `send_input_required` |
| Live progress in the chat | `send_status_update`, with `"streaming": true` in the card |
| Approval before costly steps | `"requires_approval": true` |
| Background tasks for long jobs | `declare_long_running` |
| LLM access, any of several providers | `self.llm_client(...)` + `LLM_CONFIG_PROFILE` |
| Per-conversation memory | `load_context_state` / `save_context_state` |

{.small}
How to use each one: the agent session at 2:45 pm.

---

## Two repositories you will touch {eyebrow="The code"}

:::: cols 1.15fr 1fr gap=28px
```text {.sm}
prometheus_core/          # idaholab/prometheus_core, devel
├── platform/             # the stack: make up here
├── sdk/                  # prometheus_api (in your image)
└── agent-template/       # setup_agent.py

<team>-agent/             # github.com/<owner>, main
├── agent.py · agent_card.json
└── tests/                # one repo per team
```

|||

::: card tag="one clone"
### prometheus_core

{.small}
A monorepo since Oct 9: the platform, the SDK (`sdk/`, formerly `prometheus_api`), and the agent template (`agent-template/`, formerly `prometheus_agent_template`). Run commands from inside the directory you work on.
:::

::: card acc tag="your code"
### Your team repo

{.small}
Today a hello agent in a repo of your own. Tomorrow one teammate owns the team's agent repo; the others fork it and send PRs.
:::
::::

::: callout warn
The code moves fast and some docs lag behind. When a doc disagrees with these slides or the code, trust the code and ask a mentor. The appendix lists the known stale spots.
:::

---

## Help {eyebrow="Where to find things"}

:::: grid 2 gap=30px
| What | Where |
|---|---|
| The mentors | in the room, all day |
| Agent developer guide | `sdk/docs/agent/GUIDE.md` in `prometheus_core` |
| These slides | `index.html`; every deck has an appendix (key `A`) |
| Platform repo | `github.com/idaholab/prometheus_core` |
| Issues and tasks | JIRA project `PPLT` |
| Chat | Teams |

|||

::: takeaways
### You write one agent

The platform does the rest.

### The orchestrator chains skills

Your card decides whether you get called.

### Files are artifacts

Stored in DeepLynx, passed by id.
:::
::::

::: callout good
Next: GitHub & PR workflow (1:00 pm). Keep your platform running.
:::

---

# Bonus: catch-up slides {.section .bonus num="+"}
For participants who could not finish the homework. Work through these with a mentor while the session goes on.

---

## Is your laptop ready? {eyebrow="Bonus · Homework check"}

{widths="330px|430px|"}
| Homework item | Quick check | If it fails |
|---|---|---|
| Access to `idaholab/prometheus_core` | open `github.com/idaholab/prometheus_core` in the browser | ask the organizer to add your github.com account; deck 02 bonus |
| Docker installed and running | `docker info`, `docker compose version` (≥ 2.20) | install Docker Desktop and start it |
| Platform cloned | `ls ~/prometheus/prometheus_core` shows `platform`, `sdk`, `agent-template` | deck 02 bonus (clone commands) |
| Base image builds | `LOCAL_SDK=true` in `platform/.env`, then `make base-image` in `prometheus_core/platform` | deck 03 bonus (step 1) |
| Platform starts | `make up` in `prometheus_core/platform`, then `http://localhost:5150` | deck 03 bonus (`.env`, "the stack won't start") |
| Local DeepLynx (**required**: no agent starts without it) | `http://localhost:3000` shows the DeepLynx UI | deck 03 (local DeepLynx) |
| `uv` (for the agent session) | `uv --version` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `gh` (decks 02 and 05) | `gh auth status` | `brew install gh` (needs admin), or copy the release binary from `github.com/cli/cli/releases` into `~/.local/bin`; then `gh auth login`. No `gh`? Use the Fork and "Compare & pull request" buttons on the web. |

---

# Appendix: reference {.section .appendix num="A"}
Reference material behind the talk. Skipped in the session; use it when you need the details.

---

# Platform architecture overview {.section num="01"}
From the big picture to one concrete chat turn: which services exist, what each does, and how a question becomes work done by specialist agents.

---

## A chat front door to a team of specialist agents {eyebrow="Why Prometheus"}

:::: grid 2 gap=36px
{.body}
Nuclear engineering work spans many specialized tools: meshing (Gmsh, Cubit), CFD (OpenPronghorn), UQ (RAVEN), BIM/IFC generation, requirements, safety analysis, literature search. Each needs expert setup.

{.body}
Prometheus wraps each tool in an **agent**: a small web service that describes what it can do (its **agent card**) and accepts requests over a standard protocol (**A2A**).

{.body}
An **orchestrator** (the client-agent) reads your chat message and calls agents one step at a time (an LLM tool-calling loop), choosing each next call from the previous results. It asks you for missing inputs and passes files (**artifacts**) between agents.

|||

::: card acc
### You, this hackathon

{.body}
You write **one agent**. The platform handles the chat UI, orchestration, discovery, authentication, state, and file hand-off. Your code implements one method: `_execute(params, context, event_queue)`.
:::

::: card
### The contract is the protocol

{.body}
Any service that speaks A2A and publishes a card can join. It can live in the platform repo or in its own repo, and it registers itself at startup.
:::
::::

---

## Tiers of the platform {eyebrow="The big picture"}

<div class="grid" style="grid-template-columns: 470px 1fr; gap:40px; flex:1; min-height:0">
<div class="center" style="min-height:0"><img alt="Platform tiers schematic" class="fit" src="assets/platform_schema.png" style="max-height:640px"/></div>
<div class="col" style="justify-content:center; gap:14px">
<div class="card"><h4>Client</h4><p class="small">The user and the web frontend. Today that is a React single-page app (the diagram's "e.g. Chainlit" is historical).</p></div>
<div class="card"><h4>App server tier</h4><p class="small">The backend, the orchestrator agent, and the state store (Valkey). The <b>backend</b> is also the agent registry and A2A gateway; agents call LLM providers directly.</p></div>
<div class="card"><h4>Agent runtime tier: pluggable slots</h4><p class="small">Any A2A-conformant agent registers and appears here. Each agent wraps a backend tool: a hosted service, licensed software, or an HPC code.</p></div>
<div class="card"><h4>DeepLynx data layer</h4><p class="small">Stores uploads and agent outputs with provenance. <code>deeplynx://</code> URIs let agents hand files to each other.</p></div>
<div class="card"><h4>Model development pipeline</h4><p class="small">Long-term vision: training, validation, and a model registry that serves models to the agents. Not needed for the hackathon.</p></div>
</div>
</div>

---

## Twelve words you will hear all day (1/2) {eyebrow="Vocabulary"}

{widths="230px|"}
| Term | Meaning in Prometheus |
|---|---|
| **Agent** | A Python web service (subclass of `PrometheusAgent`) that performs one or more skills. |
| **Skill** | One capability of an agent, with an `id`, description, and JSON `inputSchema`. Each skill is one tool for the orchestrator LLM. |
| **Agent card** | `agent_card.json`: name, description, capabilities, skills. Its skill descriptions, `usage_notes`, and schemas are what the orchestrator LLM reads to decide whether and how to call you. |
| **A2A** | Agent-to-Agent protocol, v1.0: JSON-RPC 2.0 over HTTP (`SendMessage`, `SendStreamingMessage`). |
| **Client agent** | The orchestrator / planner. It plans, collects parameters, dispatches, and aggregates. |
| **Registry / gateway** | The backend. Agents `POST /v1/agents` to register; the orchestrator calls them via `/a2a/{agent_name}`. Stored in Valkey. |

---

## Twelve words you will hear all day (2/2) {eyebrow="Vocabulary"}

{widths="230px|"}
| Term | Meaning in Prometheus |
|---|---|
| **Artifact** | An output (JSON, text, or a file by URI) recorded in the per-conversation catalog so later steps and the UI can use it. |
| **DeepLynx** | INL's data warehouse. It stores uploads and agent files and resolves `deeplynx://organizations/…/items/N`. |
| **Workflow** | A YAML template that chains skills (sequential, parallel, or DAG) with parameter bindings between steps. |
| **contextId** | The conversation ID. It scopes artifacts, state, and ownership across all agents in one chat. |
| **Flavor / profile** | An LLM *flavor* (`small`, `medium`, `large`…) is chosen in code; a *profile* chosen by deployment maps flavors to real models. `LLM_CONFIG_PROFILE` has no default (`anthropic`, `openai`, `genesis`, `ollama`, …); every profile reads `LLM_API_KEY`. |
| **Base image** | `prometheus_api:local`, built on your laptop from `sdk/` when `LOCAL_SDK=true` is in `platform/.env`. Every Python agent is built `FROM` it. |

---

## What actually runs: `docker compose` on branch `devel` {eyebrow="Concrete architecture"}

<div class="dg" style="gap:0">
<div class="row" style="justify-content:center">
<div class="box gray" style="width:260px"><b>Browser</b><span class="mono">localhost:5150</span></div>
</div>
<div class="arrow-v"><span>/api/* (same origin, proxied)</span></div>
<div class="row" style="justify-content:center; gap:18px">
<div class="box sky" style="width:330px"><b>frontend-dev</b><span>React 18 + Vite · :5150</span><span class="mono">(frontend-prod: nginx :8080)</span></div>
<div class="arrow-h" style="width:60px"></div>
<div class="box sky" style="width:370px"><b>backend</b><span>FastAPI · host :8600 → :8000</span><span class="mono">auth · sessions · SSE · uploads · artifacts</span></div>
<div class="arrow-h" style="width:60px"><span>A2A</span></div>
<div class="box navy" style="width:330px"><b>client-agent</b><span>orchestrator · :8000 (internal)</span><span class="mono">tool-calling loop · workflows</span></div>
</div>
<div class="row" style="justify-content:flex-end; padding-right:150px"><div class="arrow-v" style="width:40px"><span>discovery + A2A</span></div></div>
<div class="row" style="gap:18px; align-items:stretch">
<div class="box teal" style="width:240px"><b>redis</b><span>Valkey 9.1 · :6379</span><span class="mono">prometheus_platform-redis-1</span></div>
<div class="box gray" style="width:250px"><b>admin-db</b><span>Postgres 16</span><span class="mono">users · keys · OIDC</span></div>
<div class="box orange" style="flex:1"><b>backend: agent registry + A2A gateway</b><span>GET/POST /v1/agents · POST /a2a/{agent_name}</span><span class="mono">registrations in Valkey · Bearer AGENT_SECRET</span></div>
</div>
<div class="arrow-v"><span>POST /a2a/{agent_name} → the agent's registered URL</span></div>
<div class="row" style="gap:14px">
<div class="box green" style="flex:1"><b>form-filler-agent</b></div>
<div class="box green dash" style="flex:1"><b>osti-research-agent</b><span class="mono">OPTIONAL_AGENTS=true</span></div>
<div class="box green" style="flex:1"><b>synthesis-agent</b></div>
<div class="box green dash" style="flex:1"><b>debug agents</b><span class="mono">DEBUG_AGENTS=true</span></div>
<div class="box green dash" style="flex:1"><b>your agent</b><span class="mono">in-tree or external</span></div>
</div>
</div>

{.tiny}
All containers share one bridge network, `prometheus_platform_agent-network`. The backend is the only component the browser talks to, and only the ports shown are published to your host. Agents call their LLM provider directly (`LLM_CONFIG_PROFILE`); there is no LLM proxy.

---

## Every service in `docker-compose.yml` {eyebrow="Service inventory"}

{.sm}
| Service | Container `prometheus_platform-…-1` | Image / build | Host port | Role |
|---|---|---|---|---|
| **frontend-dev** | `…-frontend-dev-1` | `frontend/Dockerfile` target `dev` | 5150 | Vite dev server (profile `dev`, the default) |
| **frontend-prod** | `…-frontend-prod-1` | same, target `prod` (nginx) | 8080 | Built SPA (profile `prod`) |
| **backend** | `…-backend-1` | `./backend` (uv image + `../sdk`) | 8600 | Login, sessions, chat turn, SSE, uploads, artifacts, admin API, mesh conversion, **agent registry + A2A gateway** |
| **client-agent** | `…-client-agent-1` | `./agents/client-agent` | (8001 in system-test mode) | Orchestrator: tool-calling loop, follow-ups, approval, dispatch |
| **admin-db** | `…-admin-db-1` | `postgres:16-alpine` | — | Users (bcrypt), OIDC providers, RS256 signing keys |
| **redis** | `…-redis-1` | `valkey/valkey-bundle:9.1.3` | 6379 | Conversation state, browser sessions, SSE event bus, artifact catalog, task graph, caches |
| **agents/\*** | per agent | `agents/<name>/docker-compose.yml` | — (8008 artifact-debug) | Included automatically by `make generate` |

{.tiny}
Source: `platform/docker-compose.yml` on `devel`. There is no Chainlit service any more: it was removed in PR #91 (Aug 2026), and the React app in `frontend/` plus the FastAPI `backend/` replace it.

---

## From "Mesh this STEP file" to a mesh in the viewer {eyebrow="One chat turn, end to end"}

:::: grid 2 gap=28px
::: steps
#### Browser → backend

{.small}
`POST /api/chat/messages {query, upload_ids…}`. The browser authenticates with its session cookie and listens on one SSE stream, `/api/events`.

#### Backend → client-agent

{.small}
A2A `SendStreamingMessage` with `contextId` = conversation ID and `metadata.userToken` = a per-turn RS256 identity JWT.

#### Decide, step by step

{.small}
The orchestrator LLM sees the conversation, the artifact catalog, and every skill and workflow as a tool. It calls one, reads the result, calls the next (≤ 12 steps).

#### Missing inputs? Approval needed?

{.small}
It replies `needs_info` (follow-up form) or `plan_ready` (Approve/Reject). Your next message continues the turn.
:::

|||

<div class="steps" style="counter-reset: st 4">
<div class="step"><div><h4>Dispatch</h4><p class="small"><code>POST backend:8000/a2a/{agent_name}</code>, then the backend forwards to the agent's registered URL with <code>Bearer AGENT_SECRET</code>.</p></div></div>
<div class="step"><div><h4>Agent works</h4><p class="small"><code>_execute()</code> runs. Status updates stream back through client-agent → backend → SSE to the UI as they happen.</p></div></div>
<div class="step"><div><h4>Artifacts</h4><p class="small">Outputs are registered in the conversation catalog (Valkey). Files usually live in DeepLynx as <code>deeplynx://…</code>.</p></div></div>
<div class="step"><div><h4>Render</h4><p class="small">The backend attaches a <code>render_hint</code> (mesh, ifc, pdf, image, json…) and serves the bytes from <code>/api/artifacts/{id}/content</code>. The UI picks a viewer.</p></div></div>
</div>
::::

---

## How the client-agent runs a turn {eyebrow="Inside the orchestrator"}
> One tool-calling loop (`agents/client-agent/orchestrator/agent_loop.py`). Every skill, every workflow template, and an `ask_user` tool is an LLM tool. After each result the model picks the next fully parameterized call, and it stops when it answers without one.

::: flow
- [navy flex=1] **Tools** | one per skill, one `workflow_*` per template, `ask_user`
- ->  {w=34}
- [navy flex=1] **LLM turn** | sees the transcript, the artifact catalog, and all tools
- ->  {w=34}
- [navy flex=1] **Validate** | JSON Schema, known artifact ids; errors go back to the model
- ->  {w=34}
- [navy flex=1] **Run** | A2A via the backend gateway; independent calls in parallel
- ->  {w=34}
- [navy flex=1] **Result** | summary + artifact ids back into the transcript; repeat, ≤ 12 turns
:::

::: callout
Per skill the model sees your **description**, `usage_notes`, the approval flag, and the `inputSchema` (property descriptions, types, enums; `x_*` keys stripped). It does **not** see tags or the agent description. After each call it also reads your **result JSON**: card and result together decide whether you get chained correctly.
:::

---

## How a turn ends {eyebrow="Inside the orchestrator"}

:::: grid 4
::: card tag="needs_info"
{.small}
A required input the model couldn't fill, an `ask_user` question, or an agent's INPUT_REQUIRED: a form is shown. The backend gives up after 5 rounds in a row.
:::

::: card tag="plan_ready"
{.small}
The next step has a `requires_approval` call. One Approve covers every approval-gated call in that step (usually just one); steps that already ran stay done. *Planned: multi-agent workflows that show the whole plan up front, to accept or change.*
:::

::: card tag="completed / answer"
{.small}
The model's final reply, with or without skill calls. The chat text is the orchestrator's summary; your artifacts render from the catalog.
:::

::: card tag="error"
{.small}
A loop error or the 12-step cap. If no skill fits, the model just says so; anything that could run has run.
:::
::::

{.small}
Every turn ends in one of these states. The chat text is written by the orchestrator LLM; your agent's output shows up as artifacts and status updates.

---

## A2A v1 in one slide {eyebrow="Protocol"}

:::: grid 2 gap=30px
```json {.sm}
{ "jsonrpc": "2.0", "id": "1",
  "method": "SendMessage",      // or SendStreamingMessage
  "params": {
    "message": {
      "messageId": "msg-1",
      "role": "ROLE_USER",
      "contextId": "conv-123",  // conversation
      "metadata": {
        "skillId": "geometry_meshing",
        "userToken": "<RS256 JWT>" },
      "parts": [ { "text": "{\"element_size\": 2.0}" } ]
    },
    "configuration": { "returnImmediately": false } } }

Headers:  A2A-Version: 1.0
          Authorization: Bearer <token>
```

|||

{.sm}
- **JSON-RPC 2.0 over HTTP.** One endpoint per agent (`POST /`); the `method` field selects the operation.
- The **skill** goes in `message.metadata.skillId`, and the **conversation** in `message.contextId`.
- **Parameters** travel as a JSON string in the first text part. The base class parses it into the `params` dict.
- Tasks report **exact** states: `TASK_STATE_WORKING`, `_COMPLETED`, `_FAILED`, `_INPUT_REQUIRED`, `_CANCELED`…
- The final answer is exactly **one text part** containing the JSON of the dict you returned.
- Streaming is used only if the card says `"capabilities": {"streaming": true}`.

::: callout warn
Older docs show v0.3 syntax (`message/send`, `role: "user"`, `params.context.skillId`). Agents now reject it with `-32601 Method not found`.
:::
::::

---

## Who proves what to whom {eyebrow="Trust boundaries"}

{.sm widths="250px|330px|"}
| Secret | Used between | What it proves / where it lives |
|---|---|---|
| **Session cookie** `prometheus_session` | Browser → backend | An HS256 JWT signed with `BACKEND_JWT_SECRET`. The backend refuses to start if it is empty or still the `change-me…` placeholder. Sessions live in Valkey. |
| **`AGENT_SECRET`** | Everything ↔ backend registry and gateway; gateway → every agent | A shared bearer token. Agents reject any other token with 401. It also lets agents register and the orchestrator discover and call them (the SDK reads it from `LITELLM_MASTER_KEY`, which compose sets to `${AGENT_SECRET}`). |
| **`userToken`** (RS256 JWT) | Backend → orchestrator → agents | The identity of the human user, minted per turn. Agents verify it against `JWKS_URL` (the backend's `/.well-known/jwks.json`). Required by default. |
| **`ADMIN_DB_ENCRYPTION_KEY`** | Backend at rest | A Fernet key that encrypts OIDC client secrets and signing keys in admin-db. `make up` (`init-env`) generates it. |
| **Provider key** | Agents → LLM API | `LLM_API_KEY`, the same variable for every profile. `LLM_CONFIG_PROFILE` decides which provider it is for. |
| **DeepLynx key + secret** | Agents/backend → DeepLynx | `DEEPLYNX_KEY/SECRET/ORG_ID/PROJECT_ID`; **every agent needs them to start**. They are global by default (`CREDENTIAL_BROKER=env`), or per user via Vault. |

{.tiny}
Reference: `platform/docs/docs/dev-docs/encryption-and-keys.md` and `multi-user-setup.md`, both current on `devel`.

---

## Artifacts and DeepLynx {eyebrow="Moving data between agents"}

::: flow
- [green flex=1] **Agent A** | `send_deeplynx_artifact(file_path=…)`
- -> upload {w=84}
- [sky flex=1.1] **DeepLynx** | ~deeplynx://organizations/1/projects/1/items/42
- -> ref {w=84}
- [teal flex=1.1] **Artifact catalog** | ~artifacts:conv:{id}:by_id | (Valkey, 7-day TTL)
- -> id {w=84}
- [green flex=1] **Agent B** | `get_artifact_file_path(id)`
:::

:::: grid 3
::: card
#### What an artifact is

{.small}
An `ArtifactReference`: `artifact_id`, `name`, `description`, and a `uri` *or* inline `json_body`/`text_body`, plus `mime_type`, `json_type`, `tags` and `metadata`. Scoped to one conversation.
:::

::: card
#### How chaining works

{.small}
The orchestrator passes the full catalog to every agent. For inputs marked `x_artifact_ref`, the orchestrator LLM picks an artifact id from a new upload, an earlier result, or the catalog; unknown ids are rejected.
:::

::: card
#### How the UI shows it

{.small}
The backend picks a viewer from `json_type`, then `mime_type`, tags, and file extension: VTK mesh (Exodus/STL), IFC, PDF, image, Mermaid, JSON, markdown report, or download.
:::
::::

::: callout warn
DeepLynx is **required**. Every skill call writes an execution record there (`self.execution_record_id`), so an agent without DeepLynx credentials refuses to start, and uploads are not stored. We set up a local DeepLynx in the deployment session.
:::

---

## Agents that ship with the platform {eyebrow="What is already there"}

{.sm}
| Directory | Card name → route key | Skills | Default? |
|---|---|---|---|
| `agents/client-agent` | nuclear-analysis-client-agent | The orchestrator; excludes itself from discovery | always |
| `agents/form-filler-agent` | form-filler-agent | `fill_form`: extract structured data per a JSON schema | yes |
| `agents/optional/osti-research-agent` | osti-research-agent | `search_literature`: OSTI search, PDF download, synthesis. Heavy PDF/ML build | `OPTIONAL_AGENTS` {.hl} |
| `agents/synthesis-agent` | synthesis-agent | `synthesize_material_analysis`. **About 100 lines: the best small example.** | yes |
| `agents/debug-agents/artifact-debug-agent` | artifact-debug-agent | `create_svg_artifact`, `convert_svg_to_png`, `create_json_artifact`, plus a workflow | `DEBUG_AGENTS` {.hl} |
| `agents/debug-agents/corrosion-agent` | corrosion-analysis-agent | Mock specialist; demonstrates `send_input_required` and context state | `DEBUG_AGENTS` {.hl} |
| `agents/debug-agents/material-data-agent` | material-data-agent | `list_materials`, `get_material_data`, `get_regulatory_limits`… | `DEBUG_AGENTS` {.hl} |
| `agents/debug-agents/radiation-agent`, `thermal-agent` | …-analysis-agent | Mock specialists; thermal emits a JSON type with its own viewer | `DEBUG_AGENTS` {.hl} |
| `agents/debug-agents/thread-pattern-agent` | thread-pattern-debug-agent | Reference for `PrometheusWorker` and `declare_long_running` | `DEBUG_AGENTS` {.hl} |

{.tiny}
The route key is the card `name` lowercased with spaces turned into hyphens. The platform workflow `comprehensive_material_analysis` chains the debug agents, so it only works with `DEBUG_AGENTS=true`.

---

## Agents living in their own repos (INL network only) {eyebrow="The wider ecosystem"}

:::: grid 3 gap=14px
::: card
#### gmsh_agent (meshing)

{.small}
STEP → tetrahedral Exodus mesh with Gmsh. Branch `agentic-hex-meshing`: an LLM tool loop driving a sandboxed Python kernel.
:::

::: card
#### agent-sandbox-mcp

{.small}
A Python notebook MCP server with per-user session isolation. It is the code-execution sandbox used by agents.
:::

::: card
#### bim_agent ("Alchemy")

{.small}
Diagrams or text → 3D IFC4 BIM models of plant systems, plus ANSYS APDL scripts.
:::

::: card
#### requirements_agent

{.small}
PWR primary-loop and Rankine sizing, about 1,500 baseline requirements, topology graph for BIM.
:::

::: card
#### muninn

{.small}
A RAVEN (UQ/optimization) agent built on the MOOSEnger framework.
:::

::: card
#### open_pronghorn-agent

{.small}
k-ε RANS CFD with OpenPronghorn (MOOSE) and RAG over its docs.
:::

::: card
#### pythia-agent

{.small}
A neural surrogate predicting ATR-valve pressure and velocity fields from an STL.
:::

::: card
#### component_\* agents

{.small}
Inspection, QA, and testing guides: requirements JSON → LaTeX/PDF reports plus a traceability database.
:::

::: card
#### cubit-energy-agent, aegis, system-thermal-hydraulics …

{.small}
Cubit meshing, safety analysis, TH network solver, and more. Look around the org.
:::
::::

Note: These repos are in github.inl.gov/genesis and need INL network access and org membership. They are not part of the public prometheus_core repo.

---

## How the code is organized {eyebrow="One monorepo, three directories"}

<div class="dg">
<div class="row" style="justify-content:center">
<div class="box navy" style="width:560px"><b>sdk/</b> <span class="small">(formerly <code>prometheus_api</code>)</span><span>Python package <code>prometheus-api</code> (v0.15.0): PrometheusAgent, LLMClient, StorageClient, identity, artifacts</span></div>
</div>
<div class="arrow-v"><span>LOCAL_SDK=true: make up builds prometheus_api:local from sdk/</span></div>
<div class="row" style="gap:40px; justify-content:center">
<div class="box sky" style="width:520px"><b>platform/</b><span>frontend, backend (also the agent registry), client-agent, in-tree agents. Every agent image is <code>FROM</code> <code>prometheus_api:local</code>.</span></div>
<div class="box orange" style="width:520px"><b>agent-template/</b> <span class="small">(formerly <code>prometheus_agent_template</code>)</span><span><code>setup_agent.py</code> scaffolds a new agent and copies the platform's secrets into its <code>.env</code>, including the switch to <code>prometheus_api:local</code>.</span></div>
</div>
<div class="row" style="gap:40px; justify-content:center">
<div class="arrow-v" style="width:520px"><span>runtime only: register + A2A via the backend</span></div>
<div class="arrow-v" style="width:520px"><span>scaffolds</span></div>
</div>
<div class="row" style="justify-content:center">
<div class="box green" style="width:1080px"><b>Agent repos</b><span>gmsh_agent, bim_agent, requirements_agent, … and <b>your hackathon agent</b> (in your team repo on github.com)</span><span>Separate repos. Run them next to the platform (joining its Docker network), or put them in <code>platform/agents/&lt;name&gt;/</code>.</span></div>
</div>
</div>

::: callout
One clone of `idaholab/prometheus_core` (default branch `devel`) holds all three directories; no submodules, and no pip dependency between platform and agents. The **base Docker image** delivers the SDK; the backend's **registry** connects services at runtime. More on this at 1:00 pm.
:::

---

## The code moves fast: stale claims you may read {eyebrow="A warning about documentation"}

::: col
| You may read… | Reality on devel |
|---|---|
| Chainlit UI on :8500 | React SPA :5150 + FastAPI backend :8600 |
| `message/send`, `params.context.skillId` (old template README/TUTORIAL curl) | `SendMessage`, `metadata.skillId`, `contextId`, header `A2A-Version: 1.0` |
| implement `process_analysis()` | implement `_execute(params, context, event_queue)` |
| `request_user_approval(...)` | does not exist; use `requires_approval` or `send_input_required` |
| login `prometheus` / `prometheus` | a setup wizard creates the first admin |
| image from mooseharbor, or a pinned registry image | built locally from `sdk/` with `LOCAL_SDK=true` |
| `PROMETHEUS_DEBUG` | `DEBUG_AGENTS=true` |
| LiteLLM on `:9977` is the registry / LLM proxy; `LITELLM_MASTER_KEY` | the backend (`:8600/v1/agents`, `Bearer AGENT_SECRET`); agents call providers directly |
| `get_provided_inputs(context)`; "Admin › Signing Keys → generate" | answers arrive in `params`; the backend creates the signing key itself |
| an up-front planner (`planner.py`), upload auto-binding (`file-uploads.md`) | the tool-calling loop, `orchestrator/agent_loop.py` (PR #104) |
| pin `prometheus_api@2b3dbcf` (old template README/TUTORIAL) | an old-repo hash (v0.8.0); agents now build on `prometheus_api:local` |
| repos `prometheus_api`, `prometheus_agent_template`, `prometheus_platform` | `sdk/`, `agent-template/` and `platform/` in `idaholab/prometheus_core`; old hashes were rewritten |
:::

---

## When docs disagree, trust the code. These are current: {eyebrow="A warning about documentation"}

:::: col
- `sdk/docs/agent/GUIDE.md`: the full agent developer guide
- `sdk/docs/agent/AGENT_MIGRATIONS.md`: what changed in each version
- `sdk/docs/ENV_SETUP.md`: every environment variable
- `sdk/specs/*.md`: the requirements contract (REQ-/BEH- IDs)
- `…/dev-docs/agent-loop-orchestration.md`: how the orchestrator works
- `platform/docs/docs/workflow-templates.md` (says "planner tool": read "orchestrator tool")
- `…/dev-docs/multi-user-setup.md`, `encryption-and-keys.md`
- `…/docs/docs/local-deeplynx.md`
- `platform/agents/client-agent/README.md` (still lists the removed `matcher.py`)
- `agent-template/TUTORIAL.md`, with the caveats in this deck

::: callout warn
The published docs site (`gh-pages`) was last deployed in February 2026, and only pushes to `main` rebuild it. Read the docs in the repo on `devel`.
:::
::::

---

## Links and help {eyebrow="Where to find things"}

:::: grid 2 gap=28px
| What | Where |
|---|---|
| Platform repo | `https://github.com/idaholab/prometheus_core` (branch `devel`) |
| Other agent repos | `github.inl.gov/genesis` (INL network only) |
| Wiki (design and planning) | Confluence, space "Prometheus" |
| Issues and tasks | JIRA project `PPLT` |
| Proposal documents | Box folder (linked from the org profile) |
| Chat support | Teams, and the mentors in the room |

|||

::: card acc
### Next: GitHub & PR workflow (1:00 pm)

{.body}
Branching, the rebase workflow, opening a PR, and what reviewers expect. Keep your platform running during the break.
:::
::::
