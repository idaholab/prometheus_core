---
name: create-agent
description: Builds the user's Prometheus agent (an A2A service that the Prometheus chat routes to, not a Claude Code subagent) and teaches each step. It works out what is needed - set up a new agent from prometheus_core/agent-template that runs and is registered, add one platform feature (read an upload, publish a JSON table or a PNG, status updates, ask the user, approval, call an LLM, a structured answer, long-running work, a second skill, a workflow), or improve the agent card so that the orchestrator picks the right skill. Use for "create an agent", "new agent", "Day 1 hello agent", "start our team agent", "add a feature", "read the upload", "publish a plot", "call an LLM from my agent", "add a second skill", "review my card", "improve my skill description", or "my agent is never called".
argument-hint: "[what you want, e.g. an agent name, add a file upload, improve my card]"
allowed-tools:
  - Bash(docker compose -p prometheus_platform restart client-agent)
  - "Bash(docker compose -p prometheus_platform exec -T client-agent python -c \"import os, urllib.request as u; r=u.Request('http://localhost:8000/discovery/refresh', method='POST', headers={'Authorization':'Bearer '+os.environ['AGENT_SECRET']}); print(u.urlopen(r).read())\")"
---

# /create-agent

Build the user's agent, and teach each step at the level of the slides. The request: `$ARGUMENTS`

## Setup

1. `git rev-parse --show-toplevel` gives `<root>`. The KB is `<root>/.claude/skills/how/references/`
   (`<kb>`). Read `<kb>/conventions.md` and `<kb>/teaching.md`.
2. `cd "<root>/.." && pwd` gives `<parent>`. `<platform>` is `<parent>/prometheus_core/platform`, and
   `<template>` is `<parent>/prometheus_core/agent-template`. Check them:
   `test -f <platform>/docker-compose.yml && echo platform-ok; test -f <template>/setup_agent.py && echo template-ok`.
   When one is missing, list `ls -d ~/*/prometheus_core` and ask once (header `Platform`).
3. Read the ports, names only:
   `grep -E '^(BACKEND_PORT|FRONTEND_DEV_PORT|FRONTEND_PROD_PORT)=' <platform>/.env`.
   The backend (`BACKEND_PORT`, default 8600) is the agent registry: `/v1/agents` with
   `Authorization: Bearer $AGENT_SECRET`.
   The task files show the default ports; use the values that you read.

## Rules

- Obey `conventions.md` (folders, ports, secrets, "Before a write", the fixes, `AskUserQuestion`)
  and `teaching.md` (a 2-3 line primer with the deck and slide before each decision, the check
  questions by id, an offer of `/how explain <concept>` after a key concept). After "skip the
  quiz", ask no check question and no prediction.
- Never print or ask for a secret. The pin, the `LLM_CONFIG_PROFILE` value, and the ports are not
  secrets.
- Write the plumbing. Leave the domain logic as `# TODO:` hints, unless the user says yes.
- Explain each change in one or two lines.
- Add a dependency with `uv add <pkg>` in the agent folder and commit `uv.lock` with
  `pyproject.toml`; the image build fails without a current `uv.lock`.
- Late inputs arrive merged into `params`; there is no `get_provided_inputs`.
- Never edit the platform or the template. Read files outside `<root>` with `sed -n`, `grep -n`,
  `ls`. The Read and Edit tools ask for permission in `<parent>/hello-*/`; tell the user to allow
  them.

## Decide what to do

Pick the task from the request and the state. Ask only when two tasks are equally likely. First
find the user's agent ("Find your agent" in `conventions.md`).

| when | file |
|---|---|
| no agent yet; a new, Day 1, or team agent; or the request is only a name | `new-agent.md` |
| a feature: upload, table, PNG or plot, status lines, a form, approval, an LLM call, a structured answer, long work, a second skill, a workflow | `add-feature.md` |
| the card, a description, `usage_notes`, the inputs; "never called"; "wrong arguments" | `improve-card.md` |

With an agent and no clear request: when the card holds template text (`TEMPLATE_`, "When to use
this skill vs. other available skills.", "The main input data to process."), improve the card.
Else ask (header `Next`): "Add a feature (Recommended)", "Improve the card", "Start another agent".

Obey that file in this folder. "The argument" there is the request. Go on to the next file when
the user wants more.
