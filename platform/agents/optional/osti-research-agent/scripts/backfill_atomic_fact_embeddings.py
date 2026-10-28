#!/usr/bin/env python3
# This file is part of Prometheus
# https://inl.gov/super-intelligence/prometheus/
#
# Copyright 2026 Battelle Energy Alliance, LLC
# All rights reserved, see NOTICE.txt for full restrictions
# https://github.com/idaholab/prometheus_core/blob/main/NOTICE.txt
#
# Licensed under the MIT License, please see LICENSE for details
# https://github.com/idaholab/prometheus_core/blob/main/LICENSE
#
# SPDX-License-Identifier: MIT

"""Give every legacy atomic fact an embedding.

The knowledge store backfills a missing embedding lazily the first time a
fact is scored, but this script processes the whole store up front so the first
few post-deploy lookups are not slowed by it. It scans the legacy
``osti:factoid:*`` key space, computes embeddings for records missing one, and
writes them back in place. It is safe to re-run.

Usage (needs REDIS_URL + LiteLLM creds in the environment, as the service has):
    uv run python scripts/backfill_atomic_fact_embeddings.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


async def _run() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from research_agent.core.config import AgentConfig
    from research_agent.core.llm import LiteLLMEmbedder
    from research_agent.knowledge import RedisKnowledgeStore
    from research_agent.memory import RedisCaches

    config = AgentConfig.from_env()
    if not config.redis_url:
        print("REDIS_URL is not set; nothing to backfill.", file=sys.stderr)
        return 0

    caches = RedisCaches(config.redis_url, config.redis_password)
    embedder = LiteLLMEmbedder(
        config.litellm_base_url, config.litellm_api_key, config.embedding_model
    )
    store = RedisKnowledgeStore(caches.client, embedder.embed)

    print("Backfilling atomic-fact embeddings (legacy key: osti:factoid:*)...")
    count = await store.backfill_all()
    print(f"Backfilled {count} atomic-fact embedding(s).")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":  # pragma: no cover - script entry point
    raise SystemExit(main())
