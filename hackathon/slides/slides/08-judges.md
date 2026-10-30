---
title: Judges Handbook
footer: Day 2 · Judges' handbook
accent: judge
css: "  .award { background: #fff; border: 1px solid var(--rule); border-top: 6px solid var(--acc); border-radius: 12px; padding: 22px 24px; display: flex; flex-direction: column; gap: 9px; min-width: 0; min-height: 250px; }\n  .award .ic { font-size: 52px; line-height: 1; }\n  .award h4 { font-size: 26px; }\n  .award .for { font-family: var(--mono); font-size: 14px; letter-spacing: .06em; text-transform: uppercase; color: var(--acc-ink); font-weight: 600; }\n  .award p { font-size: 19px; line-height: 1.4; color: var(--ink-2); }\n  table.score td { height: 34px; }"
index:
  time: Judges
  heading: Judges' handbook
  color: var(--ink-3)
  blurb: 'Not for participants: gate verification, the hidden test, the rubric with 1/3/5 anchors, stretch checks, the score sheet, the schedule, and the winners table.'
---

# Judges' handbook {.title kicker="Agent developer hackathon · Day 2" pills="Judges | not shown to participants"}
For judges only: how to verify the gate, run the hidden test, score the rubric with its anchors, fill in the score sheet, and announce the awards.

---

## How judging works {eyebrow="Overview"}

:::: grid 4
::: card acc
<div class="kpi"><span class="v">1</span><span class="l">pass / fail</span></div>

### Gate

{.small}
Seven must-haves. Agents that pass all of them are ranked for the main prizes; everyone can win a category award.
:::

::: card acc
<div class="kpi"><span class="v">2</span><span class="l">40 points</span></div>

### Hidden test

{.small}
A new markdown file, a new CSV, and three prompts. Scored item by item while the judges watch.
:::

::: card acc
<div class="kpi"><span class="v">3</span><span class="l">60 points</span></div>

### Rubric

{.small}
Skill design, plot quality, robustness, engineering, demo. Each scored 1–5 by every judge.
:::

::: card acc
<div class="kpi"><span class="v">4</span><span class="l">+10 max</span></div>

### Stretch bonus

{.small}
+2 for each stretch goal shown working, capped at +10.
:::
::::

:::: grid 2
::: callout info
**Final score** = hidden test (40) + the average of the judges' rubric points (60) + stretch bonus (up to 10) − penalties. Ties are broken by the hidden-test score, then *Robustness*.
:::

::: callout
**Judges**: \[names\]. A mentor who wrote code for a team does not score that team. Judges' decisions on the awards are final; People's Choice is by participant vote.
:::
::::

Note: Fill in judge names. Weights can be adjusted; hidden test + rubric must still add to 100.

---

## Must-haves: pass/fail, and how judges check each {eyebrow="Stage 1 · the gate"}

{.sm widths="40px|500px|"}
| # | Must-have | How the judges verify it |
|---|---|---|
| 1 | Built from the agent template (`prometheus_core/agent-template`); a `PrometheusAgent` subclass | Read `agent.py` at the submitted SHA |
| 2 | At least **two skills**, extract and plot, with team-prefixed IDs | Read `agent_card.json`; fetch the live card through `client-agent` (command below) |
| 3 | Registers with the platform; appears under `/agents` | `curl -H "Authorization: Bearer $AGENT_SECRET" localhost:8600/v1/agents`, then `/agents` in the chat |
| 4 | Natural-language requests are **routed by the orchestrator** | The practice prompt on the practice file calls both skills; the status stream or client-agent log shows the calls |
| 5 | Extract emits a table artifact; plot emits an **image** that renders | `/artifacts` lists both; the PNG shows in the chat |
| 6 | Tests pass and lint is clean | Fresh clone of the SHA: `uv lock --check`, `uv sync`, the SDK (below), `uv run pytest && uv run ruff check .` (the template's tests include `test_build_app_loads_agent_card`) |
| 7 | Every merged PR reviewed (owner reviews teammates; a teammate reviews the owner) | `gh pr list --repo <owner>/<team>-agent --state merged --json number,author,reviews`: each merged PR has an approval from someone other than its author |

```bash {.xs}
# 2 · no host port: read the card from inside client-agent
docker compose -p prometheus_platform exec -T client-agent \
  python -c "import json,urllib.request as u; c=json.load(u.urlopen('http://<slug>-agent:8000/api/agent-card')); print(c['name'], [s['id'] for s in c['skills']])"
# 6 · install the SDK
uv pip install "git+https://github.com/idaholab/prometheus_core.git@devel#subdirectory=sdk"
```

::: callout warn
A team that misses the gate still takes the hidden test, gets written feedback, and can win category awards. It is not ranked for the Prometheus Prize or the runner-up.
:::

---

## A new file, three prompts, 40 points {eyebrow="Stage 2 · the hidden test"}

::: col
{.body}
Judges bring a **markdown file and a CSV file nobody has seen**, written with the same conventions as the practice file. In a fresh conversation they upload the files and type the prompts exactly as written on their sheet.

{widths="||70px"}
| Test | What is checked | Pts |
|---|---|---|
| **1 · Find the table** | the right table, chosen by caption · the right columns · an image that renders, axes labelled with units | 15 |
| **2 · Match columns** | the right table · symbols and abbreviations mapped to the user's words · an image that renders | 12 |
| **3 · Plot this file** | the plot skill handles the CSV directly · it asks which columns to plot (more points for offering the real names) · it plots after the answer | 13 |
:::

---

## Rules of the test {eyebrow="Stage 2 · the hidden test"}

:::: col
::: card acc
#### Rules of the test

- The team may not touch the keyboard or explain the prompt to the agent.
- Each prompt gets **one** attempt; follow-up questions are answered by the judge. "Offers the real names" counts only for the agent's dropdown, not a free-text question from the orchestrator.
- An upload that fails on the platform side (the chat says the file "was not stored as a platform artifact") is redone in a fresh conversation and doesn't use the attempt. Confirm with `docker compose -p prometheus_platform logs --no-log-prefix client-agent 2>&1 | grep 'Failed to upload'`.
- Score the plot itself, not the orchestrator's summary of it. A text-vs-text plot was summarized as "the count of each machine type".
- A timeout of 3 minutes per prompt.
- Plotting extra series alongside the right one, or asking a sensible clarifying question, is fine.
- Plotting the wrong columns or the wrong table scores zero for that item, even if the plot looks good.
:::

::: callout
The prompts and files are revealed to everybody after the last team's test.
:::
::::

---

## Five criteria, 60 points {eyebrow="Stage 3 · the rubric"}

{widths="330px|110px|"}
| Criterion | Weight | What the judges look for |
|---|---|---|
| **Skill design & agent card** | 15 | Clean separation into skills; descriptions and `usage_notes` that route reliably; schemas with described properties; artifacts passed between skills, not data in prompts {.hl} |
| **Plot quality** | 10 | Axis labels with units, a meaningful title (from the caption), a legend for multiple series, sensible chart type, readable at chat size |
| **Robustness** | 10 | Judges try off-nominal requests: a table that doesn't exist, a text-only column, a wrong file type. Clear messages or follow-up questions, no crashes {.hl} |
| **Engineering quality** | 15 | Tests for parsing, matching, and plotting (with the LLM mocked); clean commits and PRs; README; no secrets; minimal `pyproject.toml` |
| **Demo & communication** | 10 | A clear 5-minute story: the approach, the trade-offs (regex vs LLM, where matching happens), a look at the code, what didn't work |

{.small}
Each judge scores every criterion from 1 to 5. Points = score ÷ 5 × weight. Example: a 4 on Skill design gives 12 of 15 points.

---

## What a 1, a 3, and a 5 look like {eyebrow="Scoring anchors"}

{.xs widths="230px|||"}
| Criterion | 1 · barely there | 3 · solid | 5 · outstanding |
|---|---|---|---|
| **Skill design & card** | One monolithic skill, or template placeholder text | Two skills, routed for the team's own prompts | Skills compose cleanly through artifacts; routed for every judge phrasing and never picked by mistake |
| **Plot quality** | Unlabelled axes, default title, wrong chart type | Labels and units, a title, readable | Caption-derived title, units, legend, sensible scales and chart type; looks like a figure for a report |
| **Robustness** | A stack trace on the first unusual input | Errors return a clear message | Asks when ambiguous (two matching tables, two temperature columns); handles separators, missing values, text columns |
| **Engineering quality** | The template's two tests, one giant commit | Tests for the parser and the plot; reviewed PRs; README | Fixtures from several hand-written files, mocked LLM, edge-case tests; small reviewed PRs; clear config docs |
| **Demo** | Slides only, no live run | A live run with a short explanation | A clear story with trade-offs, honest about failures, handles a judge's question at the keyboard |

{.small}
2 and 4 sit between the anchors. Judges score independently, then compare notes; a difference of more than 2 points on a criterion is discussed before averaging.

---

## +2 per stretch goal shown working, up to +10 {eyebrow="Stage 4 · stretch bonus"}

{widths="40px|480px|"}
| # | Stretch goal | Counts when the judges see… |
|---|---|---|
| 1 | Live status updates (`"streaming": true`) | progress messages in the UI during the run ("Found 4 tables…", "Plotting T \[K\] vs t \[min\]…") |
| 2 | LLM matching with tool calling or structured output | a bounded tool loop or a forced tool call in the code, and its effect in the hidden test |
| 3 | Asks for missing columns, offering the real names | a dropdown with the file's column names in the follow-up form |
| 4 | A workflow YAML chaining extract → plot | the workflow started by a natural-language request (don't require the slash command: it needs a typed artifact id) |
| 5 | A third useful skill | e.g. `list_tables`, `describe_table`, or `convert_units`, routed from a natural-language request |
| 6 | A 5-minute demo: conversation, plot, code walkthrough | all three parts within the time limit |

::: callout
Bonus points reward breadth; the hidden test rewards robustness. Get the 40 first.
:::

---

## Score sheet (one per team) {eyebrow="For judges"}

::: cols 1.35fr 1fr gap=26px
{.sm .score widths="|70px|110px|"}
| Item | Max | Score | Notes |
|---|---|---|---|
| **Hidden test 1** · table / columns / image | 15 | \__ / \__ / \__ |   {.hl} |
| **Hidden test 2** · table / matching / image | 12 | \__ / \__ / \__ |   {.hl} |
| **Hidden test 3** · direct / asks / plots | 13 | \__ / \__ / \__ |   {.hl} |
| Skill design & card (1–5) | 15 |   |   |
| Plot quality (1–5) | 10 |   |   |
| Robustness (1–5) | 10 |   |   |
| Engineering quality (1–5) | 15 |   |   |
| Demo & communication (1–5) | 10 |   |   |
| **Total** | 100 |   |   {.hl} |

|||

{.sm .score}
| Team |   |
|---|---|
| Commit SHA |   |
| Gate 1–7 passed? | ☐1 ☐2 ☐3 ☐4 ☐5 ☐6 ☐7 |
| Stretch goals seen | ☐1 ☐2 ☐3 ☐4 ☐5 ☐6 |
| Bonus (+2 each, max 10) |   |
| Penalties |   |
| Hidden test time (s) |   |
| Award nominations |   |

{.small}
Rubric points = score ÷ 5 × weight. Final = hidden test + average rubric points + bonus − penalties.
:::

Note: The item-level breakdown of the hidden-test points is in the organizer notes that go with the demo files.

---

## Schedule for demos and awards {eyebrow="Day 2 end" content-style="gap:0"}

::: agenda
- \[time\] | Code freeze and submissions | repo link and commit SHA, card name and skill IDs, README
- \[time\] | Gate checks | Judges and mentors verify the must-haves on each demo machine with the practice file
- \[time\] | Per team: 5 min demo + hidden test (≈ 10 min) | The team demos with the practice file, then the judges run the hidden prompts and two off-nominal requests
- \[time\] | Reveal · People's Choice vote · deliberation | The hidden files and prompts are shown to everybody; about 20 minutes
- \[time\] | Awards | Category awards first, then People's Choice, runner-up, and Best in Show
- \[time\] | What happens next | How the best agent gets reviewed and brought into the platform
:::

---

## Awards {eyebrow="And the winners are…"}

::: grid 2 gap=30px
{.sm}
| Award | Team |
|---|---|
| 🏆 Prometheus Prize (Best in Show) |   {.hl} |
| 🥈 Second Stage Award |   |
| 🗳️ People's Choice |   |
| 🔍 Table Detective |   |
| 🧭 Column Whisperer |   |
| 📈 Show Me the Plot |   |
| 💬 Good Question |   |

|||

{.sm}
| Award | Team |
|---|---|
| 🎯 Orchestrator's Pet |   |
| 🛑 SCRAM Award |   |
| ⚡ Speed of Light |   |
| 🛡️ Defense in Depth |   |
| 💙 Cherenkov Glow |   |
| 🧪 Moonshot |   |
| 🐛 Half-Life Award |   |
| ✨ Special mention |   |
:::

Note: Fill in the winners during deliberation, or reveal them one at a time.
