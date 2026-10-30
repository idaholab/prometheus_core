# Hackathon knowledge base: start here

Facts as of `prometheus_core` `devel` 2026-10-30, after #310 (`prometheus_api` 0.15, no LiteLLM). When the code disagrees with this file, the code is correct.

The KB distills the five Day 1 decks (01 Welcome, 02 GitHub & PRs, 03 Local platform, 04 Building an agent, 05
Dry run) against the code. `deck 04, slide 7` is the main part, `deck 04, A42` the appendix.

Placeholders: `<root>` this repository; `<platform>`, `<template>` the clones next to it; `<agent>` your
agent folder; `<you>` your GitHub login; `<slug>` your agent's kebab name (container `<slug>-agent`);
`<route key>` the card name, lowercase, spaces to hyphens; `<pin>` the `prometheus_api` commit (`environment.md`).

## Topic → file

| topic | file |
|---|---|
| The services, the ports, one chat turn, how a turn ends, the chat commands, the reference agents | `platform.md` |
| A word you do not know: skill, card, artifact, flavor, route key, `contextId` | `glossary.md` |
| The Day 1 flow: scaffold, edit, run, route, the practice PR | `day1.md` |
| The card fields, what the LLM sees, the rules, the naming rules | `card.md` |
| `_execute`, params, the result dict, errors, the helpers, the template files | `agent-code.md` |
| Uploads, tables, PNGs, DeepLynx, the viewers | `artifacts.md` |
| Ask the user (input-required), approval, context state, form fields | `asking-the-user.md` |
| Long or blocking work, `PrometheusWorker`, background tasks | `long-running.md` |
| `LLMClient`, flavors, profiles, keys, structured answers, `LLMAliasError` | `llm.md` |
| A workflow that chains skills | `workflows.md` |
| Tests, a mocked LLM, the SDK on the host | `testing.md` |
| `make up`, registration, discovery, the run modes, a test call | `run-and-register.md` |
| The `.env` values, the base image and the pin, the registry login, the first login | `environment.md` |
| One check per line: command, expected result, fix | `checks.md` |
| A symptom and its fix | `troubleshooting.md` |
| What old docs and slides say, and what the code does now | `stale-docs.md` |
| Fork, branch, rebase, the PR; who to ask | `git-pr.md`, `mentors.md` |
| How the skills teach and ask; the rules of every skill | `teaching.md`, `conventions.md` |
