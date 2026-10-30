---
name: how
description: Answers a "how do I", "why", or "what is" question about building a Prometheus agent for the hackathon, at the level of the slides, from the shared knowledge base first, then the real code and docs at the platform pin, then the mentor. When a concept needs a picture, it makes a fact-checked, slide-styled HTML page with diagrams and opens it in the browser. Use for "/how <question>", "how do I ...", "why does my agent ...", "what is a skill / card / artifact / flavor", "where is X in the code", questions about the platform, the template, prometheus_api, git and PRs, or the Day 1 flow; and for "explain X visually", "draw how X works", "make a page about X", or "I don't get X".
argument-hint: "[question, or a concept to explain]"
---

# /how

The request: `$ARGUMENTS`

## Setup

1. Run `git rev-parse --show-toplevel` to get `<root>` (not `${CLAUDE_PROJECT_DIR}`). The KB is
   `<root>/.claude/skills/how/references/`; a KB file name below means a file there.
2. Read `conventions.md` and `teaching.md` once per session, and obey them.
3. `<platform>` is `<root>/../prometheus_core/platform`, `<template>` is
   `<root>/../prometheus_core/agent-template`. Check each with `test -d <path> && echo ok`. When one is
   missing and the request needs it, ask once for its path (header `Folder`).
4. For a request about the user's own agent, find it by "Find your agent" in `conventions.md`,
   and note `<project>` and `<service>` ("Find your agent"). No agent
   is fine.

## Rules

- Never print or ask for a secret. Read the platform and the template with read-only Bash.
- Cite only the KB, the slides (`deck 04, slide 6`, `deck 04, A16`, never a PDF page), and the
  code (`path:line`). When the code disagrees with a doc, the code is correct. Say so.

## Decide what to do

- A question (how, why, what, where): obey `answer.md` in this folder.
- A request to explain, draw, or show a concept, for a page or a diagram, or "I don't get X":
  obey `explain-page.md`. After an answer on a visual topic, offer the page.
