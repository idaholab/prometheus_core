# Set up a new agent

Set up an agent that runs, registers, and shows in `/agents` of the Prometheus chat. The argument
is the agent name. KB: `card.md`, `agent-code.md`, `run-and-register.md`, `testing.md`, `llm.md`.

## 1. Preconditions

Check with a mark each: `test -f <platform>/.env`; `make ps` in `<platform>` shows the services `backend`,
`client-agent`, `redis`, `admin-db`; `curl -s localhost:8600/healthz` gives
`{"status":"ok"}`; `uv --version`; Python 3.9+; the platform `.env` has `DEEPLYNX_KEY`, `DEEPLYNX_ORG_ID` and `DEEPLYNX_PROJECT_ID` (`grep -c`; agents exit at startup without them). On a fail, send to `/diagnose check my laptop`.

## 2. Day 1 or Day 2

Primer: Day 1 is the practice agent in `<parent>/hello-<you>/` (deck 05, slide 1); Day 2 is the
team agent in `agents/<team_name>/` (deck 02, slide 3). Ask (header `Agent kind`): "Day 1
practice agent (Recommended)", "Day 2 team agent". Day 2 skips step 3 and 10.1-10.3,
`<OUTPUT_DIR>` = `<root>/agents/<team_name>`, and builds the planned skills as stubs.

## 3. Day 1 names

1. `<you>` = `gh api user --hostname github.inl.gov -q .login`; on a fail, ask (header `GitHub user`).
2. `<You>`: each hyphen part capitalized. `<you_id>`: lowercase, `-` to `_`. Agent name
   `Hello <You>` (card name `Hello <You> Agent`), skill id `hello_<you_id>_greeting`,
   `<OUTPUT_DIR>` = `<parent>/hello-<you>`.
3. When `<OUTPUT_DIR>` exists, ask (header `Folder`): "Continue with this folder (Recommended)",
   "Start over (deletes the folder)", "Use another folder". Continue: read the names from its
   card, skip to step 7, and when it has no `.env`, make one first:
   `cd <template> && printf 'yes\n' | python3 -B -c 'import sys, pathlib, setup_agent; setup_agent.PLATFORM_ENV_PATH = pathlib.Path(sys.argv[2]); setup_agent.create_env_from_platform_if_requested(pathlib.Path(sys.argv[1]))' "<OUTPUT_DIR>" "<platform>/.env"`.
4. Show the names (a name in the argument first). Ask (header `Names`): "Use these names
   (Recommended)", "Change the names" (then step 4).

## 4. Plan the card (Day 2, or changed Day 1 names)

Primer: the LLM routes on the card alone; equal names overwrite each other (deck 04, slides
4-7). Ask in rounds, 2-4 candidates each, by the rules of `card.md`: the team (header `Team`, a
new lowercase folder below `agents/`) and the agent name (starts with the team, not "Agent");
the skills (header `Skills`: prefixed ids such as `neutron_extract_table`, a description, the
`usage_notes`, the inputs, few required); `capabilities.streaming` (header `Streaming`). Show
the plan. Ask (header `Plan`): "Looks right (Recommended)", "Change something".

## 5. Check the names, then the quiz

1. Derive the slug, the class, and the route key with the scaffolder's own functions:

   ```sh
   cd <template> && python3 -B -c 'import sys, setup_agent as s; n = sys.argv[1]; c = s.to_pascal_case(n); print("slug:", s.to_kebab_case(n)); print("class:", c + "Agent", (c + "Agent").isidentifier()); print("route key:", (n + " Agent").lower().replace(" ", "-"))' "<agent name>"
   ```

   The class must print `True`; `TEMPLATE_CLASS` is it without `Agent`.
2. Reject a name that is not ASCII letters, digits, single spaces, and hyphens, starting with a
   letter, or that ends with "Agent". Reject `"`, `\`, or a newline in any value.
3. List the registered names and skill ids:

   ```sh
   set -a; source <platform>/.env; set +a; curl -s -H "Authorization: Bearer $AGENT_SECRET" localhost:8600/v1/agents | python3 -c 'import json, sys; [print(a.get("agent_name"), sorted(s.get("id") for s in (a.get("agent_card_params") or {}).get("skills", []))) for a in json.load(sys.stdin)]'
   ```

   The route key must not be listed: the same key deletes the other agent's entry
   (`registry.py:123-130`). Each skill id matches `^[A-Za-z0-9_-]{1,64}$`, is not `ask_user`, and
   is not listed.
4. Ask the check question `card-interface`. Offer `/how explain the agent card`.

## 6. Scaffold

1. Primer: `setup_agent.py` copies `agent_template/`, fills 9 placeholders, and offers to copy the
   platform secrets (deck 04, A4). It prompts, so never run it bare. Ask the check question
   `secrets`.
2. Unless "Start over": when `<OUTPUT_DIR>` exists, show it. Day 2 commits there
   (`git -C <root> log --oneline -3 -- agents/<team_name>`) mean a teammate's agent: stop. Else ask
   (header `Folder`): "Pick another folder (Recommended)", "Overwrite it".
3. Run `python3 setup_agent.py --help </dev/null`. When it lists `--` options beyond `--help`,
   build the command from those flag names only, pass all 9 values, the copy flag, and the
   no-prompt flag, with `</dev/null`. Otherwise (template a08387d) use the fallback in one Bash
   call. The closing `EOF` stands alone at the start of its line:

```sh
ANSWERS_JSON=$(cat <<'EOF'
{
  "TEMPLATE_NAME": "<agent name>",
  "TEMPLATE_DESCRIPTION": "<agent description>",
  "TEMPLATE_SLUG": "<slug>",
  "TEMPLATE_CLASS": "<class without Agent>",
  "TEMPLATE_SKILL_ID": "<first skill id>",
  "TEMPLATE_SKILL_NAME": "<first skill name>",
  "TEMPLATE_SKILL_DESCRIPTION": "<first skill description>",
  "OUTPUT_DIR": "<OUTPUT_DIR>",
  "TRIM_COMMENTS": "false"
}
EOF
)
cd <template> && printf 'yes\n' | python3 -B -c 'import json, sys, pathlib, setup_agent; setup_agent.PLATFORM_ENV_PATH = pathlib.Path(sys.argv[2]); setup_agent.create_agent(json.loads(sys.argv[1]))' "$ANSWERS_JSON" "<platform>/.env"
```

   Day 1: `Greets people by name on behalf of <You>.`, `hello_<you_id>_greeting`,
   `Hello <You> Greeting`, `Greets a person by name on behalf of <You>.`
4. Stdin answers "Overwrite?" (existing folder only), then "Create `.env`?": pipe `printf 'yes\n'`,
   or `printf 'yes\nyes\n'` after a confirmed overwrite.
5. Expect `Agent Created Successfully!`, then
   `test -f <OUTPUT_DIR>/.env && grep -qx '.env' <OUTPUT_DIR>/.gitignore && echo ok`. When it fails,
   the platform `.env` holds none of the keys: send the user to `/diagnose check my laptop`. Day 2:
   `git -C <root> check-ignore -q agents/<team_name>/.env && echo ignored` must print `ignored`.

## 7. Complete the agent `.env`

The scaffolder copies the platform secrets, `LLM_CONFIG_PROFILE`, `LLM_API_KEY`, `DEEPLYNX_*`, and
`LOCAL_SDK=true`, but not a hash pin or `USER_IDENTITY_REQUIRED` (`setup_agent.py:48-66`). Show the planned edits as key names. Ask
(header `.env edits`): "Apply the edits (Recommended)", "Skip". Check each result with `grep -c`.

1. The pin, only when the platform `.env` has no `LOCAL_SDK=true` (`grep -c '^LOCAL_SDK=true' <OUTPUT_DIR>/.env`
   is then 0):

   ```sh
   pin=$(sed -n 's/^PROMETHEUS_API_BASE_IMAGE_HASH=\([^[:space:]#]*\).*/\1/p' <platform>/.env | tail -n 1); [ -n "$pin" ] || pin=$(sed -n 's/^PROMETHEUS_API_BASE_IMAGE_HASH ?= *\([^[:space:]#]*\).*/\1/p' <platform>/Makefile | head -n 1); echo "pin: $pin"
   ```

   When `grep -c '^PROMETHEUS_API_BASE_IMAGE_HASH=.' <OUTPUT_DIR>/.env` is 0, append
   `printf '\nPROMETHEUS_API_BASE_IMAGE_HASH=%s\n' <pin> >> <OUTPUT_DIR>/.env`. Without it the agent
   builds from `latest` (deck 02, A5).
2. The LLM key: read `LLM_CONFIG_PROFILE` from the agent `.env`; it must be set (compose stops
   otherwise) and not `registry`. `ollama` needs no key; otherwise it is `LLM_API_KEY` (`llm.md` "## Profile to key map");
   `setup_agent.py` normally copies it. When the agent `.env` lacks it and the platform has a real
   value, copy the line without showing it:
   `{ [ -n "$(tail -c 1 <OUTPUT_DIR>/.env)" ] && echo; grep '^<KEY>=' <platform>/.env | tail -n 1; } >> <OUTPUT_DIR>/.env`.
   Else the user adds it in their editor.
3. When `grep '^USER_IDENTITY_REQUIRED=' <platform>/.env` prints `false` and the agent `.env` has
   no such line, append `USER_IDENTITY_REQUIRED=false`. Else every call fails with "No
   'userToken' found" (check `identity-required-match` in `checks.md`).

## 8. Edit the generated files

Obey "Before a write" for each file. Skip edits already in place.

Day 1 (deck 05, slide 3):

1. `agent_card.json`: `description` `Greets a person by name on behalf of <You>.`, `usage_notes`
   `Use when the user asks to greet someone, or says hello to <You>. Not for any other task.`,
   `output_format` `JSON with keys: status, greeting`. Rename the input `input_data` to
   `person_name` (`The name of the person to greet.`), and set `required` to `["person_name"]`.
2. `agent.py`: in `_execute`, keep the docstring, and replace the 4 numbered blocks with:

   ```python
           name = params.get("person_name")
           if not name:
               return {"status": "error", "error": "person_name is required"}
           return {"status": "success", "greeting": f"Hello, {name}, from <You>!"}
   ```

3. `tests/test_agent.py`: keep `_make_agent()`. Replace the template tests with
   `test_execute_greets_the_person` (`{"person_name": "Marie Curie"}`, the exact greeting) and
   `test_execute_rejects_missing_name` (`{}`, `status == "error"`).

Day 2:

1. `agent_card.json`: all planned skills, `usage_notes`, `inputSchema`, `output_format`, and
   `capabilities.streaming`.
2. `agent.py`: a `skill_id` dispatch with one stub per skill. The base class puts the `skillId`
   into `params["skill_id"]` (`base.py:462-469`):

   ```python
           handler = {
               "<skill_a>": self._<skill_a>,
           }.get(params.get("skill_id"))
           if handler is None:
               return {"status": "error", "error": f"Unknown skill: {params.get('skill_id')}"}
           return await handler(params, context, event_queue)

       async def _<skill_a>(self, params, context, event_queue) -> dict[str, Any]:
           # TODO: read params["<input>"] and do the work (hint: one step per helper).
           return {"status": "error", "error": "not implemented yet"}
   ```

3. Tests: one per skill with `{"skill_id": "<id>", ...}`, and one parametrized test for an
   unknown and a missing `skill_id`. A new module needs a `COPY` line in the `Dockerfile`.

## 9. Test, run, and register

1. `cd <OUTPUT_DIR> && uv sync && uv pip install <platform>/../sdk` (the SDK from the
   monorepo clone; why and other sources: `testing.md`). `uv sync` creates `uv.lock`: commit it with `pyproject.toml` (the build stops without
   it). Add packages with `uv add <pkg>`. Then `uv run pytest && uv run ruff check .`; pytest includes
   `test_build_app_loads_agent_card`. Explain each failure before a fix.
2. `make up`. "must be launched first", "pull access denied", "uv.lock not found", or an exit with
   "Invalid required DeepLynx configuration": send the user to `/diagnose check my laptop`.
3. Wait for the registration (never `make logs`; when `sleep` is refused, `run_in_background`):

   ```sh
   for i in $(seq 15); do docker compose -p <project> logs --no-log-prefix <slug>-agent 2>&1 | grep "Registered '" && break; sleep 2; done
   ```

   Expect `Registered '<route key>' with LiteLLM at http://backend:8000` (old SDK wording; the URL is
   the backend). `<project>` is the folder name of `<OUTPUT_DIR>`, in lowercase. Else send the user to `/diagnose`.
4. Run the discovery refresh of `conventions.md` (on a fail, `docker compose -p prometheus_platform restart client-agent`).

## 10. Day 1: chat, then the practice files

1. Tell the user: open `http://localhost:5150`, a new conversation, `/agents`, then "Please greet
   Marie Curie on behalf of <You>" (deck 05, slide 4). One fresh conversation per test. When it
   is not called, send them to `/diagnose trace my last chat`.
2. Offer (header `Stretch`): "Not now (Recommended)", "Add a status update": streaming `true`, a
   `send_status_update(...)` before the return, an `enqueue_event.await_count >= 1` assert, then
   pytest, `make up`, and the refresh.
3. "Before a write", then
   `mkdir -p <root>/practice/<you> && cp <OUTPUT_DIR>/agent.py <OUTPUT_DIR>/agent_card.json <OUTPUT_DIR>/README.md <root>/practice/<you>/`.
   `git -C <root> status --short --untracked-files=all practice/<you>` lists only those three
   files: no `.env` goes into the PR (deck 02, slide 14). For the branch and PR, point to
   `day1.md`. Do not commit unless asked.
4. Ask (header `Next`): stop, or build a first skill with `add-feature.md` (Day 2: recommended).
