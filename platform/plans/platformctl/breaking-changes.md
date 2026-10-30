# platformctl: breaking changes

Everything a user, script, doc or CI job relies on today that stops working
or behaves differently. Each step's PR lists the items it introduces under a
**Breaking changes** heading.

**Breaking** means something that works today fails or does something else
afterwards, with no change on the user's side. **Behaviour change** means it
still works, but differently.

## Breaking

| # | Step | What breaks | Who is affected | Migration |
|---|---|---|---|---|
| B1 | 2, 3c | `python3 scripts/init_env.py`, `scripts/check_platform.py` and `scripts/deeplynx_setup.py` become stubs that forward to the new commands in step 2, and are removed in step 3c | Anyone running them directly (`platform/README.md:53` and `docs/docs/prometheus-platform.md:50` say to); tests that import them; `make test-system`, whose recipe calls `scripts/check_platform.py` (`Makefile:259`) | `./platformctl config init`, `status --wait`, `deeplynx setup`. The `test-system` recipe, docs and tests are updated in the same PR |
| B2 | 2 | Running the platform needs Python 3.10 or newer. Today `make up` runs `init_env.py` with any `python3`, including 3.9 | Only machines with no Python 3.10+ at all. The shim finds `python3.1x` and uv-managed Pythons, so a Mac with the built-in 3.9 `python3` plus uv's 3.12 works | Install Python 3.10+ (or uv). The shim prints the one command to run |
| B3 | 3a | Make variables that were only internal plumbing are no longer read: `COMPOSE`, `COMPOSE_BASE`, `COMPOSE_AGENTS`, `COMPOSE_FILES`, `COMPOSE_FILES_NG`, `CLEAR_COMPOSE_FILES`, `UP_WAIT`, `RUN_CHECK`, `BASE_IMAGE_DEP`, `DEEPLYNX_DEP`, `AGENT_COMPOSE_FILES`, `PROFILE_FLAGS`, `INFRA_SCRIPTS` | Anyone overriding them on the command line (none found in docs or CI) | The documented settings and `--set` |
| B4 | 2 | `sudo make up` works (the files it writes end up owned by root) | Linux machines where policy forbids the `docker` group | The tool refuses under `sudo` (`SUDO_USER` set). Its message gives both fixes: `sudo usermod -aG docker $USER` then `newgrp docker`, or rootless Docker |
| B5 | 3a | `make logs \| grep ...` follows the logs | Anyone piping `make logs` or `./platformctl logs` | Without a terminal on stdout, `logs` prints and exits instead of following, so a script or assistant can't hang. `--follow` follows anyway |


`make <target> KEY=value` keeps beating `.env`, as today, including secret
keys and values with spaces: the tool reads Make's command-line variables
from `MAKEFLAGS` and the environment (`design.md`, "Settings and
precedence"). `make logs SERVICE=...`, which deck 03 uses throughout, is
unaffected.

## Behaviour changes

| # | Step | Today | After |
|---|---|---|---|
| C1 | 3a | A blank `PROMETHEUS_API_BASE_IMAGE_HASH=` or `_REPO=` line breaks the build ("invalid reference format") | The tool falls back to the default. `doctor` warns about the blank line, since a hand-run `docker compose` still sees it |
| C2 | 3a | Compose runs with `-p` and a list of `-f` files | Compose runs `-f docker-compose.platform.yml`, a generated file. Same containers, volumes, networks and images; CI checks the merged config is identical |
| C3 | 3a | `docker-compose.yml` has no `name:`, so a plain `docker compose` in `platform/` creates a project called `platform` | `name: ${COMPOSE_PROJECT_NAME:-prometheus_platform}`. A stack someone started that way is left behind under the project `platform`: remove it with `docker compose -p platform down` |
| C4 | 3a | | Two new generated, git-ignored files in `platform/`: `docker-compose.platform.yml`, `.platform.env` |
| C5 | 3b | After `make up`/`restart`, a developer's agent stays unregistered until they restart it by hand | The tool restarts your agents (containers labelled as Prometheus agents on the platform network) so they register again, and says so. Open chat turns are warned about first. `--no-restart-agents` (or `make up RESTART_AGENTS=false`) only prints them |
| C6 | 1-3c | `make up` prints Make's recipe lines and Compose's output | The tool prints numbered steps and a summary (what's running, URLs); Compose's output only for the slow parts, and in full with `--verbose` or in CI. Each forwarded `make` target also prints one line naming the new command (`make up -> ./platformctl up`). Scripts should use `status --json`, not parse `up`'s text |
| C7 | 3a | `UP_ARGS` is passed only by `make up` | Passed by every `up` and `restart` variant |
| C8 | 3a | `make build-plain` fails (undefined `$(CONTAINER_RUNTIME)`) | Works |
| C9 | 3a | `make check-prerequisites` runs `check-local-prereqs.sh --compose`, and `down`, `logs`, `ps` and `test-integration` depend on it | Runs `doctor --tag preflight`: the same checks and more. Every command that needs Docker runs it. Only the checks the script fails on today can stop a command; the new ones (Compose version, image store, ports) only warn, so they can't block `down` or `logs`. `SKIP_PREREQUISITES=1` still skips it |
| C10 | 2 | `config init` (`make init-env`) only fills blank secrets | Also reports keys in `.env.example` that `.env` lacks, and asks about the local SDK and local DeepLynx (Enter accepts the recommended answer) |
| C11 | 7 | Agent folders use their own Makefile logic and `.env` parsing | They use platformctl. Their `make` targets keep working |
| C12 | 3b | Starting the platform from a second folder with the same project name silently reuses the first folder's containers; any port clash fails with Compose's "port is already allocated" | `up` checks first and says what holds the port: the platform running from another folder (with its version), or another process (e.g. AirPlay on 5000), and the fix |
| C13 | 3b | Containers carry Compose's labels only | Platform containers also carry `io.prometheus.platform.root` and `.source` (not the network), from a generated `docker-compose.labels.yml`. The first `up` after step 3b recreates every container, because their config changed; volumes and data are kept. Later commits don't, since neither label changes with the version |
| C14 | 3b | `down -v` (`make down-v`) deletes every volume without asking | `down --volumes` asks you to type `clobber`, like `reset data`. `--yes`/`--confirm clobber` for scripts and CI; `make down-v` passes it, so CI is unaffected |
| C15 | 3a | `.env` values in quotes: Make reads `LOCAL_SDK="true"` as `"true"` with the quotes, so the setting is off | Quotes are stripped, as Compose does, so a quoted `LOCAL_SDK="true"` turns the setting on |
| C16 | 3b | | One more generated, git-ignored file in `platform/`: `docker-compose.labels.yml` |
| C17 | 3a | `make ps` exits 0 when nothing runs | `make ps` forwards to `status`, which exits 3 when the platform isn't running. The Make forward maps 3 to 0, so `make ps` still exits 0; `./platformctl status` exits 3 |

## Not breaking

- Every current `make` target name, its help text and the variables
  `SERVICE`, `PROFILE`, `CHECK`, `UP_ARGS`, `WAIT_TIMEOUT`, `CHECK_TIMEOUT`
  and the documented settings, including `make <target> KEY=value`
  overriding `.env`.
- Output that docs, slides or CI quote: `config init`'s messages (deck 03),
  the `clobber` confirmation word, "Cleared N agent registration key(s).",
  `cluster-up`'s "already running".
- The compose files' services, volumes, networks and their names; the agent
  compose files; `docker-compose.agents.yml`.
- `test-*`, `check-markings`, `react-*` and `cluster-*`.
- The `--json` output is versioned (`schema_version`); fields are only added
  within a version.
