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
"""OpenAlex/arXiv edge cases: empty DOIs, mailto, API key, failed lookups, merge caps."""

import asyncio

import httpx
import respx

from research_agent import scholarly


def test_a_doi_that_is_only_a_prefix_has_no_slug():
    assert scholarly._doi_slug("https://doi.org/") is None
    assert scholarly._doi_slug("doi:/") is None
    # With no slug the source id falls back to a hash of the URL.
    assert scholarly._source_id("https://doi.org/", "https://x.example").startswith("url_")


@respx.mock
def test_openalex_search_sends_mailto():
    route = respx.get(scholarly.OPENALEX_URL).mock(
        return_value=httpx.Response(200, json={"results": []})
    )

    hits = asyncio.run(scholarly.search_openalex("creep", 5, mailto="me@example.org"))

    assert hits == []
    assert route.calls.last.request.url.params["mailto"] == "me@example.org"


# --- OpenAlex API key -------------------------------------------------------

_KEY = "oa-test-key-123"


@respx.mock
def test_openalex_api_key_goes_in_the_header_never_the_url():
    search = respx.get(scholarly.OPENALEX_URL).mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    lookup = respx.get(f"{scholarly.OPENALEX_URL}/doi:10.1/abc").mock(
        return_value=httpx.Response(200, json={"best_oa_location": None})
    )

    asyncio.run(scholarly.search_openalex("creep", 5, api_key=_KEY))
    asyncio.run(scholarly.openalex_oa_pdf_url("10.1/abc", api_key=_KEY))

    for route in (search, lookup):
        request = route.calls.last.request
        assert request.headers["Authorization"] == f"Bearer {_KEY}"
        assert _KEY not in str(request.url)


@respx.mock
def test_search_scholarly_passes_the_key_to_openalex():
    route = respx.get(scholarly.OPENALEX_URL).mock(
        return_value=httpx.Response(200, json={"results": []})
    )

    asyncio.run(scholarly.search_scholarly("creep", 5, api_key=_KEY, arxiv=False))

    assert route.calls.last.request.headers["Authorization"] == f"Bearer {_KEY}"


@respx.mock
def test_without_a_key_no_authorization_header_is_sent():
    route = respx.get(scholarly.OPENALEX_URL).mock(
        return_value=httpx.Response(200, json={"results": []})
    )

    asyncio.run(scholarly.search_openalex("creep", 5))

    assert "Authorization" not in route.calls.last.request.headers


@respx.mock
def test_a_rejected_key_says_so_without_leaking_it(caplog):
    respx.get(scholarly.OPENALEX_URL).mock(return_value=httpx.Response(401))
    respx.get(f"{scholarly.OPENALEX_URL}/doi:10.1/abc").mock(
        return_value=httpx.Response(403)
    )

    try:
        asyncio.run(
            scholarly.search_openalex("creep", 5, api_key=_KEY, raise_on_failure=True)
        )
    except scholarly.SearchFailed as e:
        message = str(e)
    else:
        raise AssertionError("a 401 should raise SearchFailed")
    assert asyncio.run(scholarly.openalex_oa_pdf_url("10.1/abc", api_key=_KEY)) is None

    assert "OpenAlex rejected OPENALEX_API_KEY" in message
    assert caplog.text.count("OpenAlex rejected OPENALEX_API_KEY") == 2
    assert _KEY not in message and _KEY not in caplog.text


@respx.mock
def test_a_401_without_a_key_does_not_blame_the_key(caplog):
    respx.get(scholarly.OPENALEX_URL).mock(return_value=httpx.Response(401))

    asyncio.run(scholarly.search_openalex("creep", 5))

    assert "OpenAlex search failed" in caplog.text
    assert "OPENALEX_API_KEY" not in caplog.text


def test_the_key_is_read_from_the_environment_and_kept_out_of_repr(monkeypatch):
    from research_agent.core.config import AgentConfig

    monkeypatch.setenv("OPENALEX_API_KEY", f"  {_KEY}\n")
    config = AgentConfig.from_env()
    assert config.openalex_api_key == _KEY
    assert _KEY not in repr(config)

    monkeypatch.setenv("OPENALEX_API_KEY", "   ")
    assert AgentConfig.from_env().openalex_api_key is None
    monkeypatch.delenv("OPENALEX_API_KEY")
    assert AgentConfig.from_env().openalex_api_key is None


@respx.mock
def test_openalex_doi_lookup_failure_returns_none(caplog):
    respx.get(f"{scholarly.OPENALEX_URL}/doi:10.1/boom").mock(
        return_value=httpx.Response(500)
    )

    assert asyncio.run(scholarly.openalex_oa_pdf_url("doi:10.1/boom")) is None
    assert "OpenAlex DOI lookup failed for 10.1/boom" in caplog.text


@respx.mock
def test_openalex_doi_lookup_without_any_pdf_returns_none():
    respx.get(f"{scholarly.OPENALEX_URL}/doi:10.1/nopdf").mock(
        return_value=httpx.Response(
            200,
            json={"best_oa_location": None, "oa_locations": [None, {"pdf_url": ""}]},
        )
    )

    assert asyncio.run(scholarly.openalex_oa_pdf_url("10.1/nopdf")) is None


def _fake_sources(monkeypatch, openalex, arxiv, semantic=()):
    """Fake every source; a source given as an exception fails with it.
    Semantic search defaults to finding nothing."""

    def fake(result):
        async def search(query, k, *, mailto=None, api_key=None, raise_on_failure=False):
            if isinstance(result, BaseException):
                raise result
            return list(result)

        return search

    async def fake_arxiv(query, k, *, raise_on_failure=False):
        if isinstance(arxiv, BaseException):
            raise arxiv
        return arxiv

    monkeypatch.setattr(scholarly, "search_openalex", fake(openalex))
    monkeypatch.setattr(scholarly, "search_openalex_semantic", fake(semantic))
    monkeypatch.setattr(scholarly, "search_arxiv", fake_arxiv)


def test_search_scholarly_drops_untitled_and_duplicate_hits(monkeypatch):
    _fake_sources(
        monkeypatch,
        [{"title": "Creep", "doi": "10.1_a"}, {"title": "", "doi": "10.1_b"}],
        [{"title": "creep", "doi": "10.1_a"}, {"title": "Swelling"}],
    )

    out = asyncio.run(scholarly.search_scholarly("creep", 10))

    assert [h["title"] for h in out] == ["Creep", "Swelling"]


def test_search_scholarly_stops_at_k(monkeypatch):
    _fake_sources(
        monkeypatch,
        [{"title": f"Paper {i}", "doi": f"10.1_{i}"} for i in range(4)],
        [{"title": "Preprint"}],
    )

    out = asyncio.run(scholarly.search_scholarly("creep", 2))

    # arXiv only fills slots OpenAlex leaves; here there are none.
    assert [h["title"] for h in out] == ["Paper 0", "Paper 1"]


# --- OpenAlex semantic search and RRF ---------------------------------------


def _hits(*names):
    return [{"title": n, "doi": f"10.1/{n}"} for n in names]


def test_rrf_puts_a_paper_both_lists_found_first():
    keyword = _hits("A", "B", "C")
    semantic = _hits("D", "C", "E")

    out = scholarly.rrf_merge([keyword, semantic], 10)

    # C: 1/63 + 1/62 beats any single first place (1/61); A and D tie at 1/61,
    # and the tie keeps the earlier list first.
    assert [h["title"] for h in out] == ["C", "A", "D", "B", "E"]


def test_rrf_scores_match_the_formula():
    out = scholarly.rrf_merge([_hits("A", "B"), _hits("B")], 10)

    k = scholarly.RRF_K
    assert [h["title"] for h in out] == ["B", "A"]
    assert 1 / (k + 2) + 1 / (k + 1) > 1 / (k + 1)  # B (in both) > A (one list)


def test_rrf_counts_a_repeat_within_one_list_once_and_caps_at_k():
    out = scholarly.rrf_merge([_hits("A", "A", "B"), _hits("B")], 1)

    # The repeated A is skipped, so B is still rank 2 in the first list and
    # rank 1 in the second.
    assert [h["title"] for h in out] == ["B"]


def test_search_scholarly_fuses_keyword_and_semantic_results(monkeypatch):
    _fake_sources(monkeypatch, _hits("A", "B"), [], semantic=_hits("B", "C"))

    out = asyncio.run(scholarly.search_scholarly("creep", 10))

    assert [h["title"] for h in out] == ["B", "A", "C"]


def test_arxiv_fills_in_after_the_fused_openalex_results(monkeypatch):
    # arXiv's top hit would tie OpenAlex's top hit under RRF; it isn't fused,
    # so it comes after every OpenAlex result, and a duplicate is dropped.
    _fake_sources(
        monkeypatch,
        _hits("A", "B"),
        [{"title": "Preprint"}, {"title": "b", "doi": "10.1/B"}, {"title": ""}],
        semantic=_hits("C"),
    )

    out = asyncio.run(scholarly.search_scholarly("creep", 10))

    assert [h["title"] for h in out] == ["A", "C", "B", "Preprint"]


def test_semantic_search_can_be_skipped(monkeypatch):
    calls = []

    async def must_not_run(*args, **kwargs):
        calls.append(args)
        return []

    _fake_sources(monkeypatch, _hits("A"), [])
    monkeypatch.setattr(scholarly, "search_openalex_semantic", must_not_run)

    out = asyncio.run(scholarly.search_scholarly("creep", 5, semantic=False))

    assert [h["title"] for h in out] == ["A"] and calls == []


def test_one_semantic_failure_still_returns_keyword_hits(monkeypatch):
    _fake_sources(
        monkeypatch,
        _hits("A"),
        [],
        semantic=scholarly.SearchFailed("OpenAlex semantic: 429"),
    )

    assert [h["title"] for h in asyncio.run(scholarly.search_scholarly("q", 5))] == ["A"]


@respx.mock
def test_semantic_search_request_is_open_access_and_gated(monkeypatch):
    route = respx.get(scholarly.OPENALEX_URL).mock(
        return_value=httpx.Response(200, json={"results": [{"title": "Creep", "doi": None}]})
    )
    entered = []

    class Gate:
        def slot(self):
            import contextlib

            @contextlib.asynccontextmanager
            async def slot():
                entered.append(True)
                yield

            return slot()

    monkeypatch.setattr(scholarly, "OPENALEX_SEMANTIC_GATE", Gate())

    hits = asyncio.run(scholarly.search_openalex_semantic("creep of 316", 7, api_key=_KEY))

    params = route.calls.last.request.url.params
    assert params["search.semantic"] == "creep of 316"
    assert params["filter"] == "open_access.is_oa:true"
    assert params["per-page"] == "7" and "search" not in params
    assert route.calls.last.request.headers["Authorization"] == f"Bearer {_KEY}"
    assert entered == [True] and [h["title"] for h in hits] == ["Creep"]


@respx.mock
def test_semantic_search_failures_name_semantic_search(caplog):
    import pytest

    respx.get(scholarly.OPENALEX_URL).mock(return_value=httpx.Response(500))

    with pytest.raises(scholarly.SearchFailed, match="^OpenAlex semantic: "):
        asyncio.run(scholarly.search_openalex_semantic("q", 5, raise_on_failure=True))
    assert "OpenAlex semantic search failed" in caplog.text


def test_scholarly_semantic_setting(monkeypatch):
    from research_agent.core.config import AgentConfig

    assert AgentConfig.from_env().scholarly_semantic is True
    monkeypatch.setenv("SCHOLARLY_SEMANTIC", "false")
    assert AgentConfig.from_env().scholarly_semantic is False


# --- retries and failures ---------------------------------------------------


@respx.mock
def test_openalex_retries_once_after_a_429_or_503():
    for status in (429, 503):
        respx.reset()
        route = respx.get(scholarly.OPENALEX_URL).mock(
            side_effect=[
                httpx.Response(status, headers={"Retry-After": "0"}),
                httpx.Response(200, json={"results": [{"title": "Creep", "doi": None}]}),
            ]
        )

        hits = asyncio.run(scholarly.search_openalex("creep", 5))

        assert route.call_count == 2 and [h["title"] for h in hits] == ["Creep"]


@respx.mock
def test_openalex_gives_up_after_a_second_failure():
    route = respx.get(scholarly.OPENALEX_URL).mock(return_value=httpx.Response(503))

    assert asyncio.run(scholarly.search_openalex("creep", 5)) == []
    assert route.call_count == 2


@respx.mock
def test_openalex_does_not_retry_other_errors():
    route = respx.get(scholarly.OPENALEX_URL).mock(return_value=httpx.Response(500))

    asyncio.run(scholarly.search_openalex("creep", 5))

    assert route.call_count == 1


@respx.mock
def test_arxiv_retries_once_after_a_503():
    route = respx.get(scholarly.ARXIV_URL).mock(
        side_effect=[httpx.Response(503), httpx.Response(200, text="<feed/>")]
    )

    asyncio.run(scholarly.search_arxiv("creep", 5))

    assert route.call_count == 2


@respx.mock
def test_a_source_failure_can_be_raised_instead_of_returned_empty():
    respx.get(scholarly.OPENALEX_URL).mock(return_value=httpx.Response(500))
    respx.get(scholarly.ARXIV_URL).mock(side_effect=httpx.ReadTimeout(""))

    import pytest

    with pytest.raises(scholarly.SearchFailed, match="OpenAlex"):
        asyncio.run(scholarly.search_openalex("creep", 5, raise_on_failure=True))
    with pytest.raises(scholarly.SearchFailed, match="arXiv: ReadTimeout"):
        asyncio.run(scholarly.search_arxiv("creep", 5, raise_on_failure=True))


def test_one_source_failing_still_returns_the_other(monkeypatch):
    _fake_sources(monkeypatch, scholarly.SearchFailed("OpenAlex: 503"), [{"title": "Preprint"}])

    out = asyncio.run(scholarly.search_scholarly("creep", 5))

    assert [h["title"] for h in out] == ["Preprint"]


def test_every_source_failing_raises(monkeypatch):
    import pytest

    _fake_sources(
        monkeypatch,
        scholarly.SearchFailed("OpenAlex: 503"),
        scholarly.SearchFailed("arXiv: ReadTimeout"),
        semantic=scholarly.SearchFailed("OpenAlex semantic: 429"),
    )

    with pytest.raises(scholarly.SearchFailed) as raised:
        asyncio.run(scholarly.search_scholarly("creep", 5))

    message = str(raised.value)
    assert "OpenAlex: 503" in message and "arXiv: ReadTimeout" in message
    assert "OpenAlex semantic: 429" in message


def test_openalex_failing_with_arxiv_off_raises(monkeypatch):
    import pytest

    _fake_sources(monkeypatch, scholarly.SearchFailed("OpenAlex: 429"), [])

    with pytest.raises(scholarly.SearchFailed, match="OpenAlex: 429"):
        asyncio.run(scholarly.search_scholarly("creep", 5, arxiv=False, semantic=False))


def test_a_found_nothing_search_is_not_a_failure(monkeypatch):
    _fake_sources(monkeypatch, [], [])

    assert asyncio.run(scholarly.search_scholarly("creep", 5)) == []


def test_an_unexpected_error_is_not_swallowed(monkeypatch):
    import pytest

    _fake_sources(monkeypatch, ValueError("bug"), [])

    with pytest.raises(ValueError, match="bug"):
        asyncio.run(scholarly.search_scholarly("creep", 5))
