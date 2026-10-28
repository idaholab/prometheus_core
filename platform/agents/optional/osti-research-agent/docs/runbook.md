# OSTI Research Agent — runbook

Operational reference: budget tuning, cache keys/TTLs, and how to replay a run.
Architecture is in `architecture.md`.

## Config / tuning knobs

All read by `AgentConfig.from_env()` (`core/config.py`); most have safe
defaults.

| Env var | Default | Effect |
|---------|---------|--------|
| `TOTAL_BUDGET_S` | `900` | hard wall-clock ceiling; runner cancels at `budget-30s` and salvages `timeout_partial` |
| `MAX_PAPERS_ANALYZED` | `5` | download/parse budget; tools refuse past it |
| `MAX_OSTI_SEARCHES` | `5` | unique OSTI queries per run |
| `MAX_SCHOLARLY_SEARCHES` | `4` | unique OpenAlex/arXiv queries per run |
| `ANALYZER_MODEL_CALL_LIMIT` | `8` | maximum model calls per paper-analyzer run |
| `ANALYZER_TOOL_CALL_LIMIT` | `12` | maximum filesystem-tool calls per paper-analyzer run |
| `VERIFIER_MODEL_CALL_LIMIT` | `10` | maximum model calls per paper-verifier run; raise it if logs show "Verifier model-call limit reached" |
| `VERIFIER_TOOL_CALL_LIMIT` | `12` | maximum filesystem-tool calls per paper-verifier run |
| `WEB_SEARCH_PROVIDER` | `none` | `tavily` (needs `TAVILY_API_KEY`) or `searxng` (needs `SEARXNG_URL`); scholarly search is always on |
| `TAVILY_API_KEY` | — | credential for Tavily web search |
| `SEARXNG_URL` | — | base URL for a self-hosted SearXNG instance |
| `OPENALEX_MAILTO` | — | identifies the caller to OpenAlex's polite pool |
| `SCHOLARLY_ARXIV` | `true` | also search arXiv; `false` skips it (arXiv answers 429 to frequent API clients and has little engineering-materials data) |
| `EMBEDDING_MODEL` | `embedding` | LiteLLM alias for the knowledge-store embeddings |
| `MAX_PDF_MB` | `50` | maximum download size for arbitrary non-OSTI PDF URLs |
| `DOWNLOAD_ALLOWED_DOMAINS` | built-in list | comma-separated hosts PDFs may be downloaded from (subdomains included). Others are never fetched, and search results only offer `oa_pdf_url` for them; a host that answers 401/403 is dropped for the rest of the run. The OSTI purl path is always allowed. Default list: `research_agent/download_policy.py` |
| `DOCLING_TIMEOUT_S` | `240` | timeout for the isolated Docling conversion process |
| `DOCLING_IMAGES_SCALE` | `2.0` | page-image render scale; memory grows with its square, so `1.0` needs about a quarter. Lower it if the worker is killed out of memory ("exited -9") |
| `DOCLING_TABLE_MODE` | `accurate` | TableFormer mode, `accurate` or `fast` (less memory and time, rougher table structure) |
| `PARSE_OCR` | `auto` | `on`/`off` force OCR for scanned PDFs |
| `ANALYZE_FIGURES` | `false` | enable the figure VLM pass |
| `MAX_FIGURES` | `12` | maximum figures considered per paper |
| `MIN_FIGURE_AREA` | `10000` | skip smaller decorative images by pixel area |
| `REDIS_URL` | — | unset ⇒ no memory/caching (everything degrades gracefully) |

**Budget guidance.** Parsing costs ~1–3 min per paper. With the 900 s budget the
deepagent orchestrator is told (in `prompts/orchestrator.md`) it has ~13 minutes;
`tools/context.BUDGET_FLOOR_S` (90 s) stops new expensive work early so synthesis
and fact storage always run. If p90 latency creeps up, lower
`max_papers_analyzed` before raising `total_budget_s`.

The source-artifact verifier uses the semantic `verifier` model role, which
defaults to the `medium` alias. It is fixed at 6 model calls and 8 filesystem
calls per candidate and shares the overall run deadline. Rejected candidates
are omitted. If every candidate is lost to verifier infrastructure or model
errors, the run returns `error`; timeout recovery includes previously verified
findings only. Each parsed source is analyzed at most once per run; duplicate
delegations reuse its terminal result.

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
