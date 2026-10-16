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

"""Provider-agnostic LLM client utilities built on LiteLLM."""

from .client import AsyncLLMClient, LLMClient
from .config import FallbackModelConfig, LLMConfig
from .exceptions import (
    LLMAliasError,
    LLMClientError,
    LLMConfigError,
    LLMEndpointUnavailableError,
    LLMProviderError,
    LLMToolCallError,
)
from .models import ChatResponse, EmbeddingResponse
from .normalization import normalize_embedding_input, normalize_messages
from .security import extract_llm_api_key_from_a2a_context, redact_secrets
from .tools import (
    ToolCall,
    ToolDefinition,
    acall_tool,
    assistant_message,
    call_tool,
    parse_finish_reason,
    parse_tool_calls,
    require_tool_calls,
    tool_result_message,
    tool_schemas,
)
from .tracing import MLFLOW_API_KEY_ENV, enable_mlflow_x_api_key

__all__ = [
    "AsyncLLMClient",
    "ChatResponse",
    "EmbeddingResponse",
    "FallbackModelConfig",
    "LLMAliasError",
    "LLMClient",
    "LLMClientError",
    "LLMConfigError",
    "LLMEndpointUnavailableError",
    "LLMProviderError",
    "LLMConfig",
    "LLMToolCallError",
    "ToolCall",
    "ToolDefinition",
    "MLFLOW_API_KEY_ENV",
    "acall_tool",
    "assistant_message",
    "call_tool",
    "enable_mlflow_x_api_key",
    "extract_llm_api_key_from_a2a_context",
    "normalize_embedding_input",
    "normalize_messages",
    "parse_finish_reason",
    "parse_tool_calls",
    "redact_secrets",
    "require_tool_calls",
    "tool_result_message",
    "tool_schemas",
]
