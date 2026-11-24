# OSTI Research Agent — runbook

Operational reference: budget tuning, cache keys/TTLs, and how to replay a run.
Architecture is in `architecture.md`; how to evaluate a change is in
`evaluation.md`; setting up an OpenAlex key is in `openalex-api-key.md`.

## Config / tuning knobs

All read by `AgentConfig.from_env()` (`core/config.py`); most have safe
defaults.

| Env var | Default | Effect |
|---------|---------|--------|
| `TOTAL_BUDGET_S` | `900` | hard wall-clock ceiling; runner cancels at `budget-30s` and salvages `timeout_partial` |
| `MAX_PAPERS_ANALYZED` | `6` | papers read per run: `read_top_candidates` reads them in rank order, 3 at a time, so 6 is two batches |
| `MAX_OSTI_SEARCHES` | `5` | unique OSTI queries per run |
| `MAX_SCHOLARLY_SEARCHES` | `4` | unique OpenAlex/arXiv queries per run |
| `ANALYZER_MODEL_CALL_LIMIT` | `8` | maximum model calls per paper-analyzer run |
| `ANALYZER_TOOL_CALL_LIMIT` | `12` | maximum filesystem-tool calls per paper-analyzer run |
| `VERIFIER_MODEL_CALL_LIMIT` | `10` | maximum model calls per paper-verifier run; raise it if logs show "Verifier model-call limit reached" |
| `VERIFIER_TOOL_CALL_LIMIT` | `12` | maximum filesystem-tool calls per paper-verifier run |
| `WEB_SEARCH_PROVIDER` | `none` | `searxng` (the bundled `osti-searxng` service, see [Web search](#web-search-searxng)) or `tavily` (needs `TAVILY_API_KEY`); scholarly search is always on |
| `TAVILY_API_KEY` | — | credential for Tavily web search |
| `SEARXNG_URL` | `http://osti-searxng:8080` | base URL of the SearXNG instance; the default is the bundled service |
| `SEARXNG_SECRET` | generated per start | `server.secret_key` for the bundled SearXNG; only signs its UI cookies, so the generated one is fine |
| `OPENALEX_API_KEY` | — | free OpenAlex key; raises its daily limit from about 50 to about 500 searches. See [`openalex-api-key.md`](openalex-api-key.md) |
| `OPENALEX_MAILTO` | — | contact address sent to OpenAlex; no longer changes its limits |
| `SCHOLARLY_ARXIV` | `true` | also search arXiv; `false` skips it (arXiv answers 429 to frequent API clients and has little engineering-materials data) |
| `SCHOLARLY_SEMANTIC` | `true` | also run OpenAlex semantic (embedding) search, open-access only, and fuse it with keyword search by reciprocal rank fusion. It's a second OpenAlex call per search, so the keyless daily budget covers about 50 searches instead of 100 (with a key, 500 instead of 1,000); `false` skips it |
| `EMBEDDING_MODEL` | `embedding` | LiteLLM alias for the knowledge-store embeddings |
| `MAX_PDF_MB` | `50` | maximum download size for arbitrary non-OSTI PDF URLs |
| `DOWNLOAD_ALLOWED_DOMAINS` | built-in list | comma-separated hosts PDFs may be downloaded from (subdomains included). Others are never fetched, and search results only offer `oa_pdf_url` for them; a host that answers 401/403 is dropped for the rest of the run. The OSTI purl path is always allowed. Default list: `research_agent/download_policy.py` |
| `DOCLING_TIMEOUT_S` | `480` | timeout for the isolated Docling conversion process. Docling runs single-threaded at about 2-3 s a page for mostly-text papers, but table-heavy ones are slower: a 96-page report with 29 tables took 539 s in `accurate` mode (about 5.6 s a page) and 324 s in `fast`. A paper that runs over falls back to PyMuPDF text (no tables or figures), and that fallback is not cached, so the paper costs the full timeout again on every run. Raise it (720 s fits that report) when `TOTAL_BUDGET_S` leaves room |
| `DOCLING_IMAGES_SCALE` | `2.0` | page-image render scale; memory grows with its square, so `1.0` needs about a quarter. Lower it if the worker is killed out of memory ("exited -9") |
| `DOCLING_TABLE_MODE` | `accurate` | TableFormer mode, `accurate` or `fast` (less memory and about 40% less time, rougher table structure). On a 96-page report, `fast` kept every value in its row but scrambled the column headers of 16 of 29 tables, for example merging "Rupture life (hr)" and "Minimum creep rate (%/hr)". An analyzer could then read the wrong column, so prefer a longer `DOCLING_TIMEOUT_S` over `fast` |
| `PARSE_OCR` | `auto` | `on`/`off` force OCR for scanned PDFs |
| `ANALYZE_FIGURES` | `false` | enable the figure VLM pass |
| `MAX_FIGURES` | `12` | maximum figures considered per paper |
| `MIN_FIGURE_AREA` | `10000` | skip smaller decorative images by pixel area |
| `REDIS_URL` | — | unset ⇒ no memory/caching (everything degrades gracefully) |

**Budget guidance.** Parsing costs ~1–5 min per paper (about 2–3 s a page, up to about 6 s a page for table-heavy papers). With the 900 s budget the
deepagent orchestrator is told (in `prompts/orchestrator.md`) it has ~13 minutes;
`tools/context.BUDGET_FLOOR_S` (90 s) stops new expensive work early so writing
and grading the answer, and fact storage, always run. If p90 latency creeps up, lower
`max_papers_analyzed` before raising `total_budget_s`.

The source-artifact verifier uses the semantic `verifier` model role, which
defaults to the `medium` alias. It is fixed at 6 model calls and 8 filesystem
calls per candidate and shares the overall run deadline. Rejected candidates
are omitted. If every candidate is lost to verifier infrastructure or model
errors, the run returns `error`; timeout recovery includes previously verified
findings only. Each parsed source is analyzed at most once per run; duplicate
delegations reuse its terminal result.

## Web search (SearXNG)

`search_web` is off by default. The agent's compose file also starts
`osti-searxng`, a SearXNG metasearch instance built from `searxng/`, and the
agent's `SEARXNG_URL` already points at it. To turn web search on, set this in
the platform `.env` and restart the agent:

```
WEB_SEARCH_PROVIDER=searxng
```

- **Reachable only by the agent.** It has no host port, so the only way to it
  is over `agent-network`. To query it by hand:
  `docker exec osti-research-agent python -c "import urllib.request; print(urllib.request.urlopen('http://osti-searxng:8080/search?q=Alloy+709+creep&format=json').read()[:500])"`.
- **Engines.** `searxng/settings.yml` lists them and says why each was chosen
  (Startpage, Yahoo, Mojeek, Wikipedia). They scrape public search sites, which
  can start answering with a CAPTCHA or "too many requests" without notice; an
  engine that does appears in the JSON's `unresponsive_engines` and adds no
  results. Change the list there and rebuild (`make up` rebuilds it).
- **Results are leads, not evidence.** Only hosts on
  `DOWNLOAD_ALLOWED_DOMAINS` are downloadable, so many web hits come back
  `downloadable: false`. Web searches have no per-run budget.
- **TLS inspection.** The image installs `common/certs` like the other
  Prometheus images, so it works behind INL's Zscaler.
- **Upgrading.** The base image is pinned in `searxng/Dockerfile`. SearXNG
  changes its engines often, so re-run a few queries after bumping it.

## Redis keys and TTLs

These keys are global, not per user: every user's runs read and write the same
facts and cached answers.

`decode_responses=True` client (binary caches use a separate raw client).

| Key | Contents | TTL |
|-----|----------|-----|
| `osti:paper:pdf_bytes:{osti_id}` | raw downloaded PDF | 30 days |
| `osti:paper:pdf_bytes:url:{sha256(url)}` | raw PDF from a scholarly/web URL | 30 days |
| `osti:paper:artifacts:v1:{source_id}` | zipped artifact dir (docling) | 30 days |
| `osti:paper:figjson:v1:{source_id}:{idx}` | per-figure VLM JSON | 30 days |
| `osti:factoid:{uuid}` | atomic fact + embedding + source (legacy key name) | **persistent (no TTL)** |
| `osti:paper:{source_id}:facts` | set: atomic-fact IDs for a paper | persistent |
| `osti:topic:{topic}:factoids` | set: atomic-fact IDs for a topic (legacy key name) | persistent |
| `osti:question:{md5(question)}:answer` | cached answer + embedding | 30 days |
| `agent:status:{conversation_id}` | latest status (UI mirror) | 10 min |
| `agent:status_history:{conversation_id}` | bounded status log (last 200) | 10 min |

**Atomic facts are persistent by design** (accumulated knowledge). To reset memory,
delete the `osti:factoid:*`, `osti:paper:*:facts`, `osti:topic:*:factoids`, and
`osti:question:*:answer` keys — use `SCAN`, never `KEYS`, on a shared Valkey.
After importing legacy records, run
`scripts/backfill_atomic_fact_embeddings.py` to embed records that do not
already have embeddings. The script is safe to re-run; lazy backfill covers any
remaining records on read.

## Developing against a running platform

To try this checkout's agent in a platform stack that is already up (for
example one started from another worktree), run `./dev-attach.sh` from the
agent's directory. It rebuilds the agent, starts it on the platform's network
with that platform's `.env`, and waits until it is healthy; the agent
registers itself on start. The platform is found from its running backend
container, or set `PLATFORM_DIR`. Stop the platform's own
`osti-research-agent` container first (the script refuses to start while it
runs), since both would answer to the same name. `./dev-attach.sh --logs`
follows the agent's logs and `./dev-attach.sh --down` removes it. Relaunching
the platform with `make up` or `make restart` starts its own agent again and
clears the registrations: stop it again, then rerun the script.

## Replaying / debugging a run

- **CLI (fastest loop):** reproduce any question locally with only LLM creds:
  ```
  uv run python -m research_agent "<the question>" --workdir ./out
  ```
  Progress prints to stderr; the full `FinalResult` lands in `out/result.json`.
  Add `--no-redis` to rule out a stale cache.
- **LangSmith traces:** the deepagent engine's LangGraph `astream` is traced when
  `LANGCHAIN_TRACING_V2=true` and `LANGCHAIN_API_KEY` are set. A trace shows every
  tool call, subagent turn, and token/latency breakdown. LangGraph does not
  checkpoint to LangSmith, so "replay" = copy the input question from the trace
  and re-run it via the CLI above with the same `--run-id`.
- **Status mirror:** for a run in the live stack, `GET agent:status:{conversation_id}`
  shows the latest status and `LRANGE agent:status_history:{conversation_id} 0 -1`
  the full progress log (10-min TTL) — the first place to look for a stuck run.

## Evaluation

`evals/` runs the agent over `evals/questions.yaml` and scores the answers
(`make osti-eval`; see `evals/README.md`). Run it after any change that could
affect answer quality.
