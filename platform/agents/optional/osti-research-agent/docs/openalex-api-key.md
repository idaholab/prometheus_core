# OpenAlex API key

`search_scholarly` searches OpenAlex, and `download_paper` asks OpenAlex for an
open-access copy when an OSTI record has no full text. Both work without a key.
A free OpenAlex key raises the daily limit tenfold. Set it in
`OPENALEX_API_KEY`.

## Why you may want one

OpenAlex limits each caller to a daily budget in US dollars, reset at midnight
UTC. Measured from its response headers on 2026-11-10:

| | Daily budget | `search_scholarly` calls a day |
|---|---|---|
| No key (shared by everything calling from your IP) | $0.10 | about 100 |
| Free key | $1.00 | about 1,000 |

- **A search costs $0.001.** That's one `search_scholarly` call, which also
  sends one arXiv request that OpenAlex doesn't count.
- **A DOI lookup is free.** That's what `download_paper` sends when looking for
  an open-access copy.
- **What runs out.** A run makes at most `MAX_SCHOLARLY_SEARCHES` (4) searches,
  so the keyless budget covers about 25 runs a day. A full `make osti-eval`
  (48 questions) can use 150 or more, and so can anything else calling OpenAlex
  from the same IP.
- **What happens when it runs out.** OpenAlex answers `429 Too Many Requests`.
  The agent retries once, then reports "scholarly search failed" to the model,
  and the run carries on with OSTI alone.

`OPENALEX_MAILTO` used to put you in OpenAlex's "polite pool". It no longer
changes the limits; the same request with and without it is charged the same.
It's still sent if set.

## Get a key

1. Sign up at <https://openalex.org/signup>.
2. Copy the key from <https://openalex.org/settings/api-key>.

The key is free. A new key's first $1 is released at $0.10 per 5 minutes.

## Set it

Add it to the platform `.env` that your stack is started with:

```
OPENALEX_API_KEY=your-key-here
```

- **Which `.env`.** It's the one the agent container was started from. For the
  dev attach setup in `docker-compose.attach.yml`, that's the file passed with
  `--env-file`. To see which file a running container used:
  `docker inspect osti-research-agent --format '{{index .Config.Labels "com.docker.compose.project.environment_file"}}'`.
- **How it reaches the agent.** The agent's `docker-compose.yml` passes it
  through, so no other file needs changing.

Then recreate the agent container so it picks the variable up:

```bash
# full platform
make up OPTIONAL_AGENTS=true

# or just the agent, from the agent's directory, for the dev attach setup
env -i HOME="$HOME" PATH="$PATH" \
  PROMETHEUS_API_BASE_IMAGE_REPO=prometheus_api PROMETHEUS_API_BASE_IMAGE_HASH=local \
  docker compose -p osti-dev --env-file <platform>/.env \
  -f docker-compose.yml -f docker-compose.attach.yml up -d osti-research-agent
```

`docker restart` is not enough: it keeps the container's old environment.

## Check that it works

Confirm the container has the key, without printing it:

```bash
docker exec osti-research-agent sh -c 'test -n "$OPENALEX_API_KEY" && echo "key set" || echo "key not set"'
```

Then check what OpenAlex sees. This sends the same request the agent does, and
costs one search ($0.001):

```bash
docker exec osti-research-agent python -c "
import os, httpx
key = os.environ.get('OPENALEX_API_KEY')
r = httpx.get('https://api.openalex.org/works', params={'search': 'creep', 'per-page': 1},
              headers={'Authorization': f'Bearer {key}'} if key else {})
print(r.status_code, r.headers.get('x-ratelimit-limit-usd'), r.text[:120] if r.status_code != 200 else '')"
```

- **`200 1`:** the key works ($1 a day).
- **`200 0.1`:** no key is set, so the agent is on the keyless budget.
- **401:** OpenAlex doesn't know the key. Check for a typo, or a missing or
  extra character from copying it.
- **403 with `key_not_activated`:** the key hasn't been activated yet. Follow
  the link in OpenAlex's email.

## If the key is wrong

An invalid key doesn't fall back to keyless access: OpenAlex rejects every
call that carries it, including ones that would work without a key. The agent
logs this, and tells the model, as:

```
OpenAlex search failed: Client error '401 Unauthorized' for url '...' (OpenAlex rejected OPENALEX_API_KEY; check it or unset it to search without a key)
```

Fix the key, or remove the line from `.env`, and recreate the container.

## How the agent sends it

- **In a header, not the URL.** The key goes in an `Authorization: Bearer`
  header, which OpenAlex treats the same as an `api_key` query parameter. Keys
  in URLs end up in logs: httpx includes the full request URL in its error
  messages, and the agent logs those and passes them to the model. The tests
  check that the key never appears in a request URL, an error message or a log
  line.
- **Kept out of printed config.** `AgentConfig` leaves it out of its `repr`.
- **Sent on every OpenAlex call** (search and DOI lookup), never to arXiv or
  anywhere else.

Code: `research_agent/scholarly.py` (`_openalex_request_parts`),
`research_agent/core/config.py` (`openalex_api_key`).

## See also

- [OpenAlex: rate limits and authentication](https://help.openalex.org/how-to-use-the-api/rate-limits-and-authentication)
- [`runbook.md`](runbook.md) for the agent's other settings
