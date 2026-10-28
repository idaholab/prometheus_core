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

"""Coverage for the judge's score parsing edge cases and its completion factory."""

from types import SimpleNamespace

import pytest

from evals import judge
from research_agent.core.llm import LiteLLMClient


def test_a_boolean_score_is_not_a_score():
    assert judge._score(True) is None
    assert judge._score(False) is None
    assert judge._score(4.6) == 5


def test_broken_json_with_no_readable_fields_is_rejected():
    with pytest.raises(ValueError, match="judge reply is not valid JSON"):
        judge.parse_verdict("{not, json}", has_notes=False)


def test_make_complete_uses_the_verifier_route():
    routes = []

    class _Config:
        def model_route(self, name):
            routes.append(name)
            return SimpleNamespace(base_url="http://verifier:4000/", api_key="k",
                                   model="judge-model")

    complete = judge.make_complete(_Config())

    assert routes == ["verifier"]
    client = complete.__self__
    assert isinstance(client, LiteLLMClient)
    assert complete.__func__ is LiteLLMClient.complete
    assert (client._base_url, client._api_key, client._model) == (
        "http://verifier:4000", "k", "judge-model"
    )
