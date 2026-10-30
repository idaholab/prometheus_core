# Files and artifacts

Facts as of `prometheus_core` `devel` 2026-10-30, after #310 (`prometheus_api` 0.15, no LiteLLM). When the code disagrees with this file, the code is correct.

Files travel as artifacts: your skill gets ids, not data (deck 04, slides 8-10 and 21). An upload goes to
DeepLynx, the catalog gives it an id, and the orchestrator passes the id. The catalog is per conversation,
in Valkey, 7-day TTL; `/artifacts` in the chat lists it. Short path: `base.py` is in
`prometheus_api/prometheus_api/agent/`.

## Files in

Card: `"document_artifact_id": {"type": "string", "x_artifact_ref": "single", "description": "The markdown document."}`.
Code (`base.py:1196-1226`):

```python
try:
    path = await self.get_artifact_file_path(params["document_artifact_id"], context=context, artifacts=params.get("artifacts"))
except FileNotFoundError:
    return {"status": "error", "error": "That artifact is not in this conversation."}
```

Let other exceptions raise. Your `DEEPLYNX_*` values must name the same org and project as the URI.

## Artifacts out

```python
table_id = await self.send_json_artifact(context, event_queue, {"caption": c, "columns": cols, "rows": rows},
                                         name="population_table", catalog_artifact=True)  # returns the id

from prometheus_api.storage_client import ConnectionConfig
with tempfile.TemporaryDirectory() as tmp:
    png = Path(tmp) / "population.png"  # TODO: render in a thread (long-running.md)
    ref = await self.send_deeplynx_artifact(context=context, event_queue=event_queue, file_path=png,
        name="population.png", description="Population vs year",
        storage_config=ConnectionConfig.from_env(), mime_type="image/png")
return {"status": "success", "artifact_id": ref.artifact_id}
```

`catalog_artifact=True` lets the next skill find it. Upload inside the `with` block (`base.py:1642-1874`).
Always set `mime_type`: it picks the viewer (image, JSON tree, report, PDF, Mermaid, 3D mesh; CSV is a
download; `prometheus_platform/backend/app/services/artifacts.py:169-237`).

## DeepLynx

`ConnectionConfig.from_env()` reads `DEEPLYNX_KEY`, `DEEPLYNX_SECRET`, `DEEPLYNX_ORG_ID`,
`DEEPLYNX_PROJECT_ID`, `DEEPLYNX_BASE_URL`. A container sees only its `environment:` values. Without
DeepLynx the chat says "DeepLynx storage is not configured", and agents exit at startup with "Invalid
required DeepLynx configuration: …" (every call writes an execution record).

| symptom | fix |
|---|---|
| "Invalid required DeepLynx configuration: missing …" | set `DEEPLYNX_ORG_ID` and `DEEPLYNX_PROJECT_ID` |
| `Must provide either jwt_token or both api_key and api_secret` | set the key and the secret |
| :5000 answers `Server: AirTunes` (macOS) | turn off AirPlay Receiver |

Check the platform side (no secret):

```sh
docker compose -p prometheus_platform exec -T backend python -c "from prometheus_api.storage_client import ConnectionConfig, StorageClient; c=ConnectionConfig.from_env(); s=StorageClient(c); print('OK', c.base_url, len(s.items.list(page_size=5).items), 'items')"
```

## Local DeepLynx

Deck 03, slides 18-20. Free ports 3000, 5000, 5432 first.

1. Next to the platform: `git clone https://github.com/idaholab/DeepLynx.git && cd DeepLynx && cp .env_sample .env && docker compose build && docker compose up -d`.
   Check: `curl -s -o /dev/null -w '%{http_code}\n' http://localhost:3000` prints `200`.
2. Open http://localhost:3000, pick "INL – default organization" (id 1), click "+ Project". The URL shows the project id.
3. Person icon › Settings › API Keys › "+ Generate New". The secret shows once. Never paste it into the chat.
4. In `prometheus_platform/.env` (your editor): `DEEPLYNX_KEY`, `DEEPLYNX_SECRET`,
   `DEEPLYNX_BASE_URL=http://prometheus.host.internal:5000/api/v1`, `DEEPLYNX_ORG_ID=1`, `DEEPLYNX_PROJECT_ID`.
5. `make down` in the agent folder, then `make restart` in the platform (it empties the registry).
6. Copy the values into the agent, printing nothing:
   `cd <agent> && { grep -v '^DEEPLYNX_' .env; grep -E '^DEEPLYNX_(BASE_URL|KEY|SECRET|JWT_TOKEN|ORG_ID|PROJECT_ID|DATA_SOURCE_ID)=' <platform>/.env; } > .env.new && mv .env.new .env`.
   Only the client keys: the other `DEEPLYNX_*` lines in the platform `.env` are the DeepLynx server's own secrets.
   This also drops them from an agent scaffolded before `setup_agent.py` stopped copying them.
7. `make up` in the agent folder. Upload a small file in a fresh chat; `/artifacts` lists it.
