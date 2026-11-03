# Check the setup (the homework)

Confirm that the laptop is ready for the hackathon, and fix what is not. Read `environment.md`;
read `llm.md` and `artifacts.md` when an item needs them. Primer: the homework makes sure that the
platform runs before Day 1 (deck 01, homework; deck 03).

## 1. Run the checks

Run the read-only checks without asking, one item per Bash call.

| # | item | check ids (`checks.md`) |
|---|---|---|
| 1 | Tools | `tools` |
| 2 | GitHub access | `repo-access` (the `ssh` form without `gh`) |
| 3 | Docker | `docker` |
| 4 | Base image | `base-image-pin` (`LOCAL_SDK=true`); `registry-login` only without it |
| 5 | Clones | `siblings` ("Not cloned yet" fails it; run the other items) |
| 6 | Platform | `platform-env`, `stack-ps`, `backend-health`, `chat-ui`, `registry-auth`, `registry-agents`, `platform-check` |
| 7 | Login | `admin-user`, `signing-key` |
| 8 | LLM | `llm-key`, `llm-call` |
| 9 | DeepLynx (required) | `deeplynx-env`, `deeplynx-backend` |
| 10 | Personal skills | `personal-skills` |
| 11 | Your agent (SKIP without one) | `agent-env-sync`, `agent-base-image`, `agent-lockfile`, `identity-required-match`, `llm-key-in-agent-env`, `llm-key-in-container`, `llm-client-pattern` |

- Marks: PASS, FAIL, WARN, SKIP, each with evidence (never an `.env` value). `docker` fails: SKIP
  4, 6-9; no container: SKIP 7-9. Both skip the container checks of item 11, not its file checks.
- Item 8: the key comes from "LLM profile → key". For `llm-call`, ask the user to send one chat
  question (header `LLM`): "It answered", "It failed", "Skip"; on a failure read the log for `LLM*Error`.
- Item 11: use the agent's own profile; run `llm-client-pattern` when the code calls an LLM.

## 2. Show the checklist and fix

Show `#`, item, mark, evidence, then one line per FAIL and WARN with its cause. Fix the items in
order, one at a time, by kind (`SKILL.md`, "Fix kinds"). Also:

- **Item 6**: ask before a platform `make up` (the first build is long). For blank secrets, offer
  `make init-env` (`environment.md`, "Fill the platform .env") after its two traps.
- **The first fix with a secret** (registry login, an LLM key, the generator): a 2-line
  primer (deck 03) and the check question `secrets`, once.
- **After item 6 passes**: the check question `registry-wipe`, once; offer
  `/how explain registration and discovery`.
- **DeepLynx** (9): required, since agents exit at startup without it. The platform runs it with
  `LOCAL_DEEPLYNX=true`: follow `artifacts.md` ("Local DeepLynx"). Add the line to the platform
  `.env` (yes), a platform `make restart` (yes; it writes the `DEEPLYNX_*` lines, no secret goes into
  the chat), then `deeplynx-env`, `deeplynx-backend`, `agent-env-sync`, and `make up` in the agent folder.
  A DeepLynx started from its own clone: stop it first (`docker compose down` there; ports 3000, 5000).
- **Personal skills** (10): WARN; give the rename command for the user's own terminal.
- **No LLM key** (8) or **no access** (2): name the mentor (`mentors.md`).

## 3. End

Check the fixed items again and show the final checklist. Items 1-9 pass: "Ready for Day 1" (10
may be WARN, 11 SKIP). Else list each open item with its next step and mentor. Suggest
`/create-agent` when there is no agent yet.
