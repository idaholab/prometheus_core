---
title: The Challenge & Teams
footer: Day 1 · The challenge & team formation
accent: team
index:
  time: '4:30'
  heading: The challenge &amp; team formation
  color: var(--crimson)
  blurb: The Table &amp; Plot agent, the practice files, the hidden test, a suggested design, five setup checks, roles and timeline, sign-up, your first hour. Card JSON and implementation hints in the appendix.
---

# The challenge &<br>team formation {.title kicker="Day 1 · 4:30 pm" pills="All participants | teams of 4–5 | 4–5 h of building"}
Every team builds the same agent: one that pulls a table out of a markdown document and plots it. At demo time it meets a file it has never seen.

---

## From announcement to teams in 30 minutes {eyebrow="How this works"}

::: agenda
- 10 min | The challenge | One task for everybody: the next slides
- 5 min | Questions | About the task, the files, or the judging
- 10 min | Form teams of 4–5 | Mix skills: Docker, parsing, prompts, tests
- 5 min | Register | Team name, members, Day 2 room
:::

::: callout
Building time on Day 2 is about **4–5 hours**. Get something working end to end in the first two hours, then make it robust.
:::

---

## One agent, at least two skills {eyebrow="The challenge"}

:::: grid 2 gap=30px
::: card acc tag="Skill 1"
### Extract a table

{.body}
From an uploaded markdown document, find the table the user describes ("the table with population data") **by its caption**, parse it, and publish it as a **table artifact**.
:::

::: card acc tag="Skill 2"
### Plot it

{.body}
From a table artifact or an uploaded CSV, draw the plot the user asked for as a **PNG artifact**. Don't know which columns? **Ask**, offering the real column names.
:::
::::

::: callout
"Extract the table with the population data and plot the population of Brie Basin versus year": the orchestrator calls skill 1, reads its result, then calls skill 2 with the new table's id. You design the skills; the orchestrator chains them.
:::

---

## The practice files {eyebrow="What you get now"}

:::: cols 1.4fr 1fr gap=26px
{.tiny}
`challenge/practice/lunar_cheese_annual_report.md` (excerpt, as rendered)

{.small}
**Table 2. Census of the resident population of the three lunar mining settlements, 2042–2051, together with the estimated number of feral cheese mice living in the maintenance tunnels.**

{.sm}
| Year | Crater Gouda (residents) | Brie Basin (residents) | Camembert Ridge (residents) | Feral cheese mice (est.) |
|---|---|---|---|---|
| 2042 | 412 | 188 | — | 350 |
| 2043 | 467 | 203 | — | 420 |
| 2044 | 521 | 231 | 37 | 515 |
| … | … | … | … | … |
| 2051 | 930 | 465 | 668 | 2,610 |

{.tiny}
*Camembert Ridge was not yet founded in 2042 and 2043 (—).* In the file, captions are bold paragraphs directly above GitHub-flavoured markdown tables.

|||

{.sm}
| File | Contents |
|---|---|
| `lunar_cheese_annual_report.md` | 3 captioned tables (equipment, population census, Emmental maturation log) with prose between them |
| `cheese_mouse_sightings.csv` | 6 numeric columns, 14 nights |
| `README.md` | the challenge brief and the requirements |

#### Example prompt (after uploading the report) {.acc}

::: callout good
*"Extract the table with the population data and plot the population of Brie Basin versus year."*
:::

{.small}
Note the traps already in the practice file: a non-numeric table, thousands separators (`1,020`), missing values (`—`), units in headers.
::::

---

## A file your agent has never seen {eyebrow="Demo time"}
> At the demo, judges upload a **new markdown file** and a **new CSV file** and type two or three prompts. The files follow the same conventions as the practice file.

:::: grid 3 gap=22px
::: card acc tag="Test 1"
### Finding the table

{.small}
Users refer to a table by what its **caption** says, not by number, and not in the same words. There may be several tables with similar columns.
:::

::: card acc tag="Test 2"
### Matching columns

{.small}
Users say "temperature" and "time". The file may use symbols and units instead of words. Case can matter.
:::

::: card acc tag="Test 3"
### Plot this file

{.small}
A user uploads a CSV and just says "plot this". The plot skill must work **without** the extract skill, and **ask** which columns to use instead of guessing.
:::
::::

::: callout warn
Tune for the conventions, not for the practice file. Hard-coding "Brie Basin" or "Table 2" will pass the practice prompt and fail every hidden one.
:::

---

## Two skills, connected by an artifact {eyebrow="A suggested design"}

::: flow
- [gray flex=0.8] **upload .md**
- ->  {w=40}
- [orange flex=1.2] **`<team>_extract_table`** | find by caption · parse · clean numbers
- -> table id {w=100}
- [orange flex=1.2] **`<team>_plot_table`** | match columns · ask if unsure · matplotlib
- ->  {w=40}
- [green flex=0.8] **PNG** | renders in chat
:::

:::: grid 3
::: card
#### Return what plotting needs

{.small}
Skill 1 returns the table's `artifact_id`, the matched caption, and the exact column names.
:::

::: card
#### Plot accepts a CSV too

{.small}
"Plot this" on an uploaded CSV must work without skill 1.
:::

::: card
#### Columns optional

{.small}
Don't make the columns required: then your skill can ask with a dropdown of real names.
:::
::::

{.small}
Full card JSON for both skills and the implementation hints: this deck's appendix and `challenge/README.md`.

---

## Five things that save you an hour {eyebrow="Before you start"}

{widths="470px|"}
| Make sure… | Because |
|---|---|
| **DeepLynx works**: `LOCAL_DEEPLYNX=true` in `platform/.env` (the first `make up` asks; deck 03) | agents won't start without it, never see the upload, and the PNG can't render |
| **Team prefix** on the card name and skill IDs | every team builds the same skills; same names overwrite each other |
| `uv add matplotlib pandas`, commit `uv.lock`; `MPLBACKEND=Agg` | the base image has none of them, the build needs the lock, and there is no display |
| `"streaming": true` in the card | so "Parsing 4 tables…" shows up live |
| A **fresh conversation** per test | old uploads and results can mislead the orchestrator |

---

## Roles and a timeline for 4–5 hours {eyebrow="Planning the day"}

::: grid 2 gap=30px
{.sm}
| Role | Owns |
|---|---|
| **Card & routing** | `agent_card.json`, the result JSON the orchestrator reads, testing many phrasings |
| **Parser** | finding tables and captions, cleaning values |
| **Matching (LLM)** | caption and column matching, prompts, input-required |
| **Plotting & artifacts** | matplotlib, DeepLynx upload, CSV/JSON handling |
| **Tests & integration** | pytest fixtures, Docker build, PRs, the demo script |

|||

<div class="col" style="gap:0">
<div class="agenda-row"><span class="tm">0:00</span><div><div class="ti">Scaffold, card with 2 stub skills</div><div class="de">Registered and routed in the chat</div></div></div>
<div class="agenda-row"><span class="tm">1:00</span><div><div class="ti">Walking skeleton</div><div class="de">Practice prompt works end to end, even if crudely</div></div></div>
<div class="agenda-row"><span class="tm">2:30</span><div><div class="ti">Robustness</div><div class="de">Write your own test files and prompts; CSV path; asking for columns</div></div></div>
<div class="agenda-row"><span class="tm">4:00</span><div><div class="ti">Freeze features</div><div class="de">Tests, README, PR review, rehearse the demo</div></div></div>
</div>
:::

---

## Teams and rooms {eyebrow="Sign-up"}

{widths="280px||200px|150px"}
| Team name | Members (4–5) | Prefix | Day 2 room |
|---|---|---|---|
| &nbsp; |   |   |   |
| &nbsp; |   |   |   |
| &nbsp; |   |   |   |
| &nbsp; |   |   |   |
| &nbsp; |   |   |   |
| &nbsp; |   |   |   |
| &nbsp; |   |   |   |
| &nbsp; |   |   |   |

{.small}
The team prefix goes everywhere: the card name "&lt;Team&gt; Table Plot" (the scaffolder appends " Agent"), skill IDs `<team>_extract_table` / `<team>_plot_table`, workflow IDs `<team>.…`, branches `feature/<team>-…`.

Note: Placeholder table: fill in live or replace with the room list.

---

## Your first hour {eyebrow="Hacking starts now"}

:::: grid 2 gap=30px
::: steps
#### Pick an owner, create the repo

{.small}
One teammate runs `setup_agent.py "<Team> Table Plot" ../../<team>-agent` (no `~`), adds the second skill to the card and a dispatch on `params["skill_id"]`, then `git init`, `gh repo create <team>-agent --source=. --push`. Practice files go in `tests/fixtures/`.

#### Everyone else forks

{.small}
`gh repo fork <owner>/<team>-agent --clone`. Your agent `.env` comes from **your** platform: `python3 setup_agent.py --env-only ../../<team>-agent` in `agent-template/`.

#### Check routing first

{.small}
Upload the practice report, try the example prompt, and see both stubs called in order. The extract stub must already emit a real artifact, or the orchestrator has no id to pass to plot.

#### Split by role

{.small}
Everyone works on a `feature/…` branch in their fork, runs `git pull --rebase upstream main` often, and opens small PRs to the owner's repo. The owner reviews and merges; a teammate reviews the owner's PRs.
:::

|||

::: card acc
### Keep these open

{.sm}
- `cheatsheet.html`: the one-page summary of commands and helpers
- `challenge/README.md`: the brief and requirements
- This deck's appendix (key `A`): both skills' card JSON, implementation hints, asking for columns, stretch ideas
- The "Building an agent" deck (`04`): helpers, artifacts, input-required, LLMClient
- `prometheus_api/docs/agent/GUIDE.md`
- The platform's `agents/debug-agents/artifact-debug-agent`: a working image artifact via DeepLynx
:::

::: callout
Write **your own** markdown test files with different captions, symbols, and units. The hidden file will not look exactly like the practice one.
:::
::::

---

# Appendix: reference {.section .appendix num="A"}
Reference material behind the talk. Skipped in the session; use it when you need the details.

---

## From announcement to teams in 30 minutes {eyebrow="How this works"}

:::: grid 2 gap=30px
::: steps
#### The challenge (10 min)

{.small}
One task for everybody, described on the next slides. Same practice file, same rules, same hidden test at the end.

#### Questions (5 min)

{.small}
Ask now about the task, the files, or the judging. The judging deck is public; the demo files are not.

#### Form teams (10 min)

{.small}
4–5 people. Mix skills: someone comfortable with Docker, someone who likes parsing, someone who likes prompts, someone who writes tests.

#### Register (5 min)

{.small}
Team name and members go on the sign-up sheet. Pick up your Day 2 room and the practice files.
:::

|||

::: card acc
### Why one shared task?

{.sm}
- Everyone exercises the same platform features: uploads, artifacts, routing, follow-up questions
- Results are directly comparable on demo day
- The interesting part is **generalization**: does your agent handle a file it has never seen?
- Teams can compare approaches afterwards: regex vs LLM, one skill vs several
:::

::: callout warn
Building time on Day 2 is about **4–5 hours**. Get something working end to end in the first two hours, then make it robust.
:::
::::

---

## One agent, at least two skills {eyebrow="The challenge"}

:::: grid 2 gap=30px
::: card acc tag="Skill 1"
### Extract a table from a markdown document

{.body}
The user uploads a markdown file and describes the table they want, the way people do: *"the table with population data"*, *"the maturation log of the big Emmental"*.

{.body}
The skill finds the right table by its **caption**, parses it into columns and rows, and emits it as a **table artifact** that other skills (and the UI) can use.
:::

::: card acc tag="Skill 2"
### Plot tabular data

{.body}
Given tabular data (a table artifact from skill 1, **or** an uploaded CSV file) and the columns to plot, the skill draws the plot and emits it as an **image artifact** that renders in the chat.

{.body}
If it doesn't know what to plot, it **asks the user**, offering the real column names.
:::
::::

::: callout
The orchestrator chains them for a request like *"Extract the table with the population data and plot the population of Brie Basin versus year"*: skill 1 runs first; the orchestrator LLM reads its result and passes the new table's artifact id to skill 2. You design the skills; the orchestrator decides when to call each, and with what.
:::

---

## Two skills, connected by artifacts {eyebrow="A suggested design"}

<div class="dg">
<div class="row" style="gap:0; align-items:stretch">
<div class="box gray" style="flex:0.8"><b>upload .md</b><span class="small">stored in DeepLynx, registered as an artifact</span></div>
<div class="arrow-h" style="width:50px"></div>
<div class="box crimson" style="flex:1.2"><b>skill 1 · <code>&lt;team&gt;_extract_table</code></b><span class="small">inputs: <code>document_artifact_id</code> (<code>x_artifact_ref</code>), <code>table_description</code></span><span class="small">parse all tables → pick by caption → clean numbers</span></div>
<div class="arrow-h" style="width:50px"></div>
<div class="box teal" style="flex:1"><b>table artifact</b><span class="small">JSON <code>{caption, columns, rows}</code> (+ a CSV file)</span></div>
</div>
<div class="arrow-v at-right" style="height:34px"><span>artifact id</span></div>
<div class="row" style="gap:0; align-items:stretch">
<div class="box green" style="flex:1"><b>image artifact</b><span class="small">PNG via <code>send_deeplynx_artifact</code>, <code>image/png</code></span></div>
<div class="arrow-h left" style="width:50px"></div>
<div class="box crimson" style="flex:1.2"><b>skill 2 · <code>&lt;team&gt;_plot_table</code></b><span class="small">inputs: <code>table_artifact_id</code> (<code>x_artifact_ref</code>), <code>x_column</code>, <code>y_columns</code>, <code>title</code></span><span class="small">match columns → ask if unsure → matplotlib</span></div>
<div class="arrow-h left" style="width:50px"></div>
<div class="box gray" style="flex:0.8"><b>upload .csv</b><span class="small">or any table artifact</span></div>
</div>
</div>

:::: grid 3
::: card
#### Skill 1 returns

{.small}
`artifact_id`, the matched caption, and the **exact column names** in its result dict. The orchestrator reads that JSON (not the artifact body) to fill the plot call. Never put an `artifacts` key in your result.
:::

::: card
#### Skill 2 accepts both

{.small}
A JSON table artifact **and** a raw CSV file. `get_artifact_file_path()` gives you a local file either way.
:::

::: card
#### Keep columns optional

{.small}
If `x_column` and `y_columns` are not required in the schema, *your* skill can ask with the real column names as choices. Say so in the description, so the orchestrator doesn't guess.
:::
::::

---

## Skill 1 in `agent_card.json`: extract {eyebrow="The card"}

```json {.sm}
{ "id": "neutron_extract_table",
  "name": "Extract table from markdown",
  "description": "Find one table in an uploaded markdown
    document by matching the user's description against the
    table captions, parse it, and publish it as a table
    artifact with clean numeric columns.",
  "usage_notes": "Use when the user refers to a table inside
    a markdown/text document. Not for CSV files: those can be
    plotted directly.",
  "tags": ["table", "markdown", "extract"],
  "inputSchema": { "type": "object",
    "properties": {
      "document_artifact_id": { "type": "string",
        "x_artifact_ref": "single",
        "description": "The markdown document artifact." },
      "table_description": { "type": "string",
        "description": "How the user referred to the table,
          e.g. 'the table with population data'." } },
    "required": ["document_artifact_id", "table_description"] } }
```

---

## Skill 2 in `agent_card.json`: plot {eyebrow="The card"}

```json {.sm}
{ "id": "neutron_plot_table",
  "name": "Plot tabular data",
  "description": "Plot columns of a table artifact or an
    uploaded CSV file as a PNG line, scatter, or bar chart.
    If the user named no columns, call it with only
    table_artifact_id: the skill asks, offering the
    real column names. Do not guess columns.",
  "usage_notes": "Use for 'plot', 'chart', 'graph' requests on
    tabular data, including a CSV the user just uploaded.
    Column names may be approximate ('temperature').",
  "tags": ["plot", "chart", "csv", "table"],
  "inputSchema": { "type": "object",
    "properties": {
      "table_artifact_id": { "type": "string",
        "x_artifact_ref": "single",
        "description": "Table artifact or CSV file." },
      "x_column": { "type": "string",
        "description": "Column for the x axis (approximate ok)." },
      "y_columns": { "type": "array", "items": {"type": "string"},
        "description": "Column(s) for the y axis (approximate ok)." },
      "kind": { "type": "string", "enum": ["line", "scatter", "bar"] } },
    "required": ["table_artifact_id"] } }
```

{.small}
These go in the card's `skills` array, with `"capabilities": {"streaming": true}` at the top level. Prefix the IDs with your team name: every team builds the same skills.

---

## The pieces you need {eyebrow="Implementation hints"}

::: col
{.wrap-code}
| Step | Options |
|---|---|
| **Get the file** | `path = await self.get_artifact_file_path(params["document_artifact_id"], context=context, artifacts=params.get("artifacts"))` |
| **Find tables** | Regex over `\|`-rows plus the separator line, or a markdown parser (`markdown-it-py`). Keep the bold line above as the caption. |
| **Pick the table** | An LLM given only the captions (a forced tool call returning an index), embeddings, or fuzzy matching. Match on meaning: the orchestrator paraphrases the user's words in `table_description`. |
| **Clean values** | `1,020` → 1020; `—`, `-`, empty → missing; keep text columns as text |
| **Match columns** | The LLM with the header list and the user's words; parse units in `[…]` or `(…)`; mind `t` vs `T` |
| **Plot** | `matplotlib` with the `Agg` backend; label axes with units; title from the caption |
| **Publish** | `send_json_artifact(..., catalog_artifact=True)` for the table; `send_deeplynx_artifact(..., mime_type="image/png")` for the plot |
:::

---

## Asking for the columns {eyebrow="Implementation hints"}

::: col
```python {.sm}
from prometheus_api.agent import MissingInput

# df: the table loaded from params["table_artifact_id"]
columns = list(df.columns)
x_col, y_col = params.get("x_column"), params.get("y_column")
if not x_col or not y_col:
    await self.send_input_required(
        context, event_queue,
        missing_inputs=[
          MissingInput(name="x_column",
            description="Column for the x axis",
            user_prompt="Which column goes on the x axis?",
            type="enum", options=columns),
          MissingInput(name="y_column",
            description="Column for the y axis",
            user_prompt="Which column should be plotted?",
            type="enum", options=columns)],
        hint="Choose the columns to plot.")
    return {}
# resumed call: the same params plus the answers,
#   params["x_column"], params["y_column"]
```

{.small}
When the user answers, `_execute` runs again with the original arguments and the answers merged into `params`. A string list in `options` becomes a dropdown in the chat's follow-up form, with your `hint` as the message. With `resolvable_from_context=False` (the default) the user is asked. If they type a reply instead, the orchestrator calls you again with new arguments.
:::

---

## Fail loudly, not plausibly {eyebrow="Implementation hints"}
> Each row is a failure seen in testing. A wrong but confident answer scores zero; an honest error can still score.

{widths="300px|"}
| Case | What to do |
|---|---|
| **No caption fits** | Return an error that lists the captions you found. A forced LLM pick always returns *some* table: "the rainfall data" picked the Emmental log. |
| **The y column is text** | Reject it or ask again. Testing produced a "Machine type vs Machine type" plot. |
| **Not a text file** | Check the extension or `mime_type` before `read_text()`. A PDF raised `UnicodeDecodeError`, visible to judges in the logs. |
| **Paraphrased request** | `table_description` is the orchestrator's wording, not the user's ("population" arrived as "the main data table in the Lunar Cheese annual report"). Match on meaning. |

---

## Prerequisites {eyebrow="Before you start"}

{widths="420px|"}
| Make sure… | Why |
|---|---|
| **DeepLynx is configured**: `LOCAL_DEEPLYNX=true` in `platform/.env` (deck 03), and the `DEEPLYNX_*` lines in your agent's `.env` (`setup_agent.py` copies them) | Every agent writes an execution record to DeepLynx, so it **won't start** without `DEEPLYNX_*`. Chat uploads are stored there too, and a PNG cannot render without it. {.hl} |
| `matplotlib`, `pandas`… added with `uv add`, `uv.lock` committed | The base image has none of them, and the build stops without a current `uv.lock`. Set `MPLBACKEND=Agg` (no display in the container). |
| Extra modules have `COPY` lines in the Dockerfile | The template copies only `agent.py`, the card, `prompts/`, and `workflows/`. |
| Card name and skill IDs carry your **team prefix** | Every team builds an "extract table" skill. Same name → the registry replaces one agent with the other. |

---

## Pitfalls {eyebrow="Before you start"}

{widths="420px|"}
| Make sure… | Why |
|---|---|
| `"streaming": true` | So "Parsing 4 tables…" and "Plotting T \[K\] vs t \[min\]…" appear live |
| Your LLM profile and its key are in `.env`; pick the flavor per call | The platform's `LLM_CONFIG_PROFILE` (e.g. `anthropic`, `genesis`, `inl_litellm`) plus its key in `LLM_API_KEY`; `setup_agent.py` copies both from `platform/.env`. Then just `self.llm_client(context)`. |
| Results stay small | Return the artifact ID, caption, and column names, not 10,000 rows. The data lives in the artifact. |
| You test with a **fresh conversation** each time | Earlier uploads and results stay in the catalog and transcript the orchestrator LLM sees, and can make it pick the wrong file. |

Note: Every profile reads LLM_API_KEY, which the template compose forwards.

---

## Once the basics work {eyebrow="Going further"}

:::: grid 3 gap=20px
::: card
#### Better plots

{.xs}
- Multiple y series, secondary axis for different units
- Bar charts for text x columns
- Log scales on request
- Captions and units in the title and labels
- A vision-model check of your own plot
:::

::: card
#### More skills

{.xs}
- `list_tables`: show all captions in a document
- `describe_table`: statistics, min/max, trends
- `convert_units`: K ↔ °C before plotting
- `compare_tables` across two files
:::

::: card
#### Platform features

{.xs}
- An `extract → plot` workflow with no follow-up questions, started by a natural-language request
- Input-required when two tables match equally well
- Tool calling for column matching
- The CSV of the extracted table as a second artifact
- Thorough tests with fixtures from the practice file
:::
::::

::: callout
Robustness beats features. A two-skill agent that handles every hidden prompt scores higher than a six-skill agent that crashes on a thousands separator.
:::

---

## What the judges will check {eyebrow="Acceptance criteria"}
> The full rubric and the awards are in the Judging & awards deck.

:::: grid 2 gap=30px
::: card acc
### Must have (the gate)

{.sm}
1. Built from the template; a `PrometheusAgent` subclass
2. At least **two skills** (extract, plot) with team-prefixed IDs
3. Registers; visible in `/agents`
4. Natural-language requests are **routed** to the right skill
5. Extract emits a table artifact; plot emits an **image** that renders
6. `uv run pytest` and `uv run ruff check .` pass
7. Every merged PR reviewed: by the owner, or by a teammate for the owner's own
:::

::: card
### Stretch

{.sm}
1. Live status updates (streaming)
2. LLM matching with tool calling or structured output
3. Asks for missing columns with the real names as choices
4. A workflow YAML chaining extract → plot (no follow-up questions)
5. A third useful skill
6. A 5-minute demo: conversation, plot, code walkthrough
:::
::::
