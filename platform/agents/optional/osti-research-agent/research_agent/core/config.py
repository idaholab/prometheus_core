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

"""Runtime configuration for the research_agent core.

Deliberately independent of prometheus_api: reads the same environment
variables the docker-compose service already sets (REGISTRY_URL is the
LiteLLM proxy's base URL — it doubles as the A2A gateway and the LLM proxy,
see CLAUDE.md), but a bare `AgentConfig.from_env()` also works on a laptop
with nothing but LiteLLM credentials.
"""

import os
from pathlib import Path
from typing import Dict, Literal, Optional, Tuple

from pydantic import BaseModel, Field

from research_agent.download_policy import DEFAULT_ALLOWED_DOMAINS, parse_domains


class ModelRoute(BaseModel):
    provider: Literal["openai", "anthropic"] = "openai"
    base_url: str
    api_key: Optional[str] = None
    model: str


class AgentConfig(BaseModel):
    litellm_base_url: str
    litellm_api_key: Optional[str] = None

    # Semantic model roles. Each defaults to the shared LiteLLM "medium" alias
    # and can be overridden through model_routes.
    orchestrator_model: str = "medium"
    analyzer_model: str = "medium"
    verifier_model: str = "medium"
    vlm_model: str = "medium"
    model_routes: Dict[str, ModelRoute] = Field(default_factory=dict)

    redis_url: Optional[str] = None
    redis_password: Optional[str] = None

    workdir: Path = Path("/tmp/research_agent")
    total_budget_s: int = 900
    max_papers_analyzed: int = 5
    # Unique queries per search tool per run. When they run out the agent can
    # only read results it already has, so too few ends a run early.
    max_osti_searches: int = Field(default=5, ge=1)
    max_scholarly_searches: int = Field(default=4, ge=1)
    analyzer_model_call_limit: int = Field(default=8, ge=1)
    analyzer_tool_call_limit: int = Field(default=12, ge=1)
    # The verifier must read paper.md and every artifact a finding cites, so
    # a long paper read in chunks needs more turns than the analyzer's own.
    verifier_model_call_limit: int = Field(default=10, ge=1)
    verifier_tool_call_limit: int = Field(default=12, ge=1)

    # --- Internet search and embedding-backed memory ---
    # Web search is additive and OFF by default: pick a provider only where
    # egress allows it. "tavily" needs tavily_api_key + egress to tavily.com;
    # "searxng" points at a self-hosted instance (searxng_url). Scholarly search
    # (OpenAlex + arXiv) is keyless and always available.
    web_search_provider: Literal["none", "tavily", "searxng"] = "none"
    tavily_api_key: Optional[str] = None
    searxng_url: Optional[str] = None
    # OpenAlex asks callers to identify themselves via a mailto for the polite
    # pool; harmless when unset.
    openalex_mailto: Optional[str] = None
    # arXiv rate-limits API clients hard (HTTP 429 even 3 s apart) and adds
    # little for engineering-materials questions; turn it off to save the calls.
    scholarly_arxiv: bool = True
    # LiteLLM alias for the embedding model backing the knowledge store's
    # semantic atomic-fact and answer retrieval.
    embedding_model: str = "embedding"
    # PDF download cap for arbitrary (non-OSTI) URLs.
    max_pdf_mb: int = 50
    # Hosts PDFs may be downloaded from (subdomains included); the OSTI purl
    # path is always allowed. See research_agent.download_policy.
    download_allowed_domains: Tuple[str, ...] = DEFAULT_ALLOWED_DOMAINS

    # --- PDF parsing (docling worker -> paper.md + per-table CSV/MD +
    # per-figure PNG/JSON, PyMuPDF text as the fallback) ---
    docling_timeout_s: int = 240
    # Docling memory use. Page images are rendered at this scale and kept for
    # figure crops, so memory grows with its square: 1.0 needs about a quarter
    # of 2.0's. "fast" TableFormer uses less memory and time than "accurate".
    # Lower both if the docling worker is OOM-killed ("exited -9").
    docling_images_scale: float = Field(default=2.0, gt=0, le=4)
    docling_table_mode: Literal["accurate", "fast"] = "accurate"
    # OCR for scanned PDFs: "auto" turns it on only when the cheap PyMuPDF
    # pre-check finds near-zero extractable text; "on"/"off" force it.
    parse_ocr: Literal["auto", "on", "off"] = "auto"
    # Figure PNGs are always produced. Multimodal analysis writes
    # figures/*.json only when explicitly enabled; the pipeline engine does not
    # consume those JSON artifacts.
    analyze_figures: bool = False
    max_figures: int = 12
    # Skip figures smaller than this pixel area (logos, rules, decorations).
    min_figure_area: int = 10_000

    def model_route(
        self,
        role: Literal["orchestrator", "analyzer", "verifier", "vlm", "embedding"],
    ) -> ModelRoute:
        route = self.model_routes.get(role)
        if route is not None:
            return route
        return ModelRoute(
            base_url=self.litellm_base_url,
            api_key=self.litellm_api_key,
            model=getattr(self, f"{role}_model"),
        )

    @classmethod
    def from_env(cls) -> "AgentConfig":
        base_url = (
            os.getenv("LITELLM_BASE_URL")
            or os.getenv("REGISTRY_URL")
            or "http://localhost:4000"
        )
        return cls(
            litellm_base_url=base_url,
            litellm_api_key=os.getenv("LITELLM_MASTER_KEY"),
            redis_url=os.getenv("REDIS_URL"),
            redis_password=os.getenv("REDIS_PASSWORD"),
            total_budget_s=int(os.getenv("TOTAL_BUDGET_S", "900")),
            max_papers_analyzed=int(os.getenv("MAX_PAPERS_ANALYZED", "5")),
            max_osti_searches=int(os.getenv("MAX_OSTI_SEARCHES", "5")),
            max_scholarly_searches=int(os.getenv("MAX_SCHOLARLY_SEARCHES", "4")),
            analyzer_model_call_limit=int(os.getenv("ANALYZER_MODEL_CALL_LIMIT", "8")),
            analyzer_tool_call_limit=int(os.getenv("ANALYZER_TOOL_CALL_LIMIT", "12")),
            verifier_model_call_limit=int(os.getenv("VERIFIER_MODEL_CALL_LIMIT", "10")),
            verifier_tool_call_limit=int(os.getenv("VERIFIER_TOOL_CALL_LIMIT", "12")),
            max_pdf_mb=int(os.getenv("MAX_PDF_MB", "50")),
            download_allowed_domains=parse_domains(os.getenv("DOWNLOAD_ALLOWED_DOMAINS")),
            docling_timeout_s=int(os.getenv("DOCLING_TIMEOUT_S", "240")),
            docling_images_scale=float(os.getenv("DOCLING_IMAGES_SCALE", "2.0")),
            docling_table_mode=os.getenv("DOCLING_TABLE_MODE", "accurate").strip().lower(),
            parse_ocr=os.getenv("PARSE_OCR", "auto"),
            analyze_figures=_env_bool("ANALYZE_FIGURES", default=False),
            scholarly_arxiv=_env_bool("SCHOLARLY_ARXIV", default=True),
            max_figures=int(os.getenv("MAX_FIGURES", "12")),
            min_figure_area=int(os.getenv("MIN_FIGURE_AREA", "10000")),
            web_search_provider=os.getenv("WEB_SEARCH_PROVIDER", "none"),
            tavily_api_key=os.getenv("TAVILY_API_KEY"),
            searxng_url=os.getenv("SEARXNG_URL"),
            openalex_mailto=os.getenv("OPENALEX_MAILTO"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "embedding"),
        )


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")
