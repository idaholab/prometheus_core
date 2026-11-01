# Build and Run Specs Index

This folder is the spec-driven-development contract for how the Prometheus
platform is built, versioned, released and run, across `sdk/`, `platform/`,
`agent-template/`, `infrastructure/` and `.github/workflows/`. Specs describe
what a user of the platform, an agent developer or a script can rely on.
How the code is organised stays in each project's README.

Specs follow [SDD_SPEC_AUTHORING.md](../../sdk/docs/SDD_SPEC_AUTHORING.md),
including the `tests:` line and the `(planned: <step>)` marker, and
[SDD_TESTING_STANDARD.md](../../sdk/docs/SDD_TESTING_STANDARD.md). The
library's own behaviour stays in [`sdk/specs/`](../../sdk/specs/000-index.md).

## Areas

Each area has a block of numbers, so it can grow without renumbering.

| Range | Area | What it covers | Status |
| --- | --- | --- | --- |
| 001–099 | Running the platform | `./platformctl` and the `make` targets that forward to it: setup, settings, secrets, lifecycle, your agents, `doctor`, compatibility, targets | Requirements for step 1, drafts for steps 2 to 9 |
| 100–199 | Images | How each Dockerfile builds; the `prometheus_api` base image and the agents built FROM it; CA certificates; the build cache; amd64 and arm64 | Not started |
| 200–299 | Versions and pins | The base-image hash pin; pinned images in compose files and Dockerfiles; how the platform version is formed; what Dependabot updates | Not started |
| 300–399 | Release and publishing | What `publish.yml` publishes, its tag format and when it runs; release images | Not started |

When the Images area is written, `sdk/specs/013` REQ-013-12 and REQ-013-13
(the SDK image build) move there and are retired in 013.

## Specs

| NNN | Name | Status | Summary |
| --- | --- | --- | --- |
| 001 | [Using the CLI](001-using-the-cli.md) | draft | Starting `./platformctl`, global options, help, exit codes, output, `--json`, use without a terminal |
| 002 | [Settings and setup](002-settings-and-setup.md) | draft | Where each setting comes from; `config init`, `set`, `show`; `deeplynx setup`; writing `.env` |
| 003 | [Secrets](003-secrets.md) | draft | No secret value is ever shown, by any route |
| 004 | [Running the platform](004-running-the-platform.md) | draft | `up`, `down`, `restart`, `build`, `logs`, `status`, the reset ladder, running elsewhere and ports |
| 005 | [Your agents](005-your-agents.md) | draft | Agents stay registered through restarts; the `agents` commands; agent folders in any repository |
| 006 | [Doctor](006-doctor.md) | draft | Diagnosing the laptop, the platform and an agent folder, without changing anything |
| 007 | [Compatibility](007-compatibility.md) | draft | `make` targets, old scripts, running `docker compose` yourself, generated files, quoted messages |
| 008 | [Where and how the platform runs](008-where-and-how-the-platform-runs.md) | draft | Deployment targets (k3d) and running from pre-built images |

## Interface ownership

Each command, option and file is claimed by exactly one spec.

- `platform/platformctl`, global options, `--help`, `--version`, exit codes,
  the `--json` envelope and its error codes: 001.
- Settings and their precedence, `config init|set|show`, `deeplynx setup`,
  `.env`: 002.
- Hiding secret values everywhere, the `--set` refusal, the `compose --`
  notice: 003.
- `up`, `down`, `restart`, `build`, `logs`, `status`, `reset ...`: 004.
- Restarting your agents, `agents ...`, `--agent` on lifecycle commands,
  `config sync`, `config init --instance`, the agent-template stub: 005.
- `doctor`, check ids, failure hints: 006.
- `make` targets and variables, the `scripts/*` stubs, `compose --print`,
  `compose --`, generated file names: 007.
- `--target`, `PLATFORM_TARGET`, `cluster ...`, `PLATFORM_SOURCE`,
  `PLATFORM_IMAGE_*`: 008.

## Plan steps and specs

The platformctl plan is in
[`platform/plans/platformctl/`](../../platform/plans/platformctl/README.md).
A requirement that a later step delivers carries `(planned: step N)`. That
step's PR removes the marker and cites the ID from its tests.

Each step's plan file has a Requirements section listing its IDs.
`python3 common/speccheck/speccheck.py --specs build/specs --report` shows
each ID's state.

| Step | Specs it delivers requirements for |
| --- | --- |
| 1 (done, #316) | 001, 002, 003, 006, 008 |
| 2 | 001, 002, 003, 004 (`status --wait`), 007 |
| 3a | 001, 002, 003, 004, 005 (`agents generate`, `clean`), 006, 007 |
| 3b | 004, 005, 006, 007 |
| 3c | 003, 004, 005, 007 |
| 4 | 001, 006 |
| 5, 6 | 007 (docs) |
| 7 | 005, 006 |
| 8, 9 | 008 |

The requirements for steps 2 to 9 are drafts, written from the plan before
the work. A step's PR may change them, and should add what it finds
missing.

## Evidence

[`common/speccheck`](../../common/speccheck/README.md) checks this folder:
every requirement is cited by a test or a CI job, marked `⚠ untested`, or
marked planned. For 001–099, a CI job counts as evidence only for what a
unit test can't show, such as a real Compose version, a real runner or the
merged compose config; platformctl's 100% unit coverage rule still applies.
