---
title: The challenge
footer: One day · The challenge · https://idaholab.github.io/prometheus_core/hackathon/one-day
accent: agt
index:
  time: '10:40'
  heading: The challenge
  color: var(--orange)
  blurb: 'Build a table plotter in four checkpoints: route to a skill, read and publish artifacts, extract a table with an LLM, and plot it with a second skill. Goal, test prompt, done-when and hints for each, plus a stretch goal.'
---

# The challenge {.title kicker="Agent developer hackathon · One day · 10:40 am" pills="Brief, then reference | 4 checkpoints | about 100 minutes"}
One agent, two skills: pull a table out of a Markdown report, then plot it. Four checkpoints, each building on the last.
Note: Present the first two slides as the 20-minute brief and take questions. The checkpoint slides are the reference for the hands-on stretch after lunch. They give the goal, a test prompt, a done-when list and hints, and no solutions.

---

## Build a table plotter {eyebrow="The challenge"}
> Upload a report. Ask for a table. Get a plot back in the chat.

::: flow
- [sky] **Upload** | `performance-car-report.md`
- -> {w=60}
- [orange flex=1.2] **extract_table** | finds the table you asked for
- -> CSV artifact {w=130}
- [orange flex=1.2] **plot_table** | draws the columns you asked for
- -> {w=60}
- [green] **PNG** | in the chat
:::

:::: grid 2 gap=30px
::: card acc tag="Skill 1"
### extract_table

{.small}
Takes the uploaded Markdown document and a description of the table. Publishes that table as a **CSV artifact** and returns its id.
:::

::: card acc tag="Skill 2"
### plot_table

{.small}
Takes the CSV artifact and a description of each axis. Publishes a **PNG artifact** that renders in the chat.
:::
::::

{.small}
The orchestrator chains the two: it calls skill 1, reads the CSV id from the result, and passes it to skill 2.

---

## How to work {eyebrow="Ground rules"}

:::: grid 2 gap=30px
::: steps
#### Four checkpoints, in order

{.small}
Each builds on the one before. Test each before moving on.

#### One fresh chat per test

{.small}
Old uploads and results stay visible to the orchestrator and can confuse it. Upload the practice document again each time.

#### Rebuild after every change

{.small}
`make up` in your agent's folder, then wait about a minute for the orchestrator to see the new card.
:::

::: card tag="Practice document"
### performance-car-report.md

{.small}
In your clone: `prometheus_core/hackathon/slides/one-day/challenge/`. It has two captioned tables of simulated data: **category scores** (six rows) and **acceleration-test speeds** (ten rows over 0 to 9 seconds).
:::
::::

::: callout info
Stuck? Ask a mentor. Never paste a key into the chat.
:::

---

## Checkpoint 1: Route to a new skill {eyebrow="Checkpoint 1 of 4 · 15 min"}
> Add an `extract_table` skill, and show that the chat routes a request to it. An error message as the result is enough.

::::: cols 1fr 1fr gap=30px
:::: col
::: callout
**Test prompt**, after uploading the practice document:

"Extract the performance car speed table."
:::

### Done when
{.sm}
- The orchestrator calls your new skill.
- Your temporary result appears in the chat.
::::
|||
:::: col
### Hints
{.sm}
- The orchestrator picks a skill from its **card**: write a clear `description` and `usage_notes`, and say that a successful call returns the CSV artifact id.
- The skill needs no inputs yet: an empty `inputSchema` (`{}`) is fine.
- Dispatch on `params["skill_id"]` in `_execute`.
- The template's tests call `_execute` without a `skill_id`. They will fail until you update them.
::::
:::::

---

## Checkpoint 2: Retrieve and publish artifacts {eyebrow="Checkpoint 2 of 4 · 30 min"}
> Read the uploaded document, convert its tables with the helper, and publish the CSV to DeepLynx.

::::: cols 1.2fr 1fr gap=26px
```python {.xs}
import csv
import io
import re

TABLE_ROW = re.compile(r"^\|(.+)\|[ \t]*$", re.MULTILINE)
SEPARATOR_ROW = re.compile(r"[\s:|-]+")


def markdown_tables_as_csv(markdown: str) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    for row in TABLE_ROW.findall(markdown):
        if SEPARATOR_ROW.fullmatch(row):  # the |---| line
            continue
        writer.writerow(cell.strip() for cell in row.split("|"))
    return output.getvalue()
```
|||
:::: col
### Done when
{.sm}
- A CSV artifact appears in the chat and in DeepLynx.
- Your result returns the CSV artifact id.
- The CSV has 18 rows. **Both tables run together**, with the second header in the middle. That is expected: the helper is naive on purpose.

### Hints
{.sm}
- Add a string parameter for the uploaded document to the card and mark it with `"x_artifact_ref": "single"`. The orchestrator then fills it with the artifact id.
- `get_artifact_file_path` turns the artifact id into a local file.
- `send_deeplynx_artifact` publishes a file. Set `mime_type="text/csv"` and call it while the temporary folder still exists.
::::
:::::

---

## Checkpoint 3: Use an LLM to extract the table {eyebrow="Checkpoint 3 of 4 · 25 min"}
> Stop using the helper. Let an LLM find the table that matches the user's description and return just that table as CSV.

::::: cols 1fr 1fr gap=30px
:::: col
::: callout
**Test prompt:**

"Extract the table that compares the cars on acceleration, braking, comfort, and everyday usability."
:::

### Done when
{.sm}
- The helper is no longer used to pick or convert the table.
- The CSV has one header row and **six data rows**.
- It is published to DeepLynx and the result returns its id.
::::
|||
:::: col
### Hints
{.sm}
- Add a string parameter to the card for the table the user wants, in their own words.
- `self.llm_client(context)` and the `medium` flavor. Give the model the whole document and that description.
- Ask for **only CSV**: no code fence, no commentary. Keep the exact column names and row order.
- Give it a way to say no, such as a fixed word like `NO_MATCH`.
- **Check the answer in Python** before you upload: parse it with `csv` and reject an empty or ragged result.
::::
:::::

---

## Checkpoint 4: Add a plot skill {eyebrow="Checkpoint 4 of 4 · 30 min"}
> Add `plot_table`: take the CSV artifact, plot two columns with Matplotlib, and publish the image.

::::: cols 1fr 1fr gap=30px
:::: col
::: callout
**Test prompt**, in a fresh chat with the practice document:

"Extract the table containing the ten-second acceleration-test speeds, then plot Ferrari speed versus time as a line chart."
:::

### Done when
{.sm}
- The orchestrator calls the plot skill with the CSV artifact id.
- A PNG renders in the chat: x from 0 to 9, the Ferrari line from 0 to 162 mph.
::::
|||
:::: col
### Hints
{.sm}
- Three parameters: the CSV id (`x_artifact_ref`), and a short description of each axis, such as "time" and "Ferrari speed".
- The axes are **descriptions, not column names**. Read the CSV header, ask an LLM which header fits each description, and check in Python that its answer is a real header.
- `uv add matplotlib "python-dateutil<3"`, then `make up`. Select the `Agg` backend before importing `pyplot`.
- Publish with `mime_type="image/png"`.
::::
:::::

---

## Stretch goal: Let the LLM choose how to plot {eyebrow="Optional · tool calling"}
> Give the LLM one tool per chart type and let it decide which to call. You build this only if the checkpoints are done.

::::: cols 1fr 1fr gap=30px
:::: col
### The change
{.sm}
- Replace the two axis parameters with one free-text `plot_request`.
- Register `line_plot`, `bar_plot` and `scatter_plot` as tools. Each takes an x column, a list of y columns and a title.
- Your Python checks every call and draws the figure. The model never writes plotting code.

::: callout
**Try:** "compare all three cars against time on one chart", or "a bar chart of the category scores". Then ask for a **line** chart of the category scores and watch what happens.
:::
::::
|||
:::: col
### Done when
{.sm}
- The model chose the chart type by calling a tool, and your result says which.
- A bad column or the wrong chart type returns an error to the model, not a crash.
- The loop is bounded, and the PNG renders in the chat.

### Hints
{.sm}
- Stop when the model makes no tool call, and cap the turns.
- Replay the model's turn (`assistant_message`) before the tool results.
- List the valid columns in every error, so the model can fix its call.
::::
:::::

---

## What you built {eyebrow="Close out"}

::: takeaways
### The model interprets

It found the right table and chose the right columns.

### Python verifies

Every answer was checked before anything was published.

### Artifacts connect skills

A CSV id was all the plot skill needed from the extract skill.
:::

:::: grid 2 gap=30px
::: card acc tag="Keep going"
### Next steps

{.small}
Add a skill of your own. The agent developer guide is `sdk/docs/agent/GUIDE.md` in `prometheus_core`.
:::

::: card tag="Tell us"
### How was today?

{.small}
Tell a mentor, or open an issue in `idaholab/prometheus_core`.
:::
::::
