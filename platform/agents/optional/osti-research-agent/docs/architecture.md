# OSTI Research Agent — architecture

How the OSTI research agent is currently structured. For the platform it
plugs into (backend agent registry, Valkey, A2A), see the repo-root `CLAUDE.md`.
For how to evaluate a change, see `evaluation.md`.

## The boundary contract

The code is split into a **transport-agnostic core** and a **thin A2A shell**:

```
a2a layer (agent.py)                 <- the ONLY file that may import prometheus_api / a2a
  └─ ResearchRunner.run(question)    <- core/runner.py: the event-stream boundary
       yields AgentEvent = ProgressEvent | FinalResult   (core/events.py)
         └─ core/deep_runner.run_deep   the deep-agent engine
```

- **`research_agent/**` imports nothing from `prometheus_api` or `a2a`.** This is
  enforced by `tests/test_import_boundary.py` (a regex over the whole package).
  The core runs on a laptop with only LLM credentials — see `cli.py`
  (`python -m research_agent "<question>" --no-redis`).
- **`ResearchRunner`** is the single seam every transport goes through. It runs
  the engine, bridges its progress to an
  `AsyncIterator[AgentEvent]`, and enforces the outer time budget
  (`total_budget_s - 30`), salvaging a `timeout_partial` `FinalResult` from
  whatever findings accumulated if the budget fires.
- **`FinalResult`** (`core/events.py`) is the wire payload. `core/adapter.py`
  serializes it to the exact JSON key set `agent.py` produced pre-refactor
  (`test_adapter.py` golden-checks this), so the frontend contract is unchanged.
- **Model routing** resolves `LLMConfig.from_env()` and uses the selected
  profile's endpoints and keys as-is. Deep Agents receives a provider-neutral
  `ChatLiteLLM` model for OpenAI-compatible and Anthropic profiles, including
  tool binding. No model temperature
  is forced by the agent; deployed profiles control supported parameters.

## Design structure

One question is one run. An LLM orchestrator decides which tool to call next;
there is no fixed pipeline order, only the strategy in
`prompts/orchestrator.md`. Code in the tools enforces budgets and checks, and
two independent LLM reviews (a per-paper verifier and an answer grader) decide
what may reach the answer.

### Components

| Component | Kind | Built in | Model route | Can use |
|---|---|---|---|---|
| orchestrator | deepagents graph | `core/deep_agent.build_research_agent` | `orchestrator` | the agent's tools (`tools/`) plus deepagents' filesystem tools |
| paper analyzer | deepagents graph, called from `analyze_paper` | `core/deep_agent.build_analyze_paper_tool` | `analyzer` | read-only `/papers/**` |
| paper verifier | deepagents graph, called from `analyze_paper` | `core/deep_agent.build_paper_verifier` | `verifier` | read-only `/papers/**` |
| synthesizer | `langchain` agent, no tools | `core/synthesis._build_synthesizer` | `orchestrator` | nothing |
| answer grader | `RubricMiddleware` on the synthesizer | `core/synthesis._build_synthesizer` | `verifier` | `read_verified_findings` |
| follow-up suggester | one completion | `llm_steps.suggest_followup_from_findings` | `complete` passed in by `agent.py` | nothing |
| figure VLM (off by default) | one completion per figure | `parsing/figures.py` | `vlm` | the figure image |
| Docling worker | subprocess, no LLM | `parsing/docling_worker.py` | - | the PDF |

Every role uses the `medium` flavor unless a model profile maps it elsewhere
(`core/config.py`, `core/model_profile.py`).

**The analyzer and verifier are not deepagents subagents.** The orchestrator
has no `task` tool (`_register_runtime_profiles` turns off the general-purpose
subagent, and `tests/test_deep_agent.py` checks `"task"` is absent). Both are
separate graphs held inside the `analyze_paper` tool, which Python code runs
as analyzer → check → verifier → validate. So the orchestrator cannot write
the analyzer's task, skip the verifier, or see an unverified candidate; it
gets back only a verified Finding or a reason the paper was not used.
`build_paper_analyzer` still returns a dict in the deepagents subagent-spec
shape, but its `name` and `description` are not used.

### Run flow

```
A2A request (question)
   │
agent.py ─► ResearchRunner             outer deadline TOTAL_BUDGET_S - 30 s
   │                                    fires → cancel, return timeout_partial
   ▼
run_deep: the orchestrator picks the next tool each turn
┌──────────────────────────────────────────────────────────────────────────────┐
│  1 memory     search_knowledge_base → cached_answer + facts (hints only)     │
│  2 search     search_osti / search_scholarly / search_web → ctx.search_hits  │
│                 code refuses duplicate and over-limit queries                │
│  3 rephrase   the orchestrator rewrites its query when hits are off-topic or │
│               analyze_paper reports what a paper covers instead (prompt only)│
│  4 triage     the orchestrator reads titles + abstracts, picks ≤ 5 papers    │
│  5 download   download_paper   code: URL came from a search, host allowlisted│
│  6 parse      parse_paper      Docling → /papers/<id>/ (no LLM)              │
│  7 analyze    analyze_paper    analyzer → check → verifier → validate        │
│  8 weaker     record_abstract_evidence, record_estimate (checked in code)    │
│  9 store      store_facts      only for sources with a verified finding      │
│ 10 end        final message {"findings": [...]} (content ignored)            │
└──────────────────────────────────────────────────────────────────────────────┘
   │
nudges (core/deep_runner.py, at most 2 extra rounds)
   no findings, budget left, unread hits → "download and analyze these"
   every finding only `nearest`          → "try record_estimate" (once)
   │
build_final_result
   synthesizer + grader → linkify → abstract/estimate sections → follow-ups
   → cache the verified part in the knowledge base (status completed only)
   │
FinalResult → agent.py → result JSON, searched_papers.md, citation cards
```

### Inside `analyze_paper`

```
analyze_paper(source_id, question)
 ├─ check (code): non-empty ids, DOI ↔ OSTI-id alias, paper parsed,
 │     directory under /papers/
 │     not parsed → {terminal: false, required_action: download + parse}
 ├─ per-source lock and result cache: each paper is analyzed once per run
 ├─ analyzer   reads meta.json, headings, sections, tables, figure JSON
 │     → candidate Finding (match exact | nearest) or answered: false
 ├─ check (code): JSON, Finding schema, same source_id as asked
 │     answered: false → ctx.unused_papers (by analyzer)
 ├─ verifier   rereads paper.md and the cited tables; treats the candidate as
 │     untrusted → supported | corrected | rejected
 ├─ validate (code): known verdict, source_id unchanged, answer and evidence
 │     present; every cited file is in this paper's directory, exists, and
 │     was read by the verifier (read_file, or grep in content mode);
 │     paper.md read and cited
 │     rejected → ctx.unused_papers (by verifier)
 │     analyzer, verifier or path failure → ctx.verification_errors
 └─ supported | corrected → ctx.findings, the only evidence the answer uses
```

### Answer and status

```
ctx.findings → synthesizer (cites "Paper N", ≤ 3000 chars asked)
            → grader (7 rubric criteria, one revision allowed)
            → code: grader satisfied, ≤ MAX_ANSWER_CHARS, every Paper N in range
              yes → synthesized answer
              no, or timeout → findings rendered per paper
```

| Status | When |
|---|---|
| `completed` | at least one verified finding |
| `no_results` | nothing verified, and no `verification_errors` |
| `error` | nothing verified and at least one `verification_errors` entry (an analyzer, verifier or source-path failure), or the final message was not JSON |
| `timeout_partial` | the runner's outer deadline fired |

### Where each kind of check happens

| Check | By | Where |
|---|---|---|
| search limits, duplicate queries | code | `RunContext.reserve_search` |
| paper and time budget (refuse with < 90 s left) | code | `RunContext.budget_reason`, called by download/parse |
| download URL came from a search, host allowlisted | code | `tools/osti.download_paper`, `download_policy.py` |
| paper relevance | orchestrator | its reading of titles and abstracts |
| candidate answers the question from the paper | analyzer | `prompts/analyzer.md` |
| candidate is supported by the paper | verifier | `prompts/verifier.md` |
| verifier output well formed, cites files it read | code | `_validated_finding`, `_validated_artifacts` |
| abstract quote verbatim, numbers in the quote | code | `tools/evidence.record_abstract_evidence` |
| estimate inputs cited, formula evaluated safely | code | `tools/evidence.check_estimate` |
| fact source has a verified finding | code | `tools/memory.store_facts` |
| answer follows the findings | grader | `prompts/synthesis_rubric.md` |
| answer length and `Paper N` range | code | `synthesis.citations_valid`, `MAX_ANSWER_CHARS` |

### Search hits and ranking

The agent does not score search results. Each API ranks its own results and
the tools keep them in that order:

- **OSTI** (`osti_client.search_osti`): the API's keyword ranking; records
  without an abstract are dropped; at most 8 per search.
- **Scholarly** (`scholarly.search_scholarly`): OpenAlex then arXiv, no
  re-ranking; deduplicated by DOI, or by normalized title; at most 6.
- **Web**: the provider's order.

A source already in `ctx.search_hits` is not returned again, so a reworded
query shows the orchestrator only papers it has not seen. Relevance is the
orchestrator's judgment from the title and the first 600 characters of the
abstract.

The knowledge base is the only place that computes a score
(`knowledge.RedisKnowledgeStore`), by cosine similarity of embeddings:

- **facts**: score ≥ 0.15, top 8; the score is not passed to the orchestrator.
- **cached answer**: exact `md5(question.lower())` key, else the closest cached
  question with cosine ≥ 0.95.

Both scan at most the first 1000 keys `SCAN` returns.

### Run state

`RunContext` (`tools/context.py`) holds one run's state, shared by the tools,
`analyze_paper` and the runner:

- inputs: config, question, `complete`, Redis caches, knowledge store,
  `run_workdir`, deadline
- search: `search_hits`, `search_queries`
- papers: `pdf_paths`, `download_failures`, `refused_hosts`, `parsed_papers`,
  `parse_failures`, `papers_attempted`
- analysis: `paper_analysis_results`, `paper_analysis_locks`,
  `invalid_paper_analysis_results`, `findings`, `unused_papers`,
  `verification_errors`
- weaker evidence and memory: `abstract_evidence`, `estimates`, `facts_stored`

`ResearchRunner` shares the `findings` and `search_hits` lists with the run, so
it can build `timeout_partial` from them after cancelling. Parsed papers live
under `run_workdir/papers/` and are deleted when the run ends; PDFs, parsed
paper directories, facts and cached answers persist in Redis (see
`runbook.md`).

### Known gaps

- **The orchestrator can change parsed papers.** `create_deep_agent` gives it
  deepagents' filesystem tools (`ls`, `read_file`, `write_file`, `edit_file`,
  `delete`, `glob`, `grep`, `execute`) on the same backend as the analyzer and
  verifier, without `permissions=`. `write_file` and `edit_file` work on the
  real files under `/papers/`, so a changed `paper.md` would be what the
  verifier checks against. Only the prompt ("NEVER read `paper.md` yourself")
  keeps it out. `execute` returns an error, because the backend has no
  sandbox. A read-only or deny rule for `/papers/**` on the orchestrator would
  close this.
- **No planning tool.** The graph has no `write_todos`, so the `todo_update`
  events `deep_runner.translate_update` handles never occur.
- **Rephrasing is prompt-driven.** No code tries an alternate query; the
  duplicate-query refusal and the nudges only push the orchestrator to.
- **Knowledge-base scans stop at 1000 keys,** in arbitrary `SCAN` order, so
  past that size some facts and cached answers are never compared.

## The engine

`core/deep_runner.py` runs a `deepagents.create_deep_agent` orchestrator
(LangGraph under the hood) whose `analyze_paper` tool holds the analyzer and
verifier graphs. The tool first analyzes one parsed paper, then independently
verifies the candidate against that paper's artifacts before returning
anything to the orchestrator (see "Design structure" above). The orchestrator
decides what to search, download, and analyze; the strategy lives in
`prompts/orchestrator.md`.

The agent's original fixed pipeline (search, assess abstracts, download,
extract text, synthesize) was removed once this engine replaced it; it is in
git history before the removal if it is ever needed.

The analyzer and verifier are read-only and receive no search, download, or
parsing tools. Only verified or verifier-corrected findings enter
`RunContext.findings`, final results, timeout partials, or fact storage.
Operational verifier failures produce an error when no other finding was
verified; evidence-based rejections produce `no_results`.

### Final answer

The orchestrator ends with `{"findings": [...]}`, which the runner ignores in
favour of the verified findings it captured itself. `core/synthesis.py` then
writes the cross-paper answer: a tool-less agent on the orchestrator route
drafts it from those findings only, and a `RubricMiddleware` grader on the
verifier route checks it against `prompts/synthesis_rubric.md`, allowing one
revision. The grader's transcript is cut at 4000 characters per message, so it
reads the findings through a `read_verified_findings` tool, and an answer
longer than `MAX_ANSWER_CHARS` is rejected. The synthesis is used only when the
grader ends `satisfied` and every `Paper N` citation is in range; otherwise the
answer is the findings rendered per paper, as before.

### Literature artifacts

After each run `agent.py` sends two kinds of conversation artifacts, built by
`core/search_artifacts.py` from the run's search hits (carried on
`FinalResult.searched_papers`, which is excluded from the result JSON):

- `searched_papers.md` - every paper the searches returned, with its source,
  year, link, and abstract (cut to 600 characters, at most 40 papers); papers
  used as verified evidence are marked. `text/markdown`, so the report viewer
  shows it.
- one citation card per verified finding: tags `reference`/`citation`, `uri`
  set to the paper's page, `metadata.source` naming the source. No MIME type,
  so the tags route it to the reference viewer.

They live in the platform's artifact registry in Valkey (no DeepLynx) and
expire with it (`ARTIFACT_REGISTRY_TTL_SECONDS`). Sending them never fails the
run.

## Tools (deepagent engine)

Tools are thin `@tool` wrappers built per-run over a shared `RunContext`
(`tools/context.py`), which holds the config, the injected `complete`/embed
functions, the Redis-backed caches, and the mutable state a run accumulates
(`search_hits`, `pdf_paths`, `findings`, counters). Budget is enforced **at the
tools** — an over-budget tool returns a refusal string, it never raises (a
raising tool would crash the orchestrator loop; `test_tools.py` pins this).

`tools/__init__.build_tools(ctx)` assembles:

- **`tools/osti.py`** — `search_osti`, `download_paper`, `parse_paper`.
  `download_paper(source_id, url=None)` fetches an arbitrary URL when given one
  (or an `oa_pdf_url` recorded in `search_hits`), else the OSTI purl.
- **`tools/search.py`** — `search_scholarly` (OpenAlex + arXiv, keyless, always
  on) and `search_web` (provider-backed, off unless configured).
- **`tools/memory.py`** — `search_knowledge_base` and `store_facts` over the
  embedding-backed `KnowledgeStore`.
- **`tools/evidence.py`** — `record_abstract_evidence` and `record_estimate`,
  weaker evidence checked in code and kept out of `findings`.

`core/deep_agent.build_research_agent` appends `analyze_paper`
(`build_analyze_paper_tool`), and deepagents adds its own filesystem tools.

### Adding a tool

1. Add a `@tool async def` inside a `build_*_tools(ctx)` factory (new file or an
   existing one), reading/writing run state through `ctx`. Enforce budget with
   `ctx.budget_reason()` and **return a string on refusal**.
2. Include the factory's output in `tools/__init__.build_tools`.
3. Add a status label in `core/deep_runner._TOOL_STATUS` so the tool call
   renders a human-readable progress line.
4. Document it for the orchestrator in `prompts/orchestrator.md` (when to use
   it, its input/output shape). The model only uses tools the prompt explains.
5. Unit-test it over a mocked `ctx` like the others in `tests/test_tools.py` /
   `tests/test_search_tools.py` — no graph needed.

### Adding a web-search provider

Implement the `WebSearchProvider` protocol in `web_search.py` (one
`async def search(query, k) -> list[dict]` returning
`{title, url, snippet, published, origin}`), wire it into `get_web_provider`
keyed off `config.web_search_provider`, add its config fields to
`core/config.py` (+ `from_env`), and add a respx test like `test_web_search.py`.
Scholarly sources (OpenAlex/arXiv) live in `scholarly.py` and follow the same
shape.

## Parsing and artifact layout

`parsing/pipeline.parse_paper_pipeline` turns a PDF into a **paper directory**
rather than one text blob. Docling runs in an isolated subprocess
(`parsing/docling_worker.py`); on failure/timeout it falls back to PyMuPDF
full-text (`method="pymupdf"`, no tables/figures, warning recorded) so consumers
always have one `paper.md` code path. Optional figure VLM analysis
(`parsing/figures.py`) is off by default (`ANALYZE_FIGURES`).

```
{workdir}/papers/{source_id}/
  paper.md                     # reading-order text with [TABLE ..]/[FIGURE ..] markers
  meta.json                    # the ParsedPaper record (parsing/artifacts.py)
  tables/table_NN.{md,csv}
  figures/fig_NN.png           # + fig_NN.json when the VLM pass ran
```

`ParsedPaper` / `TableArtifact` / `FigureArtifact` (`parsing/artifacts.py`) are
the contract; every consumer reads via them.

## Memory

The knowledge base is **shared by every user** of the platform: facts and
cached answers are not scoped per user or conversation. That is intended for
public literature; do not point this agent at private documents without adding
scoping first.

`knowledge.RedisKnowledgeStore` implements the `KnowledgeStore` protocol.
Retrieval is `SCAN` + in-process cosine over per-atomic-fact embeddings — **no
`KEYS`, no per-lookup LLM call** (the two scaling problems of the original
memory code). Embeddings come from the LiteLLM proxy (`core/llm.LiteLLMEmbedder`,
the `embedding` alias). The cached-answer path keeps the exact question-hash
fast path and adds a near-duplicate (cosine > 0.95) hit. Key prefixes are
byte-compatible with the legacy store; a missing embedding is backfilled lazily
on read (bulk: `scripts/backfill_atomic_fact_embeddings.py`). See `runbook.md` for
the key/TTL table.

Cached answers and facts are retrieval hints, not final evidence. The deep
agent must download, parse, analyze, and verify the referenced source in the
current run before using its claims in a result.

## Tests

Run with the project's canonical command (plain `uv run pytest` is broken — the
miniforge pytest lacks redis):

```
uv run --with pytest --with pytest-asyncio --with respx python -m pytest -q
```

`test_agent.py` skips without `prometheus_api`/`a2a`; golden/slow tests skip
unless `-m slow`.
