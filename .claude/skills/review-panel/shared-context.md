> Repo: `prometheus_core`, a multi-agent "Prometheus" platform run with Docker Compose. Its
> parts: `platform/frontend/` (React + Vite + TypeScript), `platform/backend/` (FastAPI, which owns
> the JSON/SSE wire contract in `backend/app/contract.py` and `backend/CONTRACT.md`),
> `platform/agents/` (the `client-agent` orchestrator and the specialist agents, all A2A services),
> `sdk/` (the `prometheus_api` package: the `PrometheusAgent` base class, the LLM client, the
> storage client, and the backend ↔ client-agent contract), `agent-template/` (scaffolds an agent
> with `setup_agent.py`), and `hackathon/` (slides, Claude Code skills, and a knowledge base for an
> event). `platform/CLAUDE.md` describes the architecture and the request flow. The CI checks
> are in `.github/workflows/test.yml`.
>
> You are reviewing: **<summary>**. The change is `<diff command>` (<n> files), at head commit
> `<sha>`. <PR body or commit messages, if any.> <"Merged into devel; fixes would go in a
> follow-up PR", if so.> <Background files, if any, such as a plan this step belongs to. They
> are context, not the thing under review.>
>
> CI on `<sha>`: <each job as passed / failed / pending / not run, with its link; or "no CI run
> for this commit">. Don't run a suite again locally if it passed here; say "passed in CI" and
> link it. For a failed job, read its log (`gh run view <run> --log-failed`) instead of rerunning
> it. Run things locally only for what CI doesn't cover, or to test a finding.
>
> The code: <one of the following>
> - "It's checked out at `<path>`. Run things there."
> - "It isn't checked out. The files in the current directory may be older than the change, so
>   read the reviewed version with `git show <sha>:<path>`. To run something, export it with
>   `git archive <sha> | tar -x -C "$TMPDIR/<you>"`. The export has no `.git`, so put checks
>   that need git under Not covered, and don't report them as findings."
>
> Stay on your brief. You are one of several reviewers running in parallel, each with its own
> perspective, and the others cover what your brief leaves out. What you add to the panel is
> depth on your own questions, so spend your time and your word budget there. When you notice
> something outside your brief, follow it only if it bears on one of your questions (for
> example, a security reviewer tracing a token into a log line, or a user reviewer hitting a
> crash while walking through setup). Otherwise don't investigate it. If it looks serious, name
> it in one line under "Outside my focus" and go back to your brief. An off-brief finding
> usually repeats another reviewer's, and it costs the time you didn't spend on your own
> questions.
>
> Rules: don't modify tracked files. Never print secrets: never `cat` a `.env`, never run `env`,
> `printenv`, `docker compose config` or `docker inspect` on a real stack, and read `.env.example`
> instead. Start containers only in a throwaway project with your own project name and ports
> (`COMPOSE_PROJECT_NAME=review-<you>`), and remove them when you are done. Write temp files
> only under `$TMPDIR`. Check a claim by running it when you can. A finding you ran is worth more
> than a finding you only read.
>
> Return your findings as text, in this shape, at most ~700 words. Don't write files, and don't
> add other sections.
>
> ```
> Ran: <the commands and suites you ran, or "read only">
> Top 3: <one line each>
>
> | Severity | Finding | Where | Fix | How you know |
> (blocker / major / minor; one or two sentences; file:line; a concrete fix; "ran <command>" or "read")
>
> Works well: <at most 3 short items>
> Not covered: <checks you couldn't run, and why>
> Outside my focus: <at most 2 one-line notes on things you saw but didn't investigate, or "none">
> ```
