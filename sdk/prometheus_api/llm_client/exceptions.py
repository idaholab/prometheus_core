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

"""Exceptions raised by the provider-agnostic LLM client."""


class LLMClientError(RuntimeError):
    """Base error for LLM client failures."""


class LLMConfigError(LLMClientError, ValueError):
    """Raised when the selected LLM profile or config file cannot be loaded."""


class LLMEndpointUnavailableError(LLMClientError):
    """Raised when the configured LLM proxy or provider endpoint cannot be reached."""


class LLMAliasError(ValueError):
    """Raised when a configured model alias is unavailable."""


class LLMToolCallError(LLMClientError):
    """Raised when an LLM tool-call response does not satisfy the caller's contract."""
