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
"""Redis-backed caches: downloaded PDFs, parsed-paper artifact directories,
and per-figure VLM JSON.

Nothing here imports prometheus_api or a2a - the clients are plain redis-py
objects built by RedisCaches below (or absent, when running without Redis -
e.g. `research_agent.cli --no-redis`). Facts and cached answers live in
``research_agent.knowledge``.
"""

from typing import Optional, Protocol

import redis


class PdfCache(Protocol):
    def get_pdf(self, key: str) -> Optional[bytes]: ...
    def put_pdf(self, key: str, data: bytes, ttl_s: int) -> None: ...


class ArtifactCache(Protocol):
    """Caches a whole parsed-paper artifact directory as a single tar blob,
    plus per-figure VLM JSON. Used by research_agent.parsing.pipeline."""

    def get_artifacts(self, key: str) -> Optional[bytes]: ...
    def put_artifacts(self, key: str, data: bytes, ttl_s: int) -> None: ...
    def get_figjson(self, source_id: str, idx: int) -> Optional[str]: ...
    def put_figjson(self, source_id: str, idx: int, data: str, ttl_s: int) -> None: ...


def _build_redis_client(
    redis_url: str, *, decode_responses: bool, password: Optional[str]
) -> redis.Redis:
    return redis.Redis.from_url(
        redis_url, decode_responses=decode_responses, password=password
    )


class RedisCaches:
    """Wraps the text and binary Redis clients behind the PDF and parsed-paper
    caches; the text client is also the knowledge store's."""

    def __init__(self, redis_url: Optional[str], redis_password: Optional[str] = None):
        self._redis_url = redis_url
        self._redis_password = redis_password
        self._client: Optional[redis.Redis] = None
        self._binary_client: Optional[redis.Redis] = None

    @property
    def client(self) -> redis.Redis:
        """Lazy initialization of the Redis client for text data."""
        if self._client is None:
            self._client = _build_redis_client(
                self._redis_url, decode_responses=True, password=self._redis_password
            )
        return self._client

    @property
    def binary_client(self) -> redis.Redis:
        """Lazy initialization of the Redis client for binary data (PDFs)."""
        if self._binary_client is None:
            self._binary_client = _build_redis_client(
                self._redis_url, decode_responses=False, password=self._redis_password
            )
        return self._binary_client

    def get_pdf(self, key: str) -> Optional[bytes]:
        return self.binary_client.get(f"osti:paper:pdf_bytes:{key}")

    def put_pdf(self, key: str, data: bytes, ttl_s: int) -> None:
        self.binary_client.set(f"osti:paper:pdf_bytes:{key}", data, ex=ttl_s)

    # --- Parsed-artifact-directory cache (binary tar) ---

    def get_artifacts(self, key: str) -> Optional[bytes]:
        return self.binary_client.get(f"osti:paper:artifacts:v1:{key}")

    def put_artifacts(self, key: str, data: bytes, ttl_s: int) -> None:
        self.binary_client.set(f"osti:paper:artifacts:v1:{key}", data, ex=ttl_s)

    def get_figjson(self, source_id: str, idx: int) -> Optional[str]:
        return self.client.get(f"osti:paper:figjson:v1:{source_id}:{idx}")

    def put_figjson(self, source_id: str, idx: int, data: str, ttl_s: int) -> None:
        self.client.set(f"osti:paper:figjson:v1:{source_id}:{idx}", data, ex=ttl_s)
