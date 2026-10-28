# OSTI Research Agent — architecture

How the OSTI research agent is currently structured. For the platform it
plugs into (backend agent registry, Valkey, A2A), see the repo-root `CLAUDE.md`.

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

## The engine

`core/deep_runner.py` runs a `deepagents.create_deep_agent` orchestrator
(LangGraph under the hood) with a compiled `paper-analyzer` task. The task
first analyzes one parsed paper, then independently verifies the candidate
against that paper's artifacts before returning anything to the orchestrator.
The orchestrator decides what to search, download, and analyze; the strategy
lives in `prompts/orchestrator.md`.

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
