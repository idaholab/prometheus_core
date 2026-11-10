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

"""specs/001-storage-configuration-and-authentication.md, through `ConnectionConfig`."""

import pydantic
import pytest

from prometheus_api.storage_client import ConnectionConfig

IDS = {"organization_id": 1, "project_id": 2}
"""The org and project every case passes unless it is testing one missing."""


@pytest.mark.parametrize(
    ("auth", "expected"),
    [
        pytest.param(
            {"jwt_token": "token"},
            {"jwt_token": "token", "api_key": None, "api_secret": None},
            marks=pytest.mark.covers(
                "REQ-001-01",
                "a config with the org, the project and only a jwt_token is built, "
                "and keeps the token with no API key or secret",
            ),
            id="jwt",
        ),
        pytest.param(
            {"api_key": "key", "api_secret": "secret"},
            {"jwt_token": None, "api_key": "key", "api_secret": "secret"},
            marks=pytest.mark.covers(
                "REQ-001-01",
                "a config with the org, the project and only an api_key and api_secret "
                "is built, and keeps the pair with no jwt_token",
            ),
            id="api-key",
        ),
    ],
)
def test_one_auth_method_is_accepted(auth, expected):
    """Either auth method on its own, with the org and project, makes a config holding just it."""
    config = ConnectionConfig(**IDS, **auth)
    assert config.organization_id == 1
    assert config.project_id == 2
    assert {name: getattr(config, name) for name in expected} == expected


@pytest.mark.parametrize(
    "missing",
    [
        pytest.param(
            "organization_id",
            marks=pytest.mark.covers(
                "REQ-001-01",
                "leaving out organization_id, with either valid auth method, fails "
                "validation naming only organization_id as a missing field",
            ),
            id="organization_id",
        ),
        pytest.param(
            "project_id",
            marks=pytest.mark.covers(
                "REQ-001-01",
                "leaving out project_id, with either valid auth method, fails "
                "validation naming only project_id as a missing field",
            ),
            id="project_id",
        ),
    ],
)
def test_the_org_and_project_are_required(missing):
    """Each ID is required on its own, with either auth method valid."""
    for auth in ({"jwt_token": "token"}, {"api_key": "key", "api_secret": "secret"}):
        kwargs = {**IDS, **auth}
        del kwargs[missing]
        with pytest.raises(pydantic.ValidationError) as caught:
            ConnectionConfig(**kwargs)
        errors = caught.value.errors()
        assert [(e["type"], e["loc"]) for e in errors] == [("missing", (missing,))], auth


@pytest.mark.parametrize(
    ("auth", "message"),
    [
        pytest.param(
            {},
            "Must provide either jwt_token or both api_key and api_secret",
            marks=pytest.mark.covers(
                "REQ-001-01",
                "a config with the org and project but no credentials at all fails "
                "validation saying to give a jwt_token or both api_key and api_secret",
            ),
            id="none",
        ),
        pytest.param(
            {"api_key": "key"},
            "Must provide either jwt_token or both api_key and api_secret",
            marks=pytest.mark.covers(
                "REQ-001-01",
                "an api_key without its api_secret fails validation, so half a key pair "
                "is not an auth method",
            ),
            id="api_key-only",
        ),
        pytest.param(
            {"api_secret": "secret"},
            "Must provide either jwt_token or both api_key and api_secret",
            marks=pytest.mark.covers(
                "REQ-001-01",
                "an api_secret without its api_key fails validation, so half a key pair "
                "is not an auth method",
            ),
            id="api_secret-only",
        ),
        pytest.param(
            {"jwt_token": "token", "api_key": "key", "api_secret": "secret"},
            "Cannot provide both jwt_token and api_key/api_secret",
            marks=pytest.mark.covers(
                "REQ-001-01",
                "a jwt_token together with a full api_key and api_secret fails validation, "
                "so two auth methods at once are refused",
            ),
            id="jwt-and-pair",
        ),
    ],
)
def test_anything_but_exactly_one_auth_method_is_refused(auth, message):
    """No auth, half a key pair, or both full auth methods is a validation error."""
    with pytest.raises(pydantic.ValidationError, match=message):
        ConnectionConfig(**IDS, **auth)
