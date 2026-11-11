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

"""Scholarly search over OpenAlex (works index) and arXiv (preprints).

Both work without a key, so ``search_scholarly`` is always available - it's
the fallback when OSTI is thin or the topic is outside DOE scope. An optional
OpenAlex API key (``OPENALEX_API_KEY``) raises OpenAlex's daily budget; see
docs/openalex-api-key.md. Returns
normalized hit dicts carrying an ``oa_pdf_url`` when an open-access PDF exists,
which the generalized downloader can fetch directly.

Uses httpx (async) so it's exercised under respx in tests. arXiv's Atom feed is
parsed with the stdlib XML parser rather than adding a feedparser dependency.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

import httpx

from research_agent.rate_gate import RateGate

logger = logging.getLogger(__name__)

OPENALEX_URL = "https://api.openalex.org/works"
ARXIV_URL = "https://export.arxiv.org/api/query"
_TIMEOUT = 30
_USER_AGENT = "osti-research-agent/1.0 (+https://www.osti.gov)"

_ATOM = "{http://www.w3.org/2005/Atom}"

# A 429 (rate limited) or 503 (temporarily unavailable) is retried once,
# after the server's Retry-After (capped) or this default.
_RETRY_STATUSES = (429, 503)
_RETRY_AFTER_S = 5.0
_MAX_RETRY_AFTER_S = 30.0


class SearchFailed(Exception):
    """A scholarly source could not be searched (an error, not zero hits)."""


def _openalex_request_parts(
    mailto: Optional[str], api_key: Optional[str]
) -> tuple[dict, dict]:
    """Query params and headers that identify the caller to OpenAlex.

    The key goes in an ``Authorization: Bearer`` header, which OpenAlex treats
    the same as an ``api_key`` query parameter, so it never appears in a URL:
    httpx puts the full request URL in its error messages, and those are
    logged and shown to the model."""
    params = {"mailto": mailto} if mailto else {}
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    return params, headers


def _openalex_error_text(e: Exception, api_key: Optional[str]) -> str:
    """``_error_text``, plus what to do when a key was sent and refused: an
    invalid key fails every call, including ones that work without a key."""
    text = _error_text(e)
    if (
        api_key
        and isinstance(e, httpx.HTTPStatusError)
        and e.response.status_code in (401, 403)
    ):
        text += (
            " (OpenAlex rejected OPENALEX_API_KEY; check it or unset it to search"
            " without a key)"
        )
    return text


def _doi_slug(doi: Optional[str]) -> Optional[str]:
    """Normalize a DOI (URL or bare) to a filesystem-safe slug, or None."""
    if not doi:
        return None
    doi = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix) :]
            break
    doi = doi.strip("/")
    if not doi:
        return None
    return doi.replace("/", "_")


def _source_id(doi: Optional[str], url: str) -> str:
    slug = _doi_slug(doi)
    if slug:
        return slug
    return "url_" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _reconstruct_abstract(inverted_index: Optional[Dict[str, List[int]]]) -> str:
    """OpenAlex ships abstracts as an inverted index {word: [positions]} for
    copyright reasons; rebuild the running text."""
    if not inverted_index:
        return ""
    positioned: List[tuple] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            positioned.append((pos, word))
    positioned.sort(key=lambda p: p[0])
    return " ".join(word for _, word in positioned)


def _openalex_hit(work: dict) -> dict:
    doi = work.get("doi")
    landing = work.get("id", "")
    url = doi or landing
    best_oa = work.get("best_oa_location") or {}
    oa_pdf_url = best_oa.get("pdf_url")
    authors = [
        (a.get("author") or {}).get("display_name", "")
        for a in work.get("authorships", []) or []
    ]
    return {
        "source_id": _source_id(doi, url or landing),
        "title": work.get("title") or work.get("display_name") or "",
        "authors": [a for a in authors if a],
        "year": work.get("publication_year"),
        "abstract": _reconstruct_abstract(work.get("abstract_inverted_index")),
        "doi": _doi_slug(doi),
        "url": url or landing,
        "oa_pdf_url": oa_pdf_url,
        "origin": "openalex",
    }


async def search_openalex(
    query: str,
    k: int = 10,
    *,
    mailto: Optional[str] = None,
    api_key: Optional[str] = None,
    raise_on_failure: bool = False,
) -> List[dict]:
    """OpenAlex works matching ``query``; a 429 or 503 is retried once.

    On failure returns ``[]``, or raises ``SearchFailed`` with
    ``raise_on_failure`` so a caller can tell a failure from zero hits."""
    auth_params, auth_headers = _openalex_request_parts(mailto, api_key)
    params = {"search": query, "per-page": max(1, min(k, 50)), **auth_params}
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT, **auth_headers}
        ) as client:

            async def request() -> httpx.Response:
                return await client.get(OPENALEX_URL, params=params)

            resp = await _with_one_retry(request, "OpenAlex")
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("OpenAlex search failed: %s", _openalex_error_text(e, api_key))
        if raise_on_failure:
            raise SearchFailed(f"OpenAlex: {_openalex_error_text(e, api_key)}") from e
        return []
    return [_openalex_hit(w) for w in data.get("results", [])[:k]]


async def openalex_oa_pdf_url(
    doi: str, *, mailto: Optional[str] = None, api_key: Optional[str] = None
) -> Optional[str]:
    """The best open-access PDF OpenAlex knows for ``doi``, or None."""
    doi = (doi or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
            break
    if not doi:
        return None
    params, auth_headers = _openalex_request_parts(mailto, api_key)
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT, **auth_headers}
        ) as client:
            resp = await client.get(f"{OPENALEX_URL}/doi:{doi}", params=params or None)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            work = resp.json()
    except Exception as e:
        logger.warning(
            "OpenAlex DOI lookup failed for %s: %s",
            doi,
            _openalex_error_text(e, api_key),
        )
        return None
    locations = [work.get("best_oa_location") or {}]
    locations += [loc or {} for loc in work.get("oa_locations") or []]
    for loc in locations:
        if loc.get("pdf_url"):
            return loc["pdf_url"]
    return None


def _arxiv_entry(entry: ET.Element) -> dict:
    def text(tag: str) -> str:
        el = entry.find(f"{_ATOM}{tag}")
        return (el.text or "").strip() if el is not None and el.text else ""

    arxiv_url = text("id")
    title = " ".join(text("title").split())
    summary = " ".join(text("summary").split())
    published = text("published")
    year = published[:4] if len(published) >= 4 and published[:4].isdigit() else None
    authors = [
        (a.find(f"{_ATOM}name").text or "").strip()
        for a in entry.findall(f"{_ATOM}author")
        if a.find(f"{_ATOM}name") is not None
    ]
    pdf_url = None
    for link in entry.findall(f"{_ATOM}link"):
        if link.get("title") == "pdf" or link.get("type") == "application/pdf":
            pdf_url = link.get("href")
            break
    return {
        "source_id": _source_id(None, arxiv_url),
        "title": title,
        "authors": [a for a in authors if a],
        "year": int(year) if year else None,
        "abstract": summary,
        "doi": None,
        "url": arxiv_url,
        "oa_pdf_url": pdf_url,
        "origin": "arxiv",
    }


# arXiv asks API clients for at most one request every 3 seconds, one
# connection at a time, across all of a client's machines, and answers 429
# past that. The gate is shared by every process on the host (the agent
# server and `python -m evals` run in the same container) and holds the lock
# for the whole request, so requests never overlap.
ARXIV_MIN_INTERVAL_S = 3.0
ARXIV_API_GATE = RateGate("arxiv-api", ARXIV_MIN_INTERVAL_S)


async def _arxiv_get(client: httpx.AsyncClient, params: dict) -> httpx.Response:
    """GET the arXiv API through ARXIV_API_GATE; one retry after a 429/503."""

    async def request() -> httpx.Response:
        async with ARXIV_API_GATE.slot():
            return await client.get(ARXIV_URL, params=params)

    return await _with_one_retry(request, "arXiv")


async def _with_one_retry(request, source: str) -> httpx.Response:
    """Send ``request()``; on a 429 or 503, wait and send it once more."""
    resp = await request()
    if resp.status_code not in _RETRY_STATUSES:
        return resp
    wait = _retry_after(resp)
    logger.info(
        "%s answered %s; retrying once in %.0f s", source, resp.status_code, wait
    )
    await asyncio.sleep(wait)
    return await request()


def _retry_after(resp: httpx.Response) -> float:
    """Retry-After in seconds (capped), or the default when absent or an
    HTTP date, which these APIs do not send."""
    value = resp.headers.get("Retry-After", "")
    try:
        return min(max(float(value), 0.0), _MAX_RETRY_AFTER_S)
    except ValueError:
        return _RETRY_AFTER_S


def _error_text(e: Exception) -> str:
    """``str(e)`` is empty for some httpx errors (timeouts); name the type."""
    return str(e).splitlines()[0] if str(e).strip() else type(e).__name__


async def search_arxiv(
    query: str, k: int = 5, *, raise_on_failure: bool = False
) -> List[dict]:
    """arXiv preprints matching ``query``; failure as for ``search_openalex``."""
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max(1, min(k, 30)),
    }
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT}
        ) as client:
            resp = await _arxiv_get(client, params)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
    except Exception as e:
        logger.warning("arXiv search failed: %s", _error_text(e))
        if raise_on_failure:
            raise SearchFailed(f"arXiv: {_error_text(e)}") from e
        return []
    return [_arxiv_entry(e) for e in root.findall(f"{_ATOM}entry")][:k]


def _dedupe_key(hit: dict) -> str:
    if hit.get("doi"):
        return "doi:" + hit["doi"]
    return "title:" + "".join(c for c in hit.get("title", "").lower() if c.isalnum())


async def search_scholarly(
    query: str,
    k: int = 10,
    *,
    mailto: Optional[str] = None,
    api_key: Optional[str] = None,
    arxiv: bool = True,
) -> List[dict]:
    """OpenAlex first (comprehensive index), then arXiv preprints to fill in
    (``arxiv=False`` skips it). Deduped by DOI/title, capped at ``k``.

    One source failing still returns the other's hits. Raises
    ``SearchFailed`` only when every source searched failed, so the caller
    can tell that apart from a search that found nothing."""
    searches = [
        search_openalex(
            query, k, mailto=mailto, api_key=api_key, raise_on_failure=True
        )
    ]
    if arxiv:
        searches.append(search_arxiv(query, max(3, k // 3), raise_on_failure=True))
    outcomes = await asyncio.gather(*searches, return_exceptions=True)
    for outcome in outcomes:
        if isinstance(outcome, BaseException) and not isinstance(outcome, SearchFailed):
            raise outcome
    failures = [o for o in outcomes if isinstance(o, SearchFailed)]
    if len(failures) == len(outcomes):
        raise SearchFailed("; ".join(str(f) for f in failures))
    openalex = outcomes[0] if not isinstance(outcomes[0], SearchFailed) else []
    arxiv_hits = (
        outcomes[1] if len(outcomes) > 1 and not isinstance(outcomes[1], SearchFailed) else []
    )

    merged: List[dict] = []
    seen = set()
    for hit in openalex + arxiv_hits:
        key = _dedupe_key(hit)
        if key in seen or not hit.get("title"):
            continue
        seen.add(key)
        merged.append(hit)
        if len(merged) >= k:
            break
    return merged
