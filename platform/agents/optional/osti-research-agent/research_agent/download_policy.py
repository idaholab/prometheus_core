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

"""Which hosts the agent may download PDFs from.

Only hosts on the allowlist are fetched: many publishers refuse scripted
downloads (HTTP 403), and every refused download costs the run a turn. The
OSTI purl path (``osti_client.download_paper``) is not a URL download and is
always allowed. A listed domain also allows its subdomains, so ``arxiv.org``
covers ``export.arxiv.org``.

Override the list with ``DOWNLOAD_ALLOWED_DOMAINS`` (comma separated). Hosts
that refuse a download (401/403) are also dropped for the rest of the run.
"""

from __future__ import annotations

from typing import Iterable, Optional, Tuple
from urllib.parse import urlsplit

# Hosts that serve open-access PDFs to scripted clients.
DEFAULT_ALLOWED_DOMAINS: Tuple[str, ...] = (
    "osti.gov",
    "arxiv.org",
    "europepmc.org",
    "ncbi.nlm.nih.gov",
    "nrc.gov",
    "oecd-nea.org",
    "iaea.org",
    "inis.iaea.org",
    "zenodo.org",
    "hal.science",
    "osf.io",
)


def parse_domains(raw: Optional[str]) -> Tuple[str, ...]:
    """``"a.org, B.org ,"`` -> ``("a.org", "b.org")``; None or "" -> defaults."""
    if not raw or not raw.strip():
        return DEFAULT_ALLOWED_DOMAINS
    return tuple(
        d.strip().lower().lstrip(".") for d in raw.split(",") if d.strip()
    )


def host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def host_allowed(host: str, domains: Iterable[str]) -> bool:
    host = host.lower().rstrip(".")
    return bool(host) and any(
        host == domain or host.endswith("." + domain) for domain in domains
    )


def url_allowed(url: str, domains: Iterable[str]) -> bool:
    """True for an http(s) URL on an allowed host."""
    if not url:
        return False
    try:
        scheme = urlsplit(url).scheme.lower()
    except ValueError:
        return False
    return scheme in ("http", "https") and host_allowed(host_of(url), domains)
