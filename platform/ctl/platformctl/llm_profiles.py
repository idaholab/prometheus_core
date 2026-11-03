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

"""The LLM profiles the SDK installs, and which API key each one needs.

Ported from `scripts/init_env.py`. One profile per YAML in `sdk/prometheus_api/llm_configs`.
"""

from __future__ import annotations

import re
from pathlib import Path

UNSUPPORTED_PROFILES = {"registry"}
"""Installed by the SDK but unusable here: "registry" sends LLM calls to `REGISTRY_URL`, which on this
platform is the backend's agent registry, not an LLM proxy."""

API_KEY_REF = re.compile(r"os\.environ/([A-Z][A-Z0-9_]*_API_KEY)")
"""A reference to an API key in a profile's YAML."""
EMBEDDING_KEY = "EMBEDDING_API_KEY"
"""Shared by several profiles for embeddings only; never the key a profile needs."""


class ProfilesError(RuntimeError):
    """The profile folder is missing."""


def provider_key(yaml: Path) -> str | None:
    """The API key a config references most often, ignoring the embedding key."""
    refs = [k for k in API_KEY_REF.findall(yaml.read_text()) if k != EMBEDDING_KEY]
    return max(set(refs), key=refs.count) if refs else None


def description(yaml: Path) -> str:
    """The first sentence of the config's header comment, minus "inference scaffold"."""
    first = next((line for line in yaml.read_text().splitlines() if line.startswith("#")), "#")
    sentence = first.lstrip("# ").split(". ")[0].rstrip(".")
    return re.sub(r"\s*inference scaffold$", "", sentence)


def profiles(folder: Path) -> dict[str, tuple[str | None, str]]:
    """LLM_CONFIG_PROFILE -> (provider key it cannot start without, description), alphabetically."""
    if not folder.is_dir():
        raise ProfilesError(f"LLM config profiles not found at {folder}.")
    return {
        yaml.stem: (provider_key(yaml), description(yaml))
        for yaml in sorted(folder.glob("*.yaml"))
        if yaml.stem not in UNSUPPORTED_PROFILES
    }


def missing_profile(env: dict[str, str]) -> bool:
    """True if neither LLM_CONFIG_PROFILE nor a custom LLM_CONFIG_FILE is set."""
    return not env.get("LLM_CONFIG_FILE") and not env.get("LLM_CONFIG_PROFILE")


def unknown_profile(env: dict[str, str], known: dict[str, tuple[str | None, str]]) -> str | None:
    """The selected LLM_CONFIG_PROFILE if no usable installed profile has that name."""
    if env.get("LLM_CONFIG_FILE") or not env.get("LLM_CONFIG_PROFILE"):
        return None  # a custom YAML replaces the profile; a blank one is missing_profile
    profile = env["LLM_CONFIG_PROFILE"]
    return None if profile in known else profile


def missing_llm_key(env: dict[str, str], known: dict[str, tuple[str | None, str]]) -> str | None:
    """The blank provider key required by the selected profile, if any."""
    if env.get("LLM_CONFIG_FILE"):
        return None  # a custom YAML decides which keys it needs
    key, _ = known.get(env.get("LLM_CONFIG_PROFILE", ""), (None, ""))
    return key if key and not env.get(key) else None
