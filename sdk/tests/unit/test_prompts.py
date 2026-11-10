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

import sys
import types

import pytest

from prometheus_api import load_prompt as top_level_load_prompt
from prometheus_api.prompts import load_prompt


def test_load_prompt_reads_from_explicit_prompt_directory(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "system_prompt.txt").write_text("\nHello {name}\n", encoding="utf-8")

    assert load_prompt("system_prompt.txt", prompts_dir=prompts_dir) == "Hello {name}"


def test_load_prompt_can_preserve_whitespace(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "system_prompt.txt").write_text("\nKeep spacing\n", encoding="utf-8")

    assert (
        load_prompt("system_prompt.txt", prompts_dir=prompts_dir, strip=False) == "\nKeep spacing\n"
    )


def test_load_prompt_defaults_to_prompts_next_to_entrypoint(tmp_path, monkeypatch):
    entrypoint = tmp_path / "agent.py"
    entrypoint.write_text("# test entrypoint\n", encoding="utf-8")
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "system_prompt.txt").write_text("default prompt", encoding="utf-8")

    main_module = types.ModuleType("__main__")
    main_module.__file__ = str(entrypoint)
    monkeypatch.setitem(sys.modules, "__main__", main_module)

    assert load_prompt("system_prompt.txt") == "default prompt"


def test_load_prompt_supports_nested_prompt_paths(tmp_path):
    prompts_dir = tmp_path / "prompts"
    nested_dir = prompts_dir / "nested"
    nested_dir.mkdir(parents=True)
    (nested_dir / "analysis.txt").write_text("nested prompt", encoding="utf-8")

    assert load_prompt("nested/analysis.txt", prompts_dir=prompts_dir) == "nested prompt"


def test_load_prompt_missing_file_fails_fast(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()

    with pytest.raises(FileNotFoundError):
        load_prompt("missing.txt", prompts_dir=prompts_dir)


def test_load_prompt_rejects_absolute_prompt_paths(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    outside_prompt = tmp_path / "outside.txt"

    with pytest.raises(ValueError, match="relative path"):
        load_prompt(outside_prompt, prompts_dir=prompts_dir)


def test_load_prompt_rejects_paths_outside_prompt_directory(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()

    with pytest.raises(ValueError, match="escapes prompt directory"):
        load_prompt("../outside.txt", prompts_dir=prompts_dir)


def test_load_prompt_is_reexported_from_top_level_package():
    assert top_level_load_prompt is load_prompt
