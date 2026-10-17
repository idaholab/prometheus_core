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

"""Paths for LLM configuration profiles installed with prometheus-api."""

from __future__ import annotations

from pathlib import Path


_CONFIG_DIR = Path(__file__).resolve().parent


def list_llm_config_profiles() -> tuple[str, ...]:
    """Return the names of every YAML profile installed in this directory."""
    return tuple(sorted(path.stem for path in _CONFIG_DIR.glob("*.yaml")))


def get_llm_config_path(profile: str = "registry") -> Path:
    """Return the installed YAML path for a named LLM configuration profile."""
    normalized = str(profile).strip().lower().removesuffix(".yaml").replace("-", "_")
    profiles = list_llm_config_profiles()
    if normalized not in profiles:
        available = ", ".join(profiles)
        raise ValueError(
            f"Unknown LLM config profile {profile!r}. Available profiles: {available}."
        )
    return _CONFIG_DIR / f"{normalized}.yaml"


__all__ = ["get_llm_config_path", "list_llm_config_profiles"]
