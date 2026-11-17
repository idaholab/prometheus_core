# OSTI Research Agent — evaluation

How to check that a change to the agent makes its answers better, or at least
not worse. The harness itself (files, every command-line option, every metric)
is described in `evals/README.md`; this page is the procedure around it. The
design it tests is in `architecture.md`.

## What to evaluate with

| Level | What it checks | Needs | Time |
|---|---|---|---|
| unit tests (`tests/`) | code paths, with fake models and HTTP | nothing | seconds |
| golden parse corpus (`tests/test_goldens.py`, `-m slow`) | Docling parsing on real PDFs | fetched PDFs, model weights | minutes |
| one question (`python -m research_agent`) | one live run end to end | model credentials | 1–15 min |
| evaluation harness (`make osti-eval`) | answer quality over a question set | running stack | 1–15 min per question |

Run the unit tests on every change. Run the harness when a change could
affect what the agent finds, accepts or writes: prompts, tools, budgets,
verification rules, parsing, models.

```bash
# from agents/optional/osti-research-agent/
uv run --with pytest --with pytest-asyncio --with respx python -m pytest -q
```

The harness's own scoring and reporting code is covered by
`tests/test_eval_*.py` and `tests/test_cov_evals_*.py`.

## The question set

`evals/questions.yaml` holds 48 questions:

| Category | Count | Tests |
|---|---|---|
| `core` | 10 | DOE/nuclear materials questions answerable from OSTI |
| `scholarly` | 2 | the OpenAlex/arXiv path |
| `web` | 1 | the web-search path |
| `cache` | 3 | repeats of earlier questions, to test the knowledge base |
| `adversarial` | 10 | ambiguous, unanswerable, figure-only, conflicting sources, false premise, very broad |
| `uq` | 22 | uncertainty-quantification literature questions (fuel performance, thermal hydraulics, reactor physics) |

Each question can pin what a right answer is:

- `expect_status` — the status the run must end with (40 questions).
- `expected_facts` — short substrings the answer must contain (26).
- `expected_source_ids` — OSTI ids or DOI slugs that must be cited (4).
- `notes` — what a good answer contains, for the LLM judge. 31 questions have
  notes the judge grades; notes that only describe a question's purpose are
  not graded.

Where an honest "not found" would also be acceptable, `expect_status` is left
out on purpose.

## Scoring, in short

Each question gets two kinds of score (details in `evals/README.md`):

- **Code checks** (`evals/scoring.py`): status as expected, a completed answer
  cites sources, every `Paper N` is a link, expected facts and sources present.
- **LLM judge** (`evals/judge.py`, a model on the verifier route): groundedness,
  completeness and, when the notes allow, agreement with the notes, each 1–5.

A question passes only when every code check is met and every judge score it
got is 4 or more (`evals/report.py:failures`). An answer the judge could not
score counts as failed.

The judge's completeness scale rewards what the agent delivers: 5 for an
exact value at the asked conditions, 4 for a cited estimate, 3 for clearly
labelled nearest data, lower for less. So an honest, well-grounded answer
that only has nearest data still fails at 3. Read the judge's note before
treating such a failure as a regression.

## Running an evaluation

### 1. Start the stack with the agent

From `platform/`:

```bash
make up OPTIONAL_AGENTS=true
```

The harness runs inside the `osti-research-agent` container, which has the
model profile, credentials, Redis and Docling. The container runs the copy of
`evals/` and `research_agent/` baked into its image, so rebuild with the same
command after any change to the code, the prompts or `questions.yaml`.

### 2. Isolate the knowledge base

The knowledge base is shared by every user and every run, and it persists in
Valkey. Without isolation, an evaluation reads facts and cached answers left
by earlier runs, and its own runs add more, so two runs of the same code can
score differently. Run against an empty Valkey database instead:

```bash
make osti-eval OSTI_EVAL_ARGS="--redis-db-base 14"
```

The harness refuses a database that is not empty and never clears one, so
empty it yourself before the next run (Valkey has databases 0–15; the
platform uses 0):

```bash
docker exec prometheus_platform-redis-1 sh -c \
  'valkey-cli -a "$REDIS_PASSWORD" --no-auth-warning -n 14 FLUSHDB'
```

The Valkey container is named after the compose project; `docker ps` shows
it. Use `--no-redis` instead to run without memory or caches at all; the
`cache` questions then cannot pass.

### 3. Run a subset, then the full set

Each question runs one at a time and can take up to `TOTAL_BUDGET_S` (900 s),
so the full set takes hours. Narrow it first:

```bash
make osti-eval                                         # first 3 questions
make osti-eval OSTI_EVAL_ARGS="--id ss316-creep-400c --redis-db-base 14"
make osti-eval OSTI_EVAL_LIMIT= OSTI_EVAL_ARGS="--category adversarial --redis-db-base 14"
make osti-eval OSTI_EVAL_LIMIT= OSTI_EVAL_ARGS="--redis-db-base 14"   # all 48
```

`--id` and `--category` can be repeated. `OSTI_EVAL_LIMIT` takes the first N
questions after them.

The cache questions only make sense after the question they repeat:
`cache-repeat-ss316-creep` (14th) repeats `ss316-creep-400c` (1st),
`cache-repeat-triso` (15th) repeats `triso-safe-temperature` (2nd),
`uq-cache-repeat-htgr-kinf` (48th) repeats `uq-rp-htgr-kinf-nuclear-data`
(37th), and `adversarial-cache-figure-repeat` (19th) repeats
`adversarial-figure-only` (18th). Questions run in file order, so a filter
that drops the original makes the repeat a cold run.

### 4. Read the results

`make osti-eval` copies each run to
`evals/results/osti-eval-<timestamp>/` (ignored by git):

```
report.md                    summary, failures with reasons, every question, judge notes
report.json                  the same as data ("complete": false if the run stopped early)
out/deepagent/<qid>/
  result.json                the FinalResult: answer, findings, provenance, status,
                             plus _answer_drafts: each submitted answer, its outcome
                             and the grader's full gaps
  progress.log               every progress message, with seconds since the start
```

`make osti-eval-report` prints the latest report again. Ctrl+C stops a run
cleanly and still keeps the questions already done.

## Comparing a change against a baseline

1. **Fix the bar first.** Decide which questions must pass, and which metrics
   must not drop, before running the changed code (see "Acceptance bar" in
   `evals/README.md`).
2. **Baseline.** Build the current code, empty the evaluation database, run
   the chosen questions with `--redis-db-base`.
3. **Change.** Build the changed code, empty the database again, run the same
   questions with the same options.
4. **Compare** question by question. From the agent directory, with the two
   `report.json` paths:

   ```bash
   python3 - BASE/report.json NEW/report.json <<'EOF'
   import json, sys
   from evals.report import failures

   def load(path):
       return {r["id"]: r for r in json.load(open(path))["records"]}

   before, after = load(sys.argv[1]), load(sys.argv[2])
   for qid in sorted(before.keys() & after.keys()):
       was, now = not failures(before[qid]), not failures(after[qid])
       tag = "same" if was == now else ("FIXED" if now else "BROKE")
       print(f"{tag:5} {qid}: {'; '.join(failures(after[qid])) or 'pass'}")
   EOF
   ```

   Compare the summary medians too (`report.md`, "Summary").

5. **Rerun what changed.** Model output varies from run to run, and so do the
   search APIs, so a question that flips once may flip back. Run the flipped
   questions again on both builds before concluding anything; trust a change
   that holds on a repeat.
6. **Read transcripts.** Read at least five `result.json` /
   `progress.log` pairs end to end, including adversarial ones, and check the
   answer against the cited findings yourself. The judge is a model and can
   be wrong.

Cost and tokens are not in the report. Read them from LiteLLM's spend logs, or
from a LangSmith trace if tracing is on (below).

## Finding why a question failed

The failure reason in `report.md` says which check failed. To find which step
of the run caused it, read `progress.log` against the run flow in
`architecture.md`:

| `progress.log` shows | Step | Look at |
|---|---|---|
| `Found 0 papers in OSTI`, the same query repeated, only off-topic titles | search / rephrase | `prompts/orchestrator.md` (query strategy), the question's wording |
| `OpenAlex search failed: ... 429 Too Many Requests` partway through a full run | search | OpenAlex's keyless daily budget (about 50 searches) ran out: set `OPENALEX_API_KEY` ([`openalex-api-key.md`](openalex-api-key.md)) |
| downloads soon after `Checking knowledge base...`, with no search finding the papers | memory | the knowledge base was not isolated: use `--redis-db-base` |
| `Skipping <id>: ... not on the download allowlist`, `refused the download` | download | `DOWNLOAD_ALLOWED_DOMAINS`, `download_policy.py` |
| `Docling failed ... falling back to PyMuPDF text`, `Parsed ...: 0 table(s)` | parse | Docling memory and timeout settings (`runbook.md`); a table-only answer cannot be found from PyMuPDF text |
| `Paper <id> not used (analyzer): ...` | analyze | the reason given; `prompts/analyzer.md` |
| `Paper <id> not used (verifier): ...`, `Rejected unsupported finding` | verify | whether the paper really supports the candidate; `prompts/verifier.md` |
| `Verifier model-call limit reached`, `Verifier returned an invalid verdict` | verify | `VERIFIER_MODEL_CALL_LIMIT`; a status of `error` |
| `Findings are only nearest data; asking for a cited estimate` | estimate nudge | whether the findings had the inputs an estimate needs |
| `The grader asked for a revision: ...`, `Answer refused by the code check: ...` | answer | the gaps it lists; `prompts/orchestrator.md` (WRITING THE ANSWER) and `prompts/answer_grader.md` |
| an answer headed `## Evidence-grounded findings` | answer | no answer was accepted (graded twice and refused, a grader error, or none submitted), so the per-paper fallback was used; `_answer_drafts` in `result.json` has each draft and why it was refused |
| status `timeout_partial` | budget | `TOTAL_BUDGET_S`, slow parses, too many papers |

`result.json` has the verified `findings` (with `match`), `provenance`,
`papers_analyzed` and `facts_stored`, so you can tell an answer that found
nothing apart from one that found papers and rejected them.

To replay one question, run the harness on it alone; it resolves the same
model profile as the deployed agent:

```bash
make osti-eval OSTI_EVAL_ARGS="--id ss316-creep-400c --redis-db-base 14 --no-judge"
```

The agent's CLI (`python -m research_agent "<question>"`) is not a substitute
inside the container: it reads `AgentConfig.from_env()` without applying the
model profile, so its model calls go to `LITELLM_BASE_URL` or `REGISTRY_URL`
rather than the profile's endpoints. It is for a laptop with
`LITELLM_BASE_URL` pointing at a LiteLLM proxy.

### Tracing

To see every model call and tool call of a run, set `LANGCHAIN_TRACING_V2=true`
and `LANGCHAIN_API_KEY` in the agent's environment; the deepagents graph is
already instrumented. The agent's `docker-compose.yml` does not pass these
through, so add them to the `osti-research-agent` service in a
`docker-compose.override.yml` at the platform root (the Makefile includes it
automatically), then restart.

## Adding or changing questions

Add a question to `evals/questions.yaml`:

```yaml
  - id: zircaloy-breakaway-oxidation        # stable slug, used in reports
    question: "At what temperature does breakaway oxidation of Zircaloy-4 begin in steam?"
    category: core
    expected_facts: ["Zircaloy"]            # short, format-robust stems
    expect_status: completed                # only when coverage is confident
    notes: "Ref: ... what a good answer contains ..."
```

- Keep one ask per question, answerable from sources the agent can reach
  (OSTI records, OpenAlex, arXiv).
- Make `expected_facts` short stems that survive formatting ("650" matches
  both "IFA-650.10" and "IFA650.10").
- Leave `expect_status` out when an honest "not found" is also a right answer.
- Write `notes` as what a right answer contains ("Ref: ...", "expect ...",
  "a good answer ..."); only notes like that are graded.
- Pin `expected_source_ids` from a first run, once you know which sources the
  agent can reach, not before.

Rebuild the image afterwards: the container runs its own copy.

## Known limits of the evaluation

- **Results drift.** The search APIs and the shared knowledge base change, so
  an old report is not a reliable baseline. Run the baseline again next to
  each change.
- **Every reported run so far used the live knowledge base.** None of the
  reports under `evals/results/` has a `redis_db_base` set, so they read
  memory left by earlier runs.
- **Few sources are pinned.** Only 4 questions list `expected_source_ids`, so
  `source_hit_rate` says little; `fact_match` and the judge carry most of the
  signal.
- **The golden parse corpus is empty.** `scripts/download_goldens.py` has no
  ids yet, so `tests/test_goldens.py` always skips.
- **`cached` is never set.** `FinalResult.cached` is always false, so whether
  a cache question was answered from memory has to be read from its
  `progress.log` (`Checking knowledge base...` followed by downloads of the
  remembered papers, or none).
