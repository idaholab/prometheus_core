---
title: Welcome & Prometheus
footer: One day · Welcome & Prometheus · https://idaholab.github.io/prometheus_core/hackathon/one-day
accent: welcome
index:
  time: '8:30'
  heading: Welcome &amp; Prometheus
  color: var(--navy)
  blurb: 'The agenda and what you will leave with, a short primer on LLMs and agents, and how Prometheus works from an agent author''s view: the platform at a glance, one chat turn, eight terms, what the platform does for you.'
---

# Welcome & Prometheus {.title kicker="Agent developer hackathon · One day · 8:30 am" pills="All participants | 60 min | Press N for notes · O for overview"}
What we will build today, what AI can and cannot do, and how Prometheus fits the pieces together.
Note: Welcome first (15 minutes): agenda, outcomes, links. Then the AI primer and the Prometheus overview (45 minutes). The live demo follows at 9:30.

---

## Today you will… {eyebrow="Welcome"}

<div class="grid g4" style="margin-top:10px">
<div class="card acc"><div class="kpi"><span class="v">1</span></div><h3>Run the platform</h3><p class="small">Prometheus and DeepLynx on your own laptop, with the debug agents to try.</p></div>
<div class="card acc"><div class="kpi"><span class="v">2</span></div><h3>Build an agent</h3><p class="small">Start from the template, add skills, and watch the chat route requests to them.</p></div>
<div class="card acc"><div class="kpi"><span class="v">3</span></div><h3>Pass files around</h3><p class="small">Read an uploaded file, publish a result, and let a second skill pick it up.</p></div>
<div class="card acc"><div class="kpi"><span class="v">4</span></div><h3>Use an LLM</h3><p class="small">Call one from your agent. Tool calling is in the live demo for everyone, and an optional stretch to build.</p></div>
</div>

::: callout info
No AI-development experience is needed. The homework was installs (git, Docker, uv, VS Code), an LLM API key, and cloning `prometheus_core`. Not quite there? Mentors will help, and the setup deck starts from the clone.
:::

---

## Follow along online {eyebrow="Links"}
> Everything you see today is online. Open it on your laptop and keep it there.

<div class="grid g2" style="margin-top:10px">
<div class="card acc"><h3>These slides</h3><p><a href="https://idaholab.github.io/prometheus_core/hackathon/one-day">idaholab.github.io/prometheus_core/hackathon/one-day</a></p><p class="small">Welcome, the live demo reference, setup, and the challenge.</p></div>
<div class="card acc"><h3>Platform documentation</h3><p><a href="https://idaholab.github.io/prometheus_core">idaholab.github.io/prometheus_core</a></p><p class="small">Architecture, deployment, the SDK, and the agent template.</p></div>
</div>

Note: Point out that the slide URL is also in the footer of every slide in this deck.

---

## The day {eyebrow="Agenda" content-style="gap:0"}

::: agenda
- 8:30 | Welcome and Prometheus | Agenda · what AI can and cannot do · how Prometheus works {.now}
- 9:30 | Live demo | An agent built from scratch, step by step. Follow along or just watch.
- 10:30 | Break
- 10:40 | The challenge | What you will build today, and questions
- 11:00 | Setting up (hands-on) | Start the platform and DeepLynx, try the debug agents, scaffold your agent. Lunch at noon while it runs.
- 1:00 | Challenge checkpoints (hands-on) | A new skill · files in and out · an LLM call · a second skill that plots. Mentors circulate.
- 1:45 | Break (10 min, then back to the checkpoints)
- 2:50 | Close out | What you built, and where to go next
:::

---

# What AI can and cannot do {.section num="AI"}
Four slides for anyone new to this. Everyone else gets a shared vocabulary for the day.

---

## An LLM predicts text {eyebrow="AI primer"}
> A large language model takes text in and gives text back. You supply the prompt.

:::: grid 2 gap=30px
::: card acc tag="Good at"
### Working with language

{.small}
Reading and summarizing, rewriting, pulling structure out of messy text, translating, explaining, and writing code.
:::

::: card tag="Not built for"
### Being a database or a calculator

{.small}
It does not look facts up. It does not run the arithmetic. It only knows what it learned plus what is in your prompt.
:::
::::

Note: Ask who has used Claude or a similar chat tool. About three quarters of the room is expected to have.

---

## Where it goes wrong {eyebrow="AI primer"}

::: takeaways
### It sounds sure when it is wrong

A wrong answer reads exactly like a right one.

### Exact work is shaky

Unit conversions, sums and lookups can be off, and differ from run to run.

### It cannot see what you did not give it

No file, no table, no state, unless it is in the prompt.
:::

Note: The live demo makes this concrete. Do not spend long on it here.

---

## An agent adds tools and a loop {eyebrow="AI primer"}
> The model asks for a tool, your code runs it, and the result goes back to the model.

::: flow
- [sky] **Prompt** | what the user asked
- ->
- [navy flex=1.2] **LLM** | decides what to do next
- -> tool call {w=110}
- [orange flex=1.2] **Your code** | runs the tool exactly
- -> result {w=90}
- [navy] **LLM** | reads it and answers
:::

{.small}
The loop repeats until the model stops asking for tools. Your code does the exact work; the model decides which tool to call and with what.

---

## Verify it {eyebrow="AI primer"}

:::: cols 1fr 1fr gap=30px
::: card acc tag="Use the LLM for"
### Interpreting

{.small}
Understanding a request, finding the right part of a document, choosing which tool to call.
:::

|||

::: card tag="Use Python for"
### Being exact

{.small}
Arithmetic, parsing, checking an answer, anything that must be right every time.
:::
::::

::: callout good
That is the pattern for today: let the model interpret, then **check what it returns before you use it**.
:::

---

# How Prometheus works {.section num="01"}
Just enough of the platform to build an agent today: what it does for you, and what happens when someone types into the chat.

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
<div class="box orange" style="flex:1.3"><b>Agents</b><span class="small">built-in, debug, and <b>yours</b></span></div>
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
All of it runs on your laptop in Docker. The backend is also the agent registry; each agent calls its LLM provider directly, picked by `LLM_CONFIG_PROFILE`.

---

## "Create an image of the word INL" {eyebrow="One chat turn"}

::: steps
#### You ask

{.small}
"Create an image of the word 'INL' with white background and blue text."

#### The orchestrator picks a skill

{.small}
Its LLM sees every registered skill as a tool. It calls the artifact debug agent's `create_svg_artifact` with the word and the two colors.

#### The agent works

{.small}
It writes the SVG, stores it in DeepLynx as an **artifact**, and returns the artifact's id.

#### The chat shows the result

{.small}
The image renders in the conversation, with the orchestrator's summary.

#### Chain the next step

{.small}
"Convert that to a PNG" calls `convert_svg_to_png` with the id from step 3. Skills hand each other files by artifact id.
:::

Note: This is the same prompt used in the first minutes of the live demo. The debug agents are switched on with DEBUG_AGENTS=true.

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
| **Flavor** | The kind of LLM you ask for in code: `small`, `medium`, `large`, `vision`… |
| **Tool call** | The model asking your code to run something and use the result |

---

## What the platform does for your agent {eyebrow="What you get for free"}

{widths="470px|"}
| Service | You use it via |
|---|---|
| Registration and discovery | nothing: it happens at startup |
| Routing the user's request to your skill | a good card |
| File storage, upload handling, viewers | artifacts, DeepLynx |
| LLM access, any of several providers | `self.llm_client(...)` + `LLM_CONFIG_PROFILE` |
| Forms for missing inputs and follow-up questions | `required` parameters, `send_input_required` |
| Live progress in the chat | `send_status_update`, with `"streaming": true` in the card |
| Approval before costly steps | `"requires_approval": true` |
| Background tasks for long jobs | `declare_long_running` |
| Per-conversation memory | `load_context_state` / `save_context_state` |

{.small}
Today you use the first four. The rest are in the agent developer guide.

---

## The code and the stack you will run {eyebrow="The code"}

:::: cols 1.15fr 1fr gap=28px
```text {.sm}
~/projects/
├── prometheus_core/      # idaholab/prometheus_core
│   ├── platform/         # the stack: make up here
│   ├── sdk/              # prometheus_api (in your image)
│   └── agent-template/   # setup_agent.py
└── my-agent/             # your agent, beside the clone
    ├── agent.py · agent_card.json
    └── tests/
```

|||

::: card tag="one clone"
### prometheus_core

{.small}
A monorepo: the platform, the SDK (`sdk/`), and the agent template (`agent-template/`). Run commands from inside the directory you work on.
:::

::: card acc tag="your code"
### Your agent

{.small}
`setup_agent.py` copies the template into a folder of your own. We put it beside the clone, so the clone stays free of untracked files.
:::
::::

::: callout warn
The code moves fast and some docs lag behind. When a doc disagrees with these slides or the code, trust the code and ask a mentor.
:::

---

## Help {eyebrow="Where to find things"}

:::: grid 2 gap=30px
| What | Where |
|---|---|
| The mentors | in the room, all day |
| Agent developer guide | `sdk/docs/agent/GUIDE.md` in `prometheus_core` |
| These slides | the **All decks** link in the footer of every slide |
| Platform repo | [github.com/idaholab/prometheus_core](https://github.com/idaholab/prometheus_core) |
| Platform docs | [idaholab.github.io/prometheus_core](https://idaholab.github.io/prometheus_core) |

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
Next: the live demo at 9:30.
:::
