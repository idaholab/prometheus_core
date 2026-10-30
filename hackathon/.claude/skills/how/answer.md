# Answer a question

Answer one question for an engineer who knows Python and git and is new to Prometheus. Use the
KB, then the code and docs at the pin, then the mentor. Edit no file.

## 1. Get the question

The question is the request. With none, ask (header `Question`): "How does my card get me
called?", "How do I read an uploaded file?", "How do I ask the user for a value?", "How do I call
an LLM?". For a failure ("does not work", an error), answer what you can and offer `/diagnose`.

## 2. Read the KB

1. Read `index.md`, and read at most 3 matching files. For an unknown word or an old name from a
   doc or a slide (`message/send`, Chainlit, the planner, the `small` flavor), read the glossary
   and stale-docs sections that `index.md` names.
2. When a KB statement with a source answers the question, go to step 4.

## 3. Look up the code

1. Get `<pin>` (a commit hash, not a secret):
   `PIN=$(grep -E '^PROMETHEUS_API_BASE_IMAGE_HASH=.+' <platform>/.env 2>/dev/null | tail -n 1 | cut -d= -f2-); [ -n "$PIN" ] || PIN=$(sed -n 's/^PROMETHEUS_API_BASE_IMAGE_HASH[[:space:]]*?=[[:space:]]*//p' <platform>/Makefile); echo "$PIN"`.
   When `grep -c '^PROMETHEUS_API_BASE_IMAGE_HASH=$' <platform>/.env` is not 0, say that the
   empty line breaks every platform build, and offer `/diagnose`.
2. Check `docker info >/dev/null 2>&1 && echo up` and `docker ps --format '{{.Names}}'`. Say
   that a lookup subagent searches the code. Spawn one `general-purpose` subagent with this prompt, all `<...>` filled in, and wait for it:

````text
Find the facts in the code and docs that answer one question about the Prometheus agent platform.
You cannot talk to the user. Return facts with citations, not an answer.
QUESTION: <question>
THE KB ALREADY SAYS (find what it does not settle): <at most 15 KB lines, or "nothing">
PATHS: root <root>; agent <agent or none>; project <project or none>, service <service>, running <yes|no>;
docker <up|down>; platform <platform>; template <template>; prometheus_api pin <pin>.
RULES: Read only: no make, docker compose up/down/restart/stop/rm, docker restart/stop/rm, git commit/push, or other state
change. Read files outside root with Bash (sed -n, grep -n, ls), never Read/Grep/Glob. Never
read or source a .env file; never run env, printenv, docker inspect, docker compose config,
curl -v, set -x. A fact that needs a secret: write "needs a secret; not checked". No web.
When the code and a doc disagree, the code is correct; report both.
SEARCH IN THIS ORDER, stop at a cited answer:
1. The agent folder: agent.py, agent_card.json, Dockerfile, docker-compose.yml, tests/.
2. The platform: agents/client-agent/orchestrator/, agents/client-agent/*.py,
   agents/debug-agents/*/, backend/app/, Makefile, docker-compose.yml, docs/docs/; the template:
   setup_agent.py, agent_template/.
3. prometheus_api at the pin. Runner: docker compose -p <project> exec -T <service> python -c "..." when it runs,
   else run it in <platform>/../sdk with uv run python -c "..." (the monorepo's SDK source);
   skip when neither works. Version: import prometheus_api; print(prometheus_api.__version__).
   Find WORD: import pathlib, prometheus_api as p; r = pathlib.Path(p.__file__).parent;
   [print(f'{f.relative_to(r.parent)}:{i}: {l.rstrip()}') for f in sorted(r.rglob('*.py'))
   for i, l in enumerate(f.read_text().splitlines(), 1) if 'WORD' in l]. Source of one object:
   inspect.getsourcelines. The agent base class is prometheus_api/agent/base.py (not
   storage_client/). Cite as sdk/prometheus_api/agent/base.py:<line>.
4. SDK docs in the monorepo: <platform>/../sdk/docs/agent/, sdk/docs/, sdk/examples/, sdk/specs/
   (grep -rn WORD).
RETURN at most 40 lines:
ANSWER: 2-5 sentences. EVIDENCE: - <repo-prefixed path>:<lines> - what it shows.
SNIPPET: up to 15 verbatim lines with a citation, or none. SDK VERSION: version and source, or
not checked. DISAGREES: KB, slide, or doc vs code, with both citations, or none.
NOT FOUND: what you searched, or none.
````

3. Check the one citation that carries the answer (`sed -n` for a sibling clone, `Read` in the
   repository, the snippet for an image or `gh` source). When nothing was found, go to step 6.

## 4. Answer

Give the direct answer in 2 to 6 short sentences: the concept, not only the command. Add a
snippet of at most 15 lines from the KB or the code when it helps; never invent one. When the
code disagrees with a doc or a slide, say that the code is correct. End with "More in
`<kb file>`." and a `Source:` line, the sources separated by `; `.

## 5. Teach and point onward

1. For a visual topic (a chat turn, the services, registration, input-required, artifacts,
   workflows, the agent lifecycle), offer an explainer page.
2. Ask at most one matching check question of `teaching.md`, unless the user said "skip the
   quiz" or you asked that id already: `card-interface` (how a skill gets picked),
   `route-fields` (routing fields), `artifacts` (files), `input-required` (asking the user),
   `registry-wipe` (registration), `chat-turn` (who calls whom), `secrets` (keys, `.env`, git).
3. Name the skill that does the work: `/create-agent` (build or change the agent, the card) or
   `/diagnose` (a failure, the laptop, a chat turn).

## 6. When nothing answers

Say that the KB and the code do not answer it, and what you searched. Name the mentor for the
topic from `mentors.md`, and the channel: the room, Teams, or JIRA `PPLT` for a bug. Never guess.
