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
"""Malformed URLs are neither given a host nor allowed for download."""

from research_agent import download_policy


def test_host_of_a_malformed_url_is_empty():
    assert download_policy.host_of("http://[::1") == ""
    assert download_policy.host_of("https://OSTI.gov/x.pdf") == "osti.gov"


def test_a_malformed_url_is_not_allowed():
    domains = download_policy.DEFAULT_ALLOWED_DOMAINS

    assert download_policy.url_allowed("https://[osti.gov/x.pdf", domains) is False
    assert download_policy.url_allowed("https://www.osti.gov/x.pdf", domains) is True
