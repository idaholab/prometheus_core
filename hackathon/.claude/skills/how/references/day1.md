# Day 1: the hello-world agent

Facts as of `prometheus_core` `devel` 2026-10-30, after #310 (`prometheus_api` 0.15, no LiteLLM). When the code disagrees with this file, the code is correct.

Four parts (deck 05, slide 1). You are done when `/agents` lists your agent, the chat returns your greeting, and
your PR is approved. With Claude Code, `/diagnose` checks the laptop, and `/create-agent` does steps 2 to 4.

Names: `<you>` is your login (`gh api user --hostname github.inl.gov -q .login`). The card is `Hello <You> Agent`,
the skill id `hello_<you>_greeting` (`-` to `_`), the container `hello-<you>-agent`. Use your own names: an agent
with the same card name replaces yours (`registry.py:123-130`). Keep the four clones side by side.

## Step 1. Check the platform

Run `git pull`, `make up`, `make ps`, `curl -s localhost:8600/healthz`, and the names-only `/v1/agents` command
(`conventions.md`; deck 05, slide 2). At `http://localhost:5150`, run the wizard (the signing key is created for you).

## Step 2. Scaffold the agent

Run `python3 setup_agent.py` in the template (deck 05, slide 3). Name `Hello <You>`; description `Greets people
by name on behalf of <You>.`; skill id `hello_<you>_greeting`; skill name `Hello <You> Greeting`; output
`../hello-<you>`; Enter for the rest. No `"` or `\` in an answer. It copies the platform secrets into `.env`.

## Step 3. Edit and test

1. Card: description `Greets a person by name on behalf of <You>.`; `usage_notes` `Use when the user asks to
   greet someone, or says hello to <You>. Not for any other task.`; one required string `person_name` (`card.md`).
2. `_execute` returns `{"status": "success", "greeting": f"Hello, {name}, from <You>!"}`, or an error dict
   without `person_name` (`agent-code.md`). Update the two tests (`testing.md`).
3. Check that the agent `.env` has `LOCAL_SDK=true`, `LLM_CONFIG_PROFILE` and the `DEEPLYNX_*` lines (`environment.md`).
4. Run `uv sync` (creates `uv.lock`; commit it), `uv pip install <platform>/../sdk`, `uv run pytest`,
   `uv run ruff check .`.

## Step 4. Run it and see it routed

Run `make up`; expect `Registered 'hello-<you>-agent'` in `docker compose -p hello-<you> logs --no-log-prefix`. Run the discovery
refresh (`conventions.md`). In a new conversation, type `/agents`, then "Please greet Marie Curie on behalf of
<You>". After each edit, run `make up` again. Problems: `troubleshooting.md`.

## Step 5. The practice PR

Deck 05, slide 5. Fork and clone as `git-pr.md` says, then:

```sh
git switch -c feature/hello-<you> upstream/main
mkdir -p practice/<you> && cp ../hello-<you>/{agent.py,agent_card.json,README.md} practice/<you>/
git status                      # NO .env in the list!
git add practice/<you> && git commit -m "Add hello-world agent for <you>" && git push -u origin HEAD
gh pr create --repo genesis/hackathon --base main --head <you>:feature/hello-<you> --title "Practice: hello from <you>"
```

Copy only these three files. A neighbour comments; you reply "Fixed in <sha>"; they approve; a mentor merges.
