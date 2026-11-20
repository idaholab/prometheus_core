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

"""Framework variants of a design pattern, written as ``pattern_<framework>.py``.

With ``--framework <slug>`` the scaffolder writes a second module next to
``agent.py`` that builds the chosen pattern's steps with that framework's own
primitives (a LangGraph ``StateGraph``, a CrewAI ``Crew``, Strands tools, ...).
``agent.py`` keeps its ``PrometheusAgent`` and calls the module's
``run_framework`` from ``_run_pattern``, so the A2A contract, auth and
registration stay with the platform.

Each module imports only its framework, and nothing in it runs at import time
except imports, so the generated agent's tests pass once the framework is
installed. The framework's package is added to the agent's pyproject.
"""

from __future__ import annotations

from collections.abc import Callable

from patterns import Architecture, Framework

Fragment = Callable[[Architecture, str, str], str]


def _header(
    arch: Architecture, fw: Framework, agent_name: str, description: str, imports: str, stdlib: str = ""
) -> str:
    stdlib_block = "\n".join(sorted([*(stdlib.splitlines() if stdlib else []), "from typing import Any"]))
    return (
        f'"""{arch.name} pattern for {agent_name}, built with {fw.name}.\n\n'
        f"{description}\n\n"
        f"{arch.name}: {arch.description}\n"
        f"{fw.name}: {fw.base_entrypoint}. Docs: {fw.docs}\n\n"
        "agent.py calls ``run_framework(task)``; fill each TODO(author).\n"
        '"""\n\n'
        "from __future__ import annotations\n\n"
        f"{stdlib_block}\n\n"
        f"{imports}\n\n\n"
        "def _call_model(prompt: str) -> str:\n"
        '    """The one place a framework step calls an LLM directly.\n\n'
        "    TODO(author): call your model, or return the prompt for the framework's\n"
        "    own LLM to handle. The platform's configured LLM is available through\n"
        "    ``prometheus_api.llm_client.LLMClient``.\n"
        '    """\n'
        '    raise NotImplementedError("Wire _call_model to your LLM.")\n'
    )


def _q(text: str) -> str:
    """Make text safe inside a double-quoted Python string."""
    return text.replace("\\", "\\\\").replace('"', "'")


def _tool_functions(arch: Architecture, decorator: str, args_doc: bool = False) -> tuple[str, list[str]]:
    fns, names = [], []
    for node, desc in arch.steps:
        name = f"step_{node}"
        names.append(name)
        doc = f"Step `{node}`: {_q(desc)}"
        if args_doc:
            doc += "\n\n    Args:\n        context: The task or the previous step's output.\n    "
        fns.append(
            f"\n\n@{decorator}\n"
            f"def {name}(context: str) -> str:\n"
            f'    """{doc}"""\n'
            f"    # TODO(author): implement `{node}`.\n"
            f'    return f"{node}: {{context}}"\n'
        )
    return "".join(fns), names


def _langgraph(arch: Architecture, agent_name: str, description: str, fw: Framework) -> str:
    steps = [n for n, _ in arch.steps]
    out = _header(
        arch,
        fw,
        agent_name,
        description,
        "from langgraph.graph import END, StateGraph",
        stdlib="from typing import TypedDict",
    )
    fields = "\n".join(f"    {n}: Any" for n in steps)
    out += (
        "\n\nclass PatternState(TypedDict, total=False):\n"
        '    """State flowing through the graph."""\n\n'
        f"    task: str\n{fields}\n    iterations: int\n"
    )
    for node, desc in arch.steps:
        out += (
            f"\n\ndef _node_{node}(state: PatternState) -> dict[str, Any]:\n"
            f'    """Graph node `{node}`: {_q(desc)}"""\n'
            f"    # TODO(author): implement `{node}`.\n"
            f'    return {{"{node}": state.get("{node}"), '
            f'"iterations": state.get("iterations", 0) + {int(node == steps[-1])}}}\n'
        )
    looped = arch.topology in ("loop", "cycle") and len(steps) >= 2
    if looped:
        back = steps[0] if arch.topology == "loop" else steps[-2]
        out += (
            "\n\ndef _should_continue(state: PatternState) -> str:\n"
            f'    """Back-edge `{steps[-1]}` -> `{back}` until done or 3 iterations."""\n'
            '    # TODO(author): return "continue" while the result needs another pass.\n'
            f'    done = state.get("iterations", 0) >= 3 or state.get("{steps[-1]}") is None\n'
            '    return "end" if done else "continue"\n'
        )
    out += f'\n\ndef build_graph() -> Any:\n    """Compile the {arch.name} ({arch.topology}) graph."""\n'
    out += "    graph = StateGraph(PatternState)\n"
    out += "".join(f'    graph.add_node("{n}", _node_{n})\n' for n in steps)
    out += f'    graph.set_entry_point("{steps[0]}")\n'
    out += "".join(f'    graph.add_edge("{a}", "{b}")\n' for a, b in zip(steps, steps[1:], strict=False))
    if looped:
        out += (
            f'    graph.add_conditional_edges(\n        "{steps[-1]}", _should_continue, '
            f'{{"continue": "{back}", "end": END}}\n    )\n'
        )
    else:
        out += f'    graph.add_edge("{steps[-1]}", END)\n'
    out += "    return graph.compile()\n"
    out += (
        "\n\ndef run_framework(task: str) -> Any:\n"
        '    """Run the compiled graph on ``task``."""\n'
        '    return build_graph().invoke({"task": task})\n'
    )
    return out


def _pydantic_ai(arch: Architecture, agent_name: str, description: str, fw: Framework) -> str:
    out = _header(
        arch, fw, agent_name, description, "from pydantic import BaseModel, Field\nfrom pydantic_ai import Agent"
    )
    fields = "\n".join(f'    {n}: str = Field(default="", description="{_q(d)}")' for n, d in arch.steps)
    out += (
        f'\n\nclass PatternOutput(BaseModel):\n    """Structured output: one field per {arch.name} step."""\n\n'
        f'{fields}\n    final_output: str = Field(default="", description="The final answer.")\n'
        "\n\ndef build_agent() -> Agent[None, PatternOutput]:\n"
        '    """A typed Pydantic AI agent that returns every step\'s result."""\n'
        '    # TODO(author): set the model your deployment uses (e.g. "openai:<model>").\n'
        f'    return Agent("test", output_type=PatternOutput, system_prompt="{_q(description)}")\n'
        "\n\ndef run_framework(task: str) -> Any:\n"
        '    """Run the agent and return its structured output."""\n'
        "    return build_agent().run_sync(task).output\n"
    )
    return out


def _crewai(arch: Architecture, agent_name: str, description: str, fw: Framework) -> str:
    out = _header(arch, fw, agent_name, description, "from crewai import Agent, Crew, Process, Task")
    tasks = "".join(
        f'        Task(\n            name="{n}",\n            description="{n}: {_q(d)} Input: {{task}}",\n'
        f'            agent=specialist,\n            expected_output="The result of `{n}`.",\n        ),\n'
        for n, d in arch.steps
    )
    out += (
        "\n\ndef build_crew() -> Crew:\n"
        f'    """The {arch.name} steps as a sequential CrewAI pipeline."""\n'
        f'    specialist = Agent(role="{_q(agent_name)}", goal="{_q(description)}", '
        f'backstory="Runs the {arch.name} pattern.")\n'
        f"    tasks = [\n{tasks}    ]\n"
        "    return Crew(agents=[specialist], tasks=tasks, process=Process.sequential)\n"
        "\n\ndef run_framework(task: str) -> Any:\n"
        '    """Kick off the crew on ``task``."""\n'
        '    return build_crew().kickoff(inputs={"task": task})\n'
    )
    return out


def _smolagents(arch: Architecture, agent_name: str, description: str, fw: Framework) -> str:
    out = _header(arch, fw, agent_name, description, "from smolagents import CodeAgent, tool")
    fns, names = _tool_functions(arch, "tool", args_doc=True)
    out += fns + (
        "\n\ndef build_agent(model: Any) -> CodeAgent:\n"
        '    """A CodeAgent with one tool per pattern step."""\n'
        f"    return CodeAgent(tools=[{', '.join(names)}], model=model)\n"
        "\n\ndef run_framework(task: str, model: Any = None) -> Any:\n"
        '    """Run the agent on ``task``."""\n'
        "    # TODO(author): pass your smolagents model instance.\n"
        "    return build_agent(model).run(task)\n"
    )
    return out


def _ag2(arch: Architecture, agent_name: str, description: str, fw: Framework) -> str:
    out = _header(
        arch, fw, agent_name, description, "from autogen import ConversableAgent, GroupChat, GroupChatManager"
    )
    agents = "".join(
        f'    agent_{n} = ConversableAgent(\n        name="{n}",\n'
        f'        system_message="Step `{n}` ({arch.name}): {_q(d)}",\n        human_input_mode="NEVER",\n    )\n'
        for n, d in arch.steps
    )
    names = ", ".join(f"agent_{n}" for n, _ in arch.steps)
    out += (
        "\n\ndef build_agents() -> tuple[ConversableAgent, GroupChatManager]:\n"
        '    """One ConversableAgent per step in a GroupChat."""\n'
        '    user = ConversableAgent(name="user", human_input_mode="NEVER")\n'
        f"{agents}"
        f"    chat = GroupChat(agents=[user, {names}], messages=[], max_round={len(arch.steps) + 2})\n"
        "    return user, GroupChatManager(groupchat=chat)\n"
        "\n\ndef run_framework(task: str) -> Any:\n"
        '    """Start the group chat on ``task``."""\n'
        "    user, manager = build_agents()\n"
        "    return user.initiate_chat(manager, message=task)\n"
    )
    return out


def _strands(arch: Architecture, agent_name: str, description: str, fw: Framework) -> str:
    out = _header(arch, fw, agent_name, description, "from strands import Agent, tool")
    fns, names = _tool_functions(arch, "tool")
    out += fns + (
        "\n\ndef build_agent() -> Agent:\n"
        '    """A Strands agent with one tool per pattern step."""\n'
        f'    return Agent(system_prompt="{_q(description)}", tools=[{", ".join(names)}])\n'
        "\n\ndef run_framework(task: str) -> Any:\n"
        '    """Run the agent on ``task``."""\n'
        "    return build_agent()(task)\n"
    )
    return out


def _openai_agents(arch: Architecture, agent_name: str, description: str, fw: Framework) -> str:
    out = _header(arch, fw, agent_name, description, "from agents import Agent, Runner, function_tool")
    fns, names = _tool_functions(arch, "function_tool")
    out += fns + (
        "\n\ndef build_agent() -> Agent:\n"
        '    """An OpenAI Agents SDK agent with one tool per pattern step."""\n'
        f'    return Agent(name="{_q(agent_name)}", instructions="{_q(description)}", tools=[{", ".join(names)}])\n'
        "\n\ndef run_framework(task: str) -> Any:\n"
        '    """Run the agent on ``task``."""\n'
        "    return Runner.run_sync(build_agent(), task)\n"
    )
    return out


def _google_adk(arch: Architecture, agent_name: str, description: str, fw: Framework) -> str:
    looped = arch.topology in ("loop", "cycle")
    cls = "LoopAgent" if looped else "SequentialAgent"
    out = _header(arch, fw, agent_name, description, f"from google.adk.agents import LlmAgent, {cls}")
    subs = "".join(
        f'    step_{n} = LlmAgent(\n        name="{n}",\n        model=MODEL,\n'
        f'        instruction="Step `{n}` ({arch.name}): {_q(d)}",\n    )\n'
        for n, d in arch.steps
    )
    names = ", ".join(f"step_{n}" for n, _ in arch.steps)
    extra = ", max_iterations=3" if looped else ""
    out += (
        '\n\n# TODO(author): the model your deployment uses.\nMODEL = "gemini-2.0-flash"\n'
        f"\n\ndef build_agent() -> {cls}:\n"
        f'    """One LlmAgent per step, composed into a {cls}."""\n'
        f"{subs}"
        f'    return {cls}(name="pattern", sub_agents=[{names}]{extra})\n'
        "\n\ndef run_framework(task: str) -> Any:\n"
        '    """Return the composed agent.\n\n'
        "    TODO(author): run it with google.adk.runners.InMemoryRunner on ``task``.\n"
        '    """\n'
        "    return build_agent()\n"
    )
    return out


def _claude_agent_sdk(arch: Architecture, agent_name: str, description: str, fw: Framework) -> str:
    out = _header(
        arch,
        fw,
        agent_name,
        description,
        "from claude_agent_sdk import ClaudeAgentOptions, query",
        stdlib="import asyncio",
    )
    steps = ", ".join(n for n, _ in arch.steps)
    out += (
        "\n\nasync def _run(task: str) -> list[Any]:\n"
        f'    """Drive the {arch.name} steps ({steps}) through the query loop."""\n'
        f'    options = ClaudeAgentOptions(system_prompt="{_q(description)}", max_turns={max(len(arch.steps), 2)})\n'
        "    return [message async for message in query(prompt=task, options=options)]\n"
        "\n\ndef run_framework(task: str) -> Any:\n"
        '    """Run the query loop on ``task``.\n\n'
        "    agent.py runs this in a worker thread, so a fresh event loop is safe here.\n"
        '    """\n'
        "    return asyncio.run(_run(task))\n"
    )
    return out


_FRAGMENTS: dict[str, Callable[[Architecture, str, str, Framework], str]] = {
    "langgraph": _langgraph,
    "pydantic_ai": _pydantic_ai,
    "crewai": _crewai,
    "smolagents": _smolagents,
    "ag2": _ag2,
    "strands": _strands,
    "openai_agents": _openai_agents,
    "google_adk": _google_adk,
    "claude_agent_sdk": _claude_agent_sdk,
}


def framework_slugs() -> list[str]:
    return list(_FRAGMENTS)


def render_framework_module(arch: Architecture, fw: Framework, agent_name: str, description: str) -> str:
    """Source of ``pattern_<framework>.py`` for one architecture."""
    if fw.slug not in _FRAGMENTS:
        raise ValueError(f"no framework fragment for {fw.slug!r}")
    return _FRAGMENTS[fw.slug](arch, agent_name, description, fw)


def render_framework_bridge(arch: Architecture, fw: Framework) -> str:
    """Class-body code for agent.py: ``_run_pattern`` delegating to the framework module."""
    return (
        "    # ------------------------------------------------------------------\n"
        f"    # Design pattern: {arch.name} ({arch.topology} topology), built with\n"
        f"    # {fw.name} in pattern_{fw.slug}.py. See README.md for the diagram.\n"
        "    # ------------------------------------------------------------------\n"
        "\n"
        "    async def _run_pattern(\n"
        "        self, input_data: Any, context: RequestContext, event_queue: EventQueue\n"
        "    ) -> dict[str, Any]:\n"
        f'        """Run the {arch.name} pattern through {fw.name}."""\n'
        f"        from pattern_{fw.slug} import run_framework\n"
        "\n"
        "        # Frameworks are mostly synchronous; keep the event loop free.\n"
        "        output = await asyncio.to_thread(run_framework, str(input_data))\n"
        '        return {"input_data": input_data, "output": output}\n'
    )
