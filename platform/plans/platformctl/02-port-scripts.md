# 2: Port the scripts and remove them

> **Status: In review** (PR #337, branch `platformctl-step2`; the review panel's findings are fixed in follow-up commits)

Lands after the hackathon (Day 2).

**Done so far:** `config init`/`set`/`show`, `status [--wait]`, `deeplynx setup`; the three scripts as stubs; the
Makefile forwards `init-env`, `check`, `deeplynx-setup` and has `make doctor`; `PLATFORMCTL_MAKE_VARS` (tested
with a real Make 3.81); `--json` on the shim and `__main__` refusals; `allow_abbrev=False`; `envfile.update_text`
by parsed span; the moved tests; CI's `sed` blocks; the wider `.gitattributes` and path filter; the user guide,
docs and `platform/README.md`; `--live` selects `tests/live`; the flaky port test; the canary for the new commands.

**Differs from the plan:**

- `config init` prints `Next: make up` (not `./platformctl up`, which does not exist until step 3a).
- The base-image "test pull" is `docker manifest inspect` with a 15 s timeout: same registry path and login,
  nothing downloaded.
- Under `make`, an answer that changes `LOCAL_SDK` or `LOCAL_DEEPLYNX` is saved and `config init` stops (exit 1,
  "Run the same make command again"), because make read `.env` before this run and chose the base image and the
  DeepLynx targets from the old one; carrying on would build the wrong way. It also prints no `Next:` line under
  make. (The review panel found the first version, a warning only, left a first `make up` pulling from the registry.)
- `config init`'s error for a missing profile or key ends "run ./platformctl config init again" where the script said
  "run make again". The "[ERROR]" block and every other quoted line are unchanged.
- `make test-system` is unchanged: its recipe never called `scripts/check_platform.py` (only the plan said so).
- `config set` checks a value against its setting's type (`BACKEND_PORT` digits, `LOCAL_SDK` true/false), refuses
  a key name `.env` could not parse, and makes a group- or world-readable `.env` owner-only before adding secrets.
- `--json` prints one object on every path of `config init`, `config set` and `deeplynx setup`, not only on failure.
- `check-prerequisites` is not forwarded to `doctor` (that is step 3a's C9), so `from-make.md` has no such row.

**Not done yet:** the scrubber's URL-encoded/base64 forms and URL passwords (and distinct canary sentinels);
the canary's `CI=1`/real `_streamed`/`.env`-write cases; making the step 1 jobs *required* (branch protection, a
repository setting) and gating `merge_group`; the macOS Python 3.9 leg asserting which interpreter ran; the
WSL and arm64 legs; the `make -n` fixtures for step 3a; the hackathon-freeze check (the PR is held until after Day 2).

## Goal

Move `scripts/init_env.py`, `scripts/check_platform.py` and
`scripts/deeplynx_setup.py` into platformctl, leaving each as a short
deprecation stub until step 3c deletes them.

## Work

- **Actions:** `config init` (from `init_env.py`), `config show`
  (`--json`) and `config set`; `status` with `--wait` (from `check_platform.py`; the
  service-state half of `status` arrives in step 3a); `deeplynx setup` (from
  `deeplynx_setup.py`).
- **New in `config init`:**
  - Report keys in `.env.example` that `.env` lacks (today a new key never
    reaches an existing `.env`). The same check goes into `doctor`.
  - **Local SDK and local DeepLynx.** `--local-sdk`/`--no-local-sdk` and
    `--local-deeplynx`/`--no-local-deeplynx` set `LOCAL_SDK` and
    `LOCAL_DEEPLYNX` in `.env`. Without a flag, an interactive run asks for
    each when `.env` doesn't decide it yet (for DeepLynx: neither
    `LOCAL_DEEPLYNX` nor `DEEPLYNX_KEY` set), in plain words with a
    recommended answer that Enter accepts: "Build everything on this laptop
    (no INL login needed)? (recommended) [Y/n]" and "Run DeepLynx (file
    storage) on this laptop? (recommended) [Y/n]". The SDK recommendation comes from a test
    pull of the pinned base image with a short timeout (off the VPN it would
    otherwise hang). It reuses the existing menu code, with its numbered
    fallback when `termios` is missing. It never changes a value that's
    already set unless a flag asks. Today the hackathon tells people to
    `echo "LOCAL_SDK=true" >> .env` by hand (deck 03) and walks them through
    DeepLynx in the browser.
  - **No terminal:** asks nothing and uses flags and the environment as
    today. It exits 1 only where `init_env.py` does today (no LLM profile
    or key). The new questions don't fail it: an unanswered `LOCAL_SDK` or
    `LOCAL_DEEPLYNX` keeps today's default (off), with a one-line note
    naming the flag. Otherwise CI and assistant runs of every start target
    (which run `config init`) would start failing.
  - `.env` is created 0600 and written atomically; the LLM key is read with
    `getpass`, which stops rather than echo.
  - `--instance <name>` is **not** in this step: agent folders hardcode the
    platform's network name until step 7 (`design.md`, "Replace as you
    go").
- **`config set KEY=value ...`** writes values into `.env`, in place
  (unlike the global `--set`, which overrides for one run; a second
  `--set` on `config init` can't exist anyway, since argparse rejects a
  subparser option that clashes with the inherited global one, verified).
  Like the global `--set`, it refuses keys the registry marks secret.
  **`config set --from-env KEY ...`** copies each key's value from the
  environment instead, for secrets: the value never appears in argv, shell
  history or `ps`. It exits 1 naming any key that isn't set in the
  environment. CI uses `config set --from-env DEEPLYNX_KEY DEEPLYNX_SECRET
  DEEPLYNX_ORG_ID DEEPLYNX_PROJECT_ID` to replace its three `sed` blocks
  (the stubs are already in the job's environment).
- **Adapters:** `system/deeplynx.py` (never prints request headers or
  bodies). `.env` writes go through `system/envfile.py`.
- **Messages stay word for word.** Deck 03 shows `init-env`'s output
  ("Created .env from .env.example.", "Generated in .env: ...", the profile
  menu, "Saved LLM_CONFIG_PROFILE=... in .env."), and CI relies on the
  others.
- **Makefile:** `init-env` → `config init`, `check` → `status --wait`,
  `deeplynx-setup` → `deeplynx setup`, each setting `PLATFORMCTL_VIA_MAKE=1`
  (so the tool reads Make's command-line variables) and printing the new
  command. **`test-system`**: the plan
  said its recipe calls `scripts/check_platform.py` (`Makefile:259`), but it only runs the system tests, so nothing
  switches. `test_compose_static.py` parses that recipe and still passes.
- **Replace** the three scripts with stubs that print one line ("moved:
  run `./platformctl config init`") and exec the new command. The hackathon
  knowledge base and deck 03 (`checks.md`, `environment.md`,
  `03-deployment.md`) and `platform/README.md` users still name them, and
  the hackathon material can't change until 3c. Step 3c deletes the stubs.
- **Moved from step 1** (it had to stay out of the hackathon freeze):
  - `make doctor`: `doctor: ##@ ...` forwarding to the shim.
  - **`.gitattributes`** (repo root): step 1 added it with `platform/platformctl`
    and `*.sh` as `text eol=lf`. Widen it to `*.py`, `Makefile`, `Dockerfile`,
    `*.yml`, `.env.example` and `*.md` as `text eol=lf`. `NOTICE.txt` is already
    committed with CRLF and a BOM; give it `-text` so nothing changes for it.
  - The step 1 CI jobs become required, and their path filter widens to
    `platform/Makefile`, `platform/scripts/` and the compose files.
- **Tests:** move `tests/infrastructure/test_check_platform.py`,
  `test_deeplynx_setup.py` and the `init_env` parts of `test_env_vars.py`
  into `ctl/tests/unit/` in this PR. Keep the parts of `test_env_vars.py`
  that test `.env.example` itself; `test_required_secrets_have_generator`
  points at the new generator code.
- Search before opening the PR:
  `git grep -nE 'scripts/(init_env|check_platform|deeplynx_setup)|make (init-env|check|deeplynx-setup)'`.

## Output

- `config init`: one line per thing it did ("Created .env", "Generated 5
  secrets", "LLM profile: anthropic, key set", "Local SDK: yes"), the keys
  missing from `.env`, and a closing "Next: ./platformctl up" (with local
  DeepLynx: "Next: ./platformctl up, then ./platformctl deeplynx setup").
  The lines deck 03 quotes stay word for word.
- The user guide's `index.md` says: the first time, just run
  `./platformctl up`; it runs `config init` and asks what it needs.
- `config show`: a table of settings, value (secrets as `set`/`blank`), and
  where it came from.
- `status --wait`: what it's waiting for and how long it has left
  ("backend ok, frontend ok, agents 2/3: waiting for synthesis-agent, 240 s
  left"); on a timeout, what's missing and the `doctor` check for it.
- `deeplynx setup`: the steps (server up, project found or created, key
  saved) and the DeepLynx UI URL.

## Replaces

- `scripts/init_env.py`, `scripts/check_platform.py`,
  `scripts/deeplynx_setup.py`: stubs that forward to the new commands,
  removed in step 3c.
- `make init-env`, `make check` and `make deeplynx-setup` forward to the new commands, and the start targets call
  `config init` and `status --wait` through the tool.
- CI's `sed` blocks after `make init-env`: `config set --from-env`.
- The manual `echo "LOCAL_SDK=true" >> .env` step (deck 03) and the manual
  DeepLynx clone, build, project and key steps: replaced by the
  `config init` questions and `deeplynx setup` (the slides and KB switch
  in step 3c, both together).

## Docs and slides

- **Set up the user guide** (moved from step 1) on the docs site,
  `platform/docs/docs/platformctl/` (`design.md`, "User guide"): `index.md`
  with what platformctl is, how to run it, and `./platformctl doctor`;
  `troubleshooting.md` with `doctor`; `from-make.md` with its table header
  and the `check-prerequisites` and `doctor` rows. Link the section from the
  site's `index.md` and from `prometheus-platform.md`'s "Getting started".
  Check it with `uv run zensical build` in `platform/docs`.
- **User guide:** `setup.md` (`config init`, its questions, `config show`,
  `deeplynx setup`), `everyday.md` started with `status --wait`;
  `from-make.md` rows for `init-env`, `check`, `deeplynx-setup`.
- `platform/README.md`: a short "platformctl" section that links to the user
  guide (moved from step 1).

Switch to `./platformctl config init`, `./platformctl status --wait` and
`./platformctl deeplynx setup` in:

- `platform/README.md` (including `python3 scripts/init_env.py`),
  `platform/CLAUDE.md`, `platform/tests/README.md`
- `docs/docs/prometheus-platform.md`, `docs/docs/local-deeplynx.md`,
  `docs/dev-docs/encryption-and-keys.md`, `docs/dev-docs/multi-user-setup.md`
- `backend/app/routers/agent_registry.py` docstring
- Python 3.10+ (found automatically) where docs list prerequisites:
  `platform/README.md`, `docs/docs/prometheus-platform.md`,
  `docs/docs/windows-wsl2-setup.md` (per distro)

**Not yet:** the hackathon slides, skills and knowledge base, and the
agent-template docs. Their setup blocks also use `make up`, so they switch
together in step 3c, with no mixed `make`/`./platformctl` blocks
(`design.md`, "Documentation and slides").

## What changes for you

- **Commands:** `make init-env`, `make check`, `make deeplynx-setup` work as
  before; the docs now say `./platformctl config init`, `status --wait`,
  `deeplynx setup`. `python3 scripts/init_env.py` still works, with a
  one-line "moved" notice. `make doctor` is new.
- **Files created:** none new. `.env` gets `LOCAL_SDK` and `LOCAL_DEEPLYNX`
  if you answer the new questions.
- **First run:** `config init` (and so `make up`) may ask two new questions;
  Enter accepts the recommended answer. It lists keys `.env.example` has
  and your `.env` lacks.
- **Needs:** Python 3.10+, found by the shim. `sudo make up` is refused.
- **Roll back:** revert the PR. The two new `.env` lines are harmless to the
  old Makefile (delete them if you like).

## Breaking changes

- **B1:** the three scripts become forwarding stubs (removed in 3c);
  `make test-system` is unchanged.
- **B2:** `make init-env`, `make check`, `make deeplynx-setup` and every
  start target (which run `init-env`) now need Python 3.10+, which the shim
  finds.
- **B4:** `sudo make up` is refused, with both fixes in the message.
- **C10:** `config init` asks two more questions on a first run (Enter
  accepts the recommended answers) and reports missing keys.

## Tests

- **Unit:** the ported behaviour at 100%, with each quoted message pinned
  (move `test_deeplynx_setup.py`'s pin on "make init-env" to the new
  wording, `./platformctl config init`);
  the local SDK and DeepLynx questions (asked, skipped when set, flags, no
  terminal, the pull timeout); `config set` (refusing secrets) and
  `config set --from-env` (a missing key); file mode and atomic
  writes; the secrets canary for the new commands.
- **`make -n` fixtures for step 3a** (`design.md`, "Tests"): record
  `make -n <target>` for every compose target over the variable matrix,
  with a placeholder `.env`, while the Makefile logic still exists.
- **Live:** `config init` on a real file in `tmp_path`, including its menu
  in a pseudo-terminal; `status --wait` against a stub server.

## CI

- The three `sed` blocks (`platform: up`, `platform: up deeplynx`,
  `agent-template: platform`) become `make init-env` followed by
  `./platformctl config set --from-env DEEPLYNX_KEY DEEPLYNX_SECRET ...`.

## From the step 1 review

Findings the step 1 review deferred to here. "Checked" means the review's author reproduced it;
"reported" means a reviewer found it and nobody has reproduced it yet, so reproduce it first.

- **Make's command-line variables** (checked). Step 1's `make_overrides` reads the words after
  ` -- ` in `MAKEFLAGS`, which Make 3.81 omits for a plain `make X=y`, and its tests only use the
  ` -- ` form. Have the Makefile export `PLATFORMCTL_MAKE_VARS` (see `design.md`, "Settings and
  precedence"), read that instead, and test it by running a real `make` and feeding its
  environment to `make_overrides`, on both Make 3.81 and 4.x. Unknown names get the one-line
  warning `design.md` promises (a reviewer reports they are ignored silently today; check).
- **`--json` on every exit path** (checked). `SUDO_USER=x ./platformctl doctor --json` and a bad
  `PLATFORMCTL_PYTHON` print plain text and exit 1, with no object. This step makes `make` call the
  tool, so decide: print a minimal `{"schema_version":1,"ok":false,"error":{...}}` from
  `__main__.py` and the shim when `--json` is in argv (`json` is stdlib and importable on 3.9), or
  document the two exceptions in `design.md` and the user guide.
- **`envfile.update_text`** (checked). It rewrites only the first line of a quoted multi-line
  value (`K="a\nb"` becomes `K=x\nb"`), and for a duplicate key it edits the first line while
  `parse` takes the last. `config set` and `config init` write `.env` through it: update by parsed
  span, replace the last occurrence, and test both.
- **Argparse abbreviations** (checked: `doctor --li` runs `--list`). Set `allow_abbrev=False` on the
  parser and every subparser, so abbreviations aren't part of the interface.
- **The scrubber's forms** (reported). URL-encoded and base64 forms of a secret, and a password in
  a URL-shaped value such as `DOCKER_HOST=tcp://u:pw@h` or `HTTPS_PROXY`, are not scrubbed, and
  the canary reuses one sentinel for `DOCKER_HOST` so it cannot see the gap. Register the password
  of URL-shaped environment values, add the encoded forms, and give the canary distinct sentinels.
  Also: a short secret under `MIN_SECRET_LENGTH`, and `LLM_CONFIG_PROFILE` (not a secret) masked in
  output because unregistered keys count as secret. Register it as safe.
- **The canary's reach** (reported). It runs only `doctor` and `--version`; it never sets `CI=1`
  (the `::group::` path), never uses the real `Runner._streamed`, never writes `.env` through
  `envfile.update`, and has no duplicate-key or comment-secret case. Add them with the new
  commands.
- **CI for the jobs becoming required** (reported):
  - the macOS Python 3.9 leg probably runs Homebrew's Python, because the shim tries
    `/opt/homebrew/bin/python3` by path, and the tests that would notice skip. Assert which
    interpreter ran (or add an override that empties the Homebrew list) and fail instead of
    skipping under `PLATFORMCTL_REQUIRE_PY39`;
  - `merge_group` ignores `paths:`, so every merge-queue run starts all legs: gate them on a
    changed-files job once the checks are required;
  - `pytest --live` collects only `tests/unit`, because `testpaths` is `tests/unit`: make `--live`
    select `tests/live`, or fail when it collects none; and `tests/shim` is outside the default run;
  - add a live test that copies the platform tree to a temp folder, runs `config init` and
    `doctor --json --tag preflight`, and asserts no FAIL; holding a port with `socket` should fail
    naming the holder;
  - `test_port_free_without_ipv6` failed 2 of about 40 runs (another process takes the closed
    port): patch `_bind` and `_connects` in that test.
- **WSL and arm64 legs** (reported): a `windows-latest` WSL leg and an `ubuntu-24.04-arm` leg for
  the shim and unit tests; the manual WSL checklist from step 1.

## Review

Before merging, run `/review-panel` on the PR (see `reviews.md`) with these reviewers: all eight.

Ask them to look at:

- **Technical:** that messages stay word for word (deck 03, CI); Make's command-line variables
  with `PLATFORMCTL_VIA_MAKE=1`, tried on the Make on a Mac (3.81), where `make X=y` puts no
  ` -- ` in `MAKEFLAGS`; that `config set` refuses secret keys and `--from-env` keeps values out
  of argv; that each stub execs the new command.
- **CI and tests:** that the moved tests lose no coverage; the CI jobs that switch from `sed` to
  `config set --from-env`; the `test-system` recipe that `test_compose_static.py` parses; the step
  1 jobs becoming required with the wider path filter.
- **Security:** `.env` created 0600 and written atomically; the LLM key read with `getpass`;
  `config show` and `--json` printing no secret; the DeepLynx adapter printing no headers or
  bodies; the canary extended to every new command.
- **Linux/WSL:** the numbered menu when `termios` is missing; `.gitattributes`, which step 1
  already created for the shim and `*.sh` and this step widens (`NOTICE.txt` must not change); the
  base-image test pull off the VPN.
- **User:** the new questions ("Build everything on this laptop?") in plain words, with an answer
  Enter accepts; first run on a fresh clone.
- **Rollout:** an existing `.env` that lacks new keys; the hackathon freeze; stubs for scripts the
  decks still name; `breaking-changes.md`.
- **AI skills:** no-terminal behaviour of `config init`, with a note instead of a failure; `--json`
  of `config show` and `status`.
- **Agent developer:** agents scaffolded earlier still working through the stubs.

## Done when

- The three scripts are stubs, and nothing outside the hackathon material
  and agent-template docs references them.
- CI's `platform: up` job passes (it runs `make init-env` and `make up`),
  and so does `make test-system`'s recipe test.
