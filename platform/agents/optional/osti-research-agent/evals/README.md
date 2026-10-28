# Evaluation harness

Runs the OSTI research agent over a fixed question set and scores the
answers, so a change to answer quality is visible before it ships.

## Layout

| File | What |
|------|------|
| `questions.yaml` | 51 questions (core / scholarly / web / cache / adversarial) with optional expectations |
| `run.py` | runs each question through the agent, writes transcripts, scores |
| `scoring.py` | pure, offline metrics (unit-tested in `tests/test_eval_scoring.py`) |
| `report.py` | terminal summary and Markdown report (unit-tested in `tests/test_eval_report.py`) |
| `judge.py`, `judge_prompt.md` | LLM judge: groundedness, completeness, reference agreement (`tests/test_eval_judge.py`) |
| `progress.py` | the progress bar |
| `__main__.py` | the `python -m evals {run,report}` CLI |

## Running

The evaluation runs inside the agent's container, which already has the
agent's model profile, credentials, Redis and Docling. From `platform/`:

```
make up OPTIONAL_AGENTS=true          # once: start the stack with the OSTI agent
make osti-eval                        # default: deepagent, first 3 questions
make osti-eval OSTI_EVAL_LIMIT=10     # first 10 questions
make osti-eval OSTI_EVAL_LIMIT=       # every question (51; takes hours)
make osti-eval OSTI_EVAL_LIMIT= OSTI_EVAL_ARGS="--category uq"
make osti-eval OSTI_EVAL_ARGS="--redis-db-base 14"   # isolate from the live cache
make osti-eval-report                 # re-print the latest report
```

| Variable | Default | Use |
|----------|---------|-----|
| `OSTI_EVAL_LIMIT` | `3` | how many questions to run; empty runs every selected question |
| `OSTI_EVAL_ENGINES` | `deepagent` | engines to run; `deepagent` is the only one |
| `OSTI_EVAL_ARGS` | (none) | any other `python -m evals run` options (table below) |

The limit applies after `--id`/`--category`: `OSTI_EVAL_LIMIT=5
OSTI_EVAL_ARGS="--category uq"` runs the first 5 UQ questions. Any of the
variables can also be set in the environment (`export OSTI_EVAL_LIMIT=10`).

While it runs, a progress bar on the terminal shows questions done, percent,
the current engine and question, elapsed time, an ETA (from the average time
of the questions so far), time on the current question, and the agent's live
status ("Parsing paper..."). Each finished question prints one line above it:
pass/FAIL, status, time, judge scores, and the failure reasons. Off a terminal
(CI, `| tee`), it prints plain lines instead.

`make osti-eval` prints a summary when it finishes (per-engine pass counts,
medians including the judge scores, p90 time, and each failing question with
the reason) and copies the
results to `evals/results/osti-eval-<timestamp>/` on the host:
`report.md` (summary, failures, every question, links to transcripts),
`report.json`, and `out/{engine}/{qid}/` with each `result.json` and
`progress.log`. The report is rewritten after every question, so a run that
stops early still leaves a partial report (`"complete": false`).
Press Ctrl+C to stop a run: it finishes cleanly (exit code 130), prints the
summary of the questions already done, and `make osti-eval` still copies the
partial results back.

`OSTI_EVAL_ARGS` takes any other `python -m evals run` option. (Run
directly, `python -m evals run` takes `--limit` too; its own default is no
limit.)

| Option | Use |
|--------|-----|
| `--id <qid>` | only this question; repeatable |
| `--category <name>` | only this category (`core`, `uq`, `adversarial`, ...); repeatable |
| `--redis-db-base N` | run against Redis database N instead of the live one, so cached answers from earlier runs can't leak in; refuses a non-empty database and never clears Redis |
| `--no-redis` | run without Redis (the `cache` questions cannot hit the cache) |
| `--no-judge` | skip the LLM judge (no judge scores, one fewer model call per question) |
| `--questions <path>` | another question file |

Each question can take up to `TOTAL_BUDGET_S` (900 s by default) and they run
one at a time, so the full 51-question set takes hours. Start
with a filter. Rebuild the image after editing `questions.yaml` or anything
under `evals/` (`make up OPTIONAL_AGENTS=true`): the container runs the copy
baked into it.

For LangSmith traces, set `LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY` in
the agent's environment first — the deep engine's `astream` is already
instrumented.

## Scoring

Three layers — the first two run automatically:

1. **Offline metrics (`scoring.py`, automatic).** Per question:
   - `status_match` — status equals `expect_status` (when the spec pins one).
   - `provenance_ok` — a `completed` answer cites at least one source
     (`no_results`/`error`/`timeout` are exempt).
   - `citation_link_rate` — fraction of `Paper N` mentions that are real
     markdown links, not bare text.
   - `source_hit_rate` — fraction of `expected_source_ids` found in the
     provenance (when the spec lists any).
   - `fact_match` — fraction of `expected_facts` substrings present in the
     answer (when the spec lists any).
   - `wall_s` — wall-clock latency (measured directly by `run.py`).
   `aggregate()` rolls these into medians, a p90 latency, and pass counts.

   **Cost/tokens are not in `FinalResult`** and so aren't scored here — read
   them per run from LiteLLM's spend logs (or the LangSmith trace) and compare
   against the cost bar below by hand.

2. **LLM judge (`judge.py`, automatic; `--no-judge` to skip).** After each
   question, a model on the **verifier** route reads the question, the answer,
   the verified findings and the question's reviewer notes
   (`judge_prompt.md`), and scores 1–5:
   - `judge_groundedness` — every claim is supported by the findings.
   - `judge_completeness` — the question is fully addressed, or the answer
     says plainly what the sources don't report.
   - `judge_reference_agreement` — agreement with the reviewer notes: the
     "Ref:" literature-review values of the UQ block, or the expected behavior
     of the adversarial questions. Scored only when the notes say what a
     right answer is (35 of the 51 questions); notes that only describe a
     question's purpose ("exercises the arXiv path") are not graded. The
     `Access:` tag is never sent.

   A question needs 4 or more on every score it got to pass. The judge's
   one-line rationale is in `report.md` under "Judge notes". If the judge
   fails or replies badly, the question is marked `judge_error` and left
   unjudged; the run continues. One extra model call per question.

3. **Manual spot-check (manual, separate).** A model judge can be wrong, so
   still read 5 transcripts end-to-end —
   include the adversarial ones (`unobtainium-42` should be `no_results`; "Is it
   safe?" should ask to disambiguate, not fabricate) — and confirm the answer
   matches the cited sources.

## Acceptance bar

Before relying on a change, the agent should, over this set:

- have `provenance_ok` on every `completed` answer and ≥ 90% citation-link
  correctness (`median_citation_link_rate`),
- handle all 5 adversarial questions correctly (no fabricated citations; the
  no-answer question returns `no_results`; the figure-only question is
  answered),
- not drop on median `source_hit_rate`, `fact_match`, or the judge's
  groundedness and completeness versus the previous run, and
- keep `p90_wall_s` ≤ 15 min.

Set the bar before running, not after. Cost isn't in the report; read it from
the LLM provider's spend logs.
