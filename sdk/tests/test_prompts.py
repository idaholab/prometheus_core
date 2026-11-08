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

import importlib.util
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


def _define_agent_in(module_dir, body=""):
    """Write an agent module under module_dir, import it, and return its agent class."""
    module_dir.mkdir(parents=True, exist_ok=True)
    source = module_dir / "agent_module.py"
    source.write_text(
        "from prometheus_api.agent import PrometheusAgent\n\n"
        f"class SampleAgent(PrometheusAgent):\n    pass\n{body}",
        encoding="utf-8",
    )
    name = f"agent_module_{abs(hash(module_dir))}"
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # as for any imported module; inspect.getfile looks here
    spec.loader.exec_module(module)
    return module.SampleAgent


def test_agent_load_prompt_defaults_to_prompts_next_to_class_module(tmp_path, monkeypatch):
    """Covers REQ-009-23."""
    agent_cls = _define_agent_in(tmp_path / "agent")
    (tmp_path / "agent" / "prompts").mkdir()
    (tmp_path / "agent" / "prompts" / "system.txt").write_text("\nclass prompt\n", encoding="utf-8")
    # A different entrypoint must not change where the agent's prompts come from
    main_module = types.ModuleType("__main__")
    main_module.__file__ = str(tmp_path / "elsewhere" / "run.py")
    monkeypatch.setitem(sys.modules, "__main__", main_module)

    assert agent_cls.resolve_prompts_dir() == (tmp_path / "agent" / "prompts").resolve()
    assert agent_cls.load_prompt("system.txt") == "class prompt"
    assert agent_cls.load_prompt("system.txt", strip=False) == "\nclass prompt\n"


def test_agent_prompts_dir_relative_and_absolute(tmp_path):
    """Covers REQ-009-24."""
    relative = _define_agent_in(tmp_path / "rel")
    relative.prompts_dir = "templates/llm"
    (tmp_path / "rel" / "templates" / "llm").mkdir(parents=True)
    (tmp_path / "rel" / "templates" / "llm" / "a.txt").write_text("relative", encoding="utf-8")

    absolute = _define_agent_in(tmp_path / "abs")
    absolute.prompts_dir = tmp_path / "shared"
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared" / "a.txt").write_text("absolute", encoding="utf-8")

    assert relative.load_prompt("a.txt") == "relative"
    assert absolute.load_prompt("a.txt") == "absolute"


def test_agent_load_prompt_keeps_path_rules(tmp_path):
    """Covers REQ-009-24."""
    agent_cls = _define_agent_in(tmp_path / "agent")
    (tmp_path / "agent" / "prompts").mkdir()

    with pytest.raises(ValueError, match="escapes prompt directory"):
        agent_cls.load_prompt("../agent_module.py")
    with pytest.raises(FileNotFoundError):
        agent_cls.load_prompt("missing.txt")


def test_agent_without_source_file_falls_back_to_entrypoint(tmp_path, monkeypatch):
    """Covers REQ-009-25."""
    from prometheus_api.agent import PrometheusAgent

    interactive = type("InteractiveAgent", (PrometheusAgent,), {"__module__": "__interactive__"})
    entrypoint = tmp_path / "agent.py"
    entrypoint.write_text("# entrypoint\n", encoding="utf-8")
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "system.txt").write_text("entrypoint prompt", encoding="utf-8")
    main_module = types.ModuleType("__main__")
    main_module.__file__ = str(entrypoint)
    monkeypatch.setitem(sys.modules, "__main__", main_module)

    assert interactive.resolve_prompts_dir() is None
    assert interactive.load_prompt("system.txt") == "entrypoint prompt"
