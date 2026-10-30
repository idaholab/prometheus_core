# Mentors and help

Facts as of `prometheus_core` `devel` 2026-10-30, after #310 (`prometheus_api` 0.15, no LiteLLM). When the code disagrees with this file, the code is correct.

## Topic → mentor

From deck 01, slide 4. Ask early (deck 02, slide 17). When you are not sure, ask any mentor in the room.

| your problem is about | ask |
|---|---|
| The stack, Docker, the backend, the UI, login, signing keys, the orchestrator, discovery | Daniel Schwen, Brandon Biggs |
| `PrometheusAgent`, `_execute`, helpers, input-required, long work, registration | Daniel Schwen |
| `LLMClient`, flavors, profiles, LLM keys, `LLMAliasError` | Brandon Biggs |
| DeepLynx, uploads, a plot that does not render | Isaac Huffman |
| The card, skill design, workflows, tests, the Day 1 and Day 2 agents | Mengnan Li, Mauricio Tano, Zach Prince |
| Git, the PR, your team | Chris Rubel |
| Access to `github.inl.gov/genesis` (team `open`), the PAT, the registry login | Any mentor, now |

Chat: Teams. Bugs: JIRA `PPLT`. Read the SDK docs in your `prometheus_core` clone (`sdk/docs/agent/GUIDE.md`), not the docs site.
Say what you ran, expected, and got, with the error line. Never paste a key or an `.env`.
