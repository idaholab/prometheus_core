# Hackathon challenge: the Table & Plot agent

Every team builds the same thing: **one Prometheus agent with at least two skills.**

| Skill | Does |
|-------|------|
| **Extract a table** | Given a markdown document (uploaded in the chat) and a description of the table the user wants ("the table with population data"), find that table, parse it, and emit it as a **table artifact**. |
| **Plot tabular data** | Given tabular data (a table artifact from the first skill, *or* an uploaded CSV file) and the columns to plot, emit a **plot artifact** (a PNG image that renders in the chat). |

You have about 4–5 hours. Then it's demo time.

## What you get now

- `practice/lunar_cheese_annual_report.md`: a markdown report with several captioned tables.
- `practice/cheese_mouse_sightings.csv`: a plain CSV file.
- An example prompt, used after uploading the markdown file:

  > Extract the table with the population data and plot the population of Brie Basin versus year.

## What happens at demo time

You get a **new markdown file you have not seen**, a new CSV file, and two or three prompts. They test:

1. **Finding the right table by its caption.** Users refer to tables by what the caption says, not by number, and not always in the same words.
2. **Matching column names intelligently.** Users say "temperature" and "time"; the file may say something terser, with symbols and units.
3. **Skill separation and follow-up questions.** A user may upload a file and just say "plot this". Your agent should ask which columns to plot, offering the real column names, instead of guessing or failing.

The new files follow the same conventions as the practice file: GitHub-flavoured markdown tables, a bold caption directly **above** each table, units in the column headers, and prose between the tables. Expect the unexpected in the details: thousands separators, missing values, non-numeric columns, symbols.

## Requirements (the gate)

1. Built from the agent template (`prometheus_core/agent-template`); a `PrometheusAgent` subclass.
2. At least **two skills** in `agent_card.json`, with unique, team-prefixed skill IDs and card name.
3. Registers with your local platform; visible under `/agents`.
4. Natural-language requests in the chat are **routed by the orchestrator** to the right skill.
5. The extract skill emits a table artifact; the plot skill emits an **image** artifact that renders in the chat.
6. `uv.lock` is committed and current; `uv run pytest` and `uv run ruff check .` pass.
7. The code is in a team repo on github.com owned by one teammate; teammates fork it and open PRs, and every merged PR is reviewed (the owner reviews teammates' PRs, a teammate reviews the owner's).

## Platform prerequisites

- **DeepLynx must be configured**: `LOCAL_DEEPLYNX=true` in `platform/.env` runs it with the platform and writes the `DEEPLYNX_*` lines (deck 03); `setup_agent.py` copies them into your agent's `.env`. Every agent writes an execution record to DeepLynx and won't start without `DEEPLYNX_*`; chat uploads are stored there, and a PNG artifact needs it to render (`send_deeplynx_artifact`).
- Add `matplotlib` (and anything else you import) with `uv add matplotlib` and commit `uv.lock` (the image build fails without it); use the `Agg` backend.
- LLM calls: use the platform's `LLM_CONFIG_PROFILE` (`anthropic`, `openai`, `genesis`, `ollama`, `amsc`, `anl_asksage`, `inl_hpc` or `inl_litellm`) and its key `LLM_API_KEY` in your agent's `.env` (`setup_agent.py` copies both), then use `self.llm_client(context)` with the flavor that fits each call (`small` for cheap classification, `medium`/`large` for matching, `vision` to check a plot).

See the Day 1 decks (`index.html`) for everything else.
