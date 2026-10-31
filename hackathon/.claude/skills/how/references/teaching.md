# Teaching: the pattern and the check questions

Facts as of `prometheus_core` `devel` 2026-10-31, after #310 and #322 (`prometheus_api` 0.15, no LiteLLM). When the code disagrees with this file, the code is correct.

## The teaching pattern

1. **Primer.** Before each decision, explain the concept and why it matters in 2-3 lines, with the deck and slide.
2. **Check question.** At each key concept, ask one bank question. A wrong answer never blocks the work.
3. **Diagram.** After a key concept, offer a `/how explain` page.
4. **"Skip the quiz".** Then ask no more check questions this session. Keep the primers.
5. **Decisions in rounds.** Find every fact yourself (a path, a port, a login, a set key); ask only decisions.
   Each round asks every decision whose prerequisites are settled (`conventions.md`, "Ask the user"). Never
   decide for the user. At the end, summarize the decisions, and act after the user confirms.

## How to ask a check question

Ask one `AskUserQuestion` with the bank's header, stem, and options, in bank order, none recommended.
Ask each id at most once per session. Then say "Correct." or "Not quite. The answer is: <label>.", give
the feedback in 2-4 sentences with the source, and continue the work.

## The question bank

Each entry: the header, the stem, options A-D, the correct answer, the feedback, and the source.
### card-interface

`Card`. How does the orchestrator decide to call your skill? A "A test call" to each agent. B "It reads your card":
each skill becomes a tool from its description, `usage_notes`, and `inputSchema`. C "It reads agent.py". D
"Keyword match" on the tags. **B.** No test call, no code reading: the LLM picks from the card text alone, and
tags are hidden. When you are not called, fix the card. Deck 04, slides 5-7; `prometheus_platform/agents/client-agent/orchestrator/agent_loop.py:224-255`.

### route-fields

`Routing`. Which of these card fields does the orchestrator LLM read? A "Skill tags". B "Agent description". C
"Skill examples". D "usage_notes". **D.** The tool description is the skill `description`, `Usage: <usage_notes>`,
and an approval line; the parameters are the `inputSchema` without `x_*` keys. Tags, examples, `output_format`,
and the agent description never reach the LLM. Deck 04, slide 6 and A10-A12; `agent_loop.py:180-221`.

### artifacts

`Artifacts`. Your skill makes a table that the next skill needs. What does your result return? A "The artifact id"
plus names (caption, columns). B "All the rows". C "A path in /tmp". D "Nothing". **A.** Publish with
`send_json_artifact(..., catalog_artifact=True)` or `send_deeplynx_artifact` and return the id. The orchestrator
reads at most 6,000 characters of a result; the next skill gets a file with `get_artifact_file_path`. Deck 04,
slides 9-10; `prometheus_api/prometheus_api/agent/base.py:1196`, `:1642-1665`; `agent_loop.py:70`.

### input-required

`Input form`. Your skill calls `send_input_required` and returns `{}`. The user fills in the form. What next? A "The
call continues". B "Local variables stay". C "_execute runs again": the answers are merged into `params`.
D "The LLM answers". **C.** The task ends in `TASK_STATE_INPUT_REQUIRED`; the orchestrator calls again with the
same `contextId` and the original arguments plus the answers in `params`; local variables are gone. Deck 04,
"Ask which columns" and appendix; `base.py:1047`, `:1096`.

### registry-wipe

`Registry`. You ran `make restart` in the platform. `/agents` no longer lists your agent. What now? A "make
down-v". B "Restart your agent": `docker compose -p <project> restart <service>`. C "Wait a minute". D "Rename the card". **B.** A
platform `make up` or `restart` deletes the registrations (`clear-agent-registry`). On the pinned base image your
agent registers only at startup, so restart it. Once the pin includes the SDK keep-alive, C also works: the agent
registers again within about 5 s; restart if it hasn't. `make down-v` also deletes your users and keys. Deck 03,
"Once, then four commands"; `platform/Makefile`.

### chat-turn

`Chat turn`. Which path does a chat turn take to your agent? A "Browser to agent". B "Browser to the registry". C
"Backend to agent". D "Via the orchestrator": the backend hands the turn to the client-agent, whose LLM calls you
through the backend gateway at `/a2a/<route key>`. **D.** The browser talks only to the backend; the backend
forwards the client-agent's call with `Bearer <AGENT_SECRET>`. Deck 01, slide 9 and A9; `backend/app/a2a_client.py:129`; `client-agent/capability_cache.py:226`.

### secrets

`Secrets`. Your agent needs an LLM key that its `.env` lacks. How do you add it? A "Paste it in the chat". B "Put
it in agent.py". C "Edit .env yourself" in your editor. D "Use .env.example". **C.** A chat key goes into the
transcript, a tracked key into git history. The container gets only what `environment:` lists, so add it there,
then `make up`. Deck 03, slides 8 and 16; `setup_agent.py:300`; `agent_template/docker-compose.yml:58-60`.
