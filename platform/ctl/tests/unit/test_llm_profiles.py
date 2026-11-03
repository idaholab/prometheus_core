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

from __future__ import annotations

from pathlib import Path

import pytest

from platformctl import llm_profiles

SDK_PROFILES = Path(__file__).resolve().parents[4] / "sdk" / "prometheus_api" / "llm_configs"
"""The real profile folder, next to `platform/` in the repository."""


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    """A profile folder with a keyed profile, a keyless one, one using the embedding key, and `registry`."""
    root = tmp_path / "llm_configs"
    root.mkdir()
    (root / "alpha.yaml").write_text("# Alpha inference scaffold. More text.\nkey: os.environ/LLM_API_KEY\n")
    (root / "keyless.yaml").write_text("# Local models. Nothing else.\napi_key: none\n")
    (root / "embed.yaml").write_text(
        "# Embeds. x\na: os.environ/EMBEDDING_API_KEY\nb: os.environ/EMBEDDING_API_KEY\nc: os.environ/OTHER_API_KEY\n"
    )
    (root / "registry.yaml").write_text("# Proxy. x\nk: os.environ/LLM_API_KEY\n")
    return root


def test_profiles_are_sorted_and_leave_out_the_unsupported_one(folder):
    """Each profile maps to its key and description; "registry" is not offered."""
    assert llm_profiles.profiles(folder) == {
        "alpha": ("LLM_API_KEY", "Alpha"),
        "embed": ("OTHER_API_KEY", "Embeds"),
        "keyless": (None, "Local models"),
    }


def test_a_missing_folder_is_an_error_naming_it(tmp_path):
    """No profile folder is a clear error, not an empty menu."""
    with pytest.raises(llm_profiles.ProfilesError, match="not found at"):
        llm_profiles.profiles(tmp_path / "nope")


def test_description_of_a_yaml_without_a_comment(tmp_path):
    """A config with no header comment has an empty description."""
    yaml = tmp_path / "x.yaml"
    yaml.write_text("key: value\n")
    assert llm_profiles.description(yaml) == ""


def test_missing_profile_needs_neither_a_profile_nor_a_custom_file():
    """A custom YAML replaces the profile."""
    assert llm_profiles.missing_profile({})
    assert llm_profiles.missing_profile({"LLM_CONFIG_PROFILE": "", "LLM_CONFIG_FILE": ""})
    assert not llm_profiles.missing_profile({"LLM_CONFIG_PROFILE": "alpha"})
    assert not llm_profiles.missing_profile({"LLM_CONFIG_FILE": "/c.yaml"})


def test_unknown_profile(folder):
    """A profile with no installed YAML is reported; a blank one or a custom file is not."""
    known = llm_profiles.profiles(folder)
    assert llm_profiles.unknown_profile({"LLM_CONFIG_PROFILE": "genisis"}, known) == "genisis"
    assert llm_profiles.unknown_profile({"LLM_CONFIG_PROFILE": "registry"}, known) == "registry"
    assert llm_profiles.unknown_profile({"LLM_CONFIG_PROFILE": "alpha"}, known) is None
    assert llm_profiles.unknown_profile({}, known) is None
    assert llm_profiles.unknown_profile({"LLM_CONFIG_PROFILE": "x", "LLM_CONFIG_FILE": "/c.yaml"}, known) is None


def test_missing_llm_key(folder):
    """The blank key the profile needs; none for a keyless profile or a custom file."""
    known = llm_profiles.profiles(folder)
    assert llm_profiles.missing_llm_key({"LLM_CONFIG_PROFILE": "alpha"}, known) == "LLM_API_KEY"
    assert llm_profiles.missing_llm_key({"LLM_CONFIG_PROFILE": "alpha", "LLM_API_KEY": "k"}, known) is None
    assert llm_profiles.missing_llm_key({"LLM_CONFIG_PROFILE": "keyless"}, known) is None
    assert llm_profiles.missing_llm_key({"LLM_CONFIG_PROFILE": "alpha", "LLM_CONFIG_FILE": "/c"}, known) is None
    assert llm_profiles.missing_llm_key({}, known) is None


def test_profiles_match_the_sdk_llm_configs():
    """Every installed profile but "registry" is offered; all but the keyless ollama read LLM_API_KEY."""
    known = llm_profiles.profiles(SDK_PROFILES)
    installed = {p.stem for p in SDK_PROFILES.glob("*.yaml")}
    assert list(known) == sorted(installed - {"registry"})
    # EMBEDDING_API_KEY is never the profile key. Only the keyless local ollama profile needs no key.
    assert [name for name, (key, _) in known.items() if key is None] == ["ollama"]
    for name, (key, _) in known.items():
        if name != "ollama":
            assert key == "LLM_API_KEY", f"{name} must read LLM_API_KEY"
