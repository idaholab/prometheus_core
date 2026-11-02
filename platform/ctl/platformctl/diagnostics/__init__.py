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

"""The doctor framework and the checks it runs."""

from __future__ import annotations

from platformctl.diagnostics import docker_checks, env_checks, host_checks
from platformctl.diagnostics.base import Registry


def default_registry() -> Registry:
    """Every check, in an order where each check's dependencies come first."""
    registry = Registry()
    for check in (
        docker_checks.DOCKER,
        docker_checks.BUILD_CACHE_STORE,
        env_checks.PLATFORM_ENV,
        env_checks.BASE_IMAGE_PIN,
        env_checks.ENV_HIDES_ENVIRONMENT,
        env_checks.ENV_DERIVED_KEYS,
        env_checks.ENV_FILE,
        host_checks.PORTS_FREE,
        host_checks.CHECKOUT_PATH,
    ):
        registry.add(check)
    registry.validate()
    return registry
