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

"""Agentic design patterns for the agent scaffolder.

``patterns.json`` holds the catalog: 9 pattern families, 36 architectures
(each with ordered steps and a control-flow topology) and 9 agent frameworks.
This module loads it, suggests an architecture for an agent description, and
renders the code ``setup_agent.py`` writes into the new agent.

Selection is offline by default: a keyword score over each architecture's
name, description and when-to-use text. ``suggest_with_llm`` optionally asks
the platform's LLM (through ``prometheus_api``'s LLM client) and falls back to
the keyword score on any failure. Code generation is deterministic.

Standard library only, so the scaffolder runs before any agent dependency is
installed.
"""

from __future__ import annotations

import json
import keyword
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).resolve().parent / "patterns.json"
TOPOLOGIES = ("linear", "loop", "cycle", "parallel", "tree")
NATIVE_FRAMEWORK = "native"
DEFAULT_ARCHITECTURE = "tool_use"

# Words that carry no signal for matching a description to a pattern.
_STOPWORDS = frozenset(
    {
        *("a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "for", "from", "has"),
        *("have", "in", "into", "is", "it", "its", "of", "on", "or", "that", "the", "then"),
        *("this", "to", "use", "uses", "using", "via", "was", "when", "where", "which"),
        *("while", "with", "agent", "agents"),
    }
)


@dataclass(frozen=True)
class Family:
    slug: str
    name: str
    description: str
    when_to_use: str
    needs: str = ""
    cost: str = ""
    reference: str = ""


@dataclass(frozen=True)
class Architecture:
    slug: str
    name: str
    family: str
    description: str
    when_to_use: str
    steps: tuple[tuple[str, str], ...]
    topology: str
    reference: str = ""


@dataclass(frozen=True)
class Framework:
    slug: str
    name: str
    pip_install: str
    import_module: str
    base_entrypoint: str
    docs: str
    recommended_for: tuple[str, ...]
    status: str


@dataclass(frozen=True)
class Catalog:
    families: dict[str, Family]
    architectures: dict[str, Architecture]
    frameworks: dict[str, Framework]

    def family_of(self, arch: Architecture) -> Family:
        return self.families[arch.family]


@dataclass
class Plan:
    """The pattern choices for one agent, after validation and repair."""

    architecture: str
    supporting: list[str] = field(default_factory=list)
    framework: str = NATIVE_FRAMEWORK
    rationale: str = ""
    source: str = "keyword"  # "keyword", "llm", "user", or "default"
    repairs: list[str] = field(default_factory=list)


@lru_cache(maxsize=1)
def load_catalog(path: Path = CATALOG_PATH) -> Catalog:
    """Load and validate ``patterns.json``."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    families = {f["slug"]: Family(**f) for f in raw["families"]}
    architectures: dict[str, Architecture] = {}
    for a in raw["architectures"]:
        arch = Architecture(
            slug=a["slug"],
            name=a["name"],
            family=a["family"],
            description=a["description"],
            when_to_use=a["when_to_use"],
            steps=tuple((str(n), str(d)) for n, d in a["steps"]),
            topology=a.get("topology", "linear"),
            reference=a.get("reference", ""),
        )
        if arch.family not in families:
            raise ValueError(f"architecture {arch.slug!r} has unknown family {arch.family!r}")
        if arch.topology not in TOPOLOGIES:
            raise ValueError(f"architecture {arch.slug!r} has unknown topology {arch.topology!r}")
        if not arch.steps:
            raise ValueError(f"architecture {arch.slug!r} has no steps")
        for node, _ in arch.steps:
            if not node.isidentifier() or keyword.iskeyword(node):
                raise ValueError(f"architecture {arch.slug!r} step {node!r} is not a usable identifier")
        architectures[arch.slug] = arch
    frameworks = {
        f["slug"]: Framework(
            slug=f["slug"],
            name=f["name"],
            pip_install=f["pip_install"],
            import_module=f["import_module"],
            base_entrypoint=f["base_entrypoint"],
            docs=f["docs"],
            recommended_for=tuple(f.get("recommended_for", ())),
            status=f.get("status", "supported"),
        )
        for f in raw["frameworks"]
    }
    return Catalog(families, architectures, frameworks)


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS and len(t) > 1]


def score_architectures(description: str, catalog: Catalog | None = None) -> list[tuple[float, str]]:
    """Keyword score of every architecture for a description, best first.

    Score = 2 x hits in the name/description/slug + 1 x hits in when_to_use.
    Ties keep catalog order.
    """
    cat = catalog or load_catalog()
    words = set(_tokens(description))
    scored = []
    for i, arch in enumerate(cat.architectures.values()):
        head = set(_tokens(f"{arch.slug.replace('_', ' ')} {arch.name} {arch.description}"))
        tail = set(_tokens(arch.when_to_use))
        score = 2 * len(words & head) + len(words & tail)
        scored.append((score, -i, arch.slug))
    scored.sort(reverse=True)
    return [(float(s), slug) for s, _, slug in scored]


def suggest(description: str, catalog: Catalog | None = None) -> Plan:
    """Offline suggestion: the best keyword match, or the default when nothing matches."""
    cat = catalog or load_catalog()
    ranked = score_architectures(description, cat)
    best_score, best = ranked[0]
    if best_score <= 0:
        return Plan(
            architecture=DEFAULT_ARCHITECTURE,
            rationale="No keyword matched; defaulting to a single tool-calling step.",
            source="default",
        )
    supporting = [s for sc, s in ranked[1:3] if sc > 0 and s != best]
    return Plan(
        architecture=best,
        supporting=supporting,
        rationale=f"Keyword match (score {best_score:g}) on the description.",
        source="keyword",
    )


def repair_plan(plan: Plan, catalog: Catalog | None = None) -> Plan:
    """Make a plan valid: known slugs only, no duplicates, a known framework.

    Unknown values are replaced or dropped, and each change is recorded in
    ``plan.repairs`` so the scaffolder can tell the user.
    """
    cat = catalog or load_catalog()
    repairs = list(plan.repairs)
    arch = _normalize_slug(plan.architecture)
    if arch not in cat.architectures:
        repairs.append(f"unknown architecture {plan.architecture!r}; using {DEFAULT_ARCHITECTURE!r}")
        arch = DEFAULT_ARCHITECTURE
    supporting: list[str] = []
    for s in plan.supporting:
        slug = _normalize_slug(s)
        if slug not in cat.architectures:
            repairs.append(f"dropped unknown supporting architecture {s!r}")
        elif slug != arch and slug not in supporting:
            supporting.append(slug)
    framework = _normalize_slug(plan.framework) or NATIVE_FRAMEWORK
    if framework != NATIVE_FRAMEWORK and framework not in cat.frameworks:
        repairs.append(f"unknown framework {plan.framework!r}; using {NATIVE_FRAMEWORK!r}")
        framework = NATIVE_FRAMEWORK
    return Plan(arch, supporting[:3], framework, plan.rationale, plan.source, repairs)


def _normalize_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def llm_prompt(description: str, catalog: Catalog | None = None) -> str:
    """The classification prompt sent by :func:`suggest_with_llm`."""
    cat = catalog or load_catalog()
    lines = [
        "You choose the agentic design pattern for a new software agent.",
        "Pick ONE primary architecture and up to two supporting ones from this catalog.",
        "Prefer the simplest architecture that fits. Use a sampling architecture for",
        "uncertainty or Monte-Carlo work, a planning one when the task must be decomposed,",
        "and treat tool_use as a supporting architecture unless calling tools is the whole job.",
        "",
        "Catalog (slug: name -- when to use):",
    ]
    for fam in cat.families.values():
        lines.append(f"[{fam.name}]")
        for a in cat.architectures.values():
            if a.family == fam.slug:
                lines.append(f"- {a.slug}: {a.name} -- {a.when_to_use}")
    lines += [
        "",
        f"Agent description: {description}",
        "",
        'Reply with JSON only: {"architecture": "<slug>", "supporting": ["<slug>"], "rationale": "<one sentence>"}',
    ]
    return "\n".join(lines)


def parse_llm_reply(text: str) -> dict[str, Any] | None:
    """Pull the JSON object out of an LLM reply (tolerates code fences and prose)."""
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) and data.get("architecture") else None


def suggest_with_llm(description: str, catalog: Catalog | None = None) -> Plan:
    """Ask the platform's LLM for a pattern; fall back to :func:`suggest` on any failure.

    Uses ``prometheus_api.llm_client.LLMClient`` configured from the environment
    (``LLM_CONFIG_PROFILE`` / ``LLM_API_KEY``, as in a scaffolded agent's .env).
    ``prometheus_api`` is imported lazily, so the scaffolder itself does not need it.
    """
    cat = catalog or load_catalog()
    fallback = suggest(description, cat)
    try:
        from prometheus_api.llm_client import LLMClient  # type: ignore[import-not-found]

        with LLMClient(app_name="agent-template-setup") as client:
            reply = client.small(llm_prompt(description, cat))
        data = parse_llm_reply(getattr(reply, "text", "") or "")
    except Exception as exc:  # noqa: BLE001 - any failure falls back to keywords
        fallback.repairs.append(f"LLM suggestion unavailable ({type(exc).__name__}); used keywords")
        return fallback
    if data is None:
        fallback.repairs.append("LLM reply had no usable JSON; used keywords")
        return fallback
    plan = Plan(
        architecture=str(data.get("architecture", "")),
        supporting=[str(s) for s in data.get("supporting") or []],
        rationale=str(data.get("rationale", "")),
        source="llm",
    )
    return repair_plan(plan, cat)


def default_framework(arch: Architecture, catalog: Catalog | None = None) -> str:
    """The first framework recommended for the architecture's family, else native."""
    cat = catalog or load_catalog()
    for fw in cat.frameworks.values():
        if arch.family in fw.recommended_for:
            return fw.slug
    return NATIVE_FRAMEWORK


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_mermaid(arch: Architecture) -> str:
    """A Mermaid flowchart of the pattern's steps and its back-edges."""
    names = [n for n, _ in arch.steps]
    lines = ["flowchart TD", "    START([request]) --> " + names[0]]
    for node, _ in arch.steps:
        lines.append(f"    {node}[{node}]")
    if arch.topology == "parallel" and len(names) >= 2:
        lines.append(f"    {names[0]} -->|N runs| {names[1]}")
        for i in range(1, len(names) - 1):
            lines.append(f"    {names[i]} --> {names[i + 1]}")
    elif arch.topology == "tree" and len(names) >= 3:
        lines.append(f"    {names[0]} --> {names[1]}")
        lines.append(f"    {names[0]} -.-> {names[1]}")
        for i in range(1, len(names) - 1):
            lines.append(f"    {names[i]} --> {names[i + 1]}")
    else:
        for i in range(len(names) - 1):
            lines.append(f"    {names[i]} --> {names[i + 1]}")
    if arch.topology == "loop" and len(names) >= 2:
        lines.append(f"    {names[-1]} -->|not good enough| {names[0]}")
    if arch.topology == "cycle" and len(names) >= 2:
        lines.append(f"    {names[-1]} -->|continue| {names[-2]}")
    lines.append(f"    {names[-1]} --> END([result])")
    return "\n".join(lines)


def _step_method(arch: Architecture, node: str, desc: str) -> str:
    return (
        f"    async def _step_{node}(\n"
        f"        self, state: dict[str, Any], context: RequestContext, event_queue: EventQueue\n"
        f"    ) -> Any:\n"
        f'        """{arch.name} step `{node}`: {desc}"""\n'
        f"        # TODO(author): implement `{node}`. For an LLM call:\n"
        f"        #     async with self.llm_client(context) as llm:\n"
        f"        #         return (await llm.medium(f\"...{{state['input_data']}}\")).text\n"
        f"        return None\n"
    )


def _step_call(node: str, indent: str) -> str:
    """``state[node] = await self._step_node(...)``, wrapped to fit the agent's 100 columns."""
    line = f'state["{node}"] = await self._step_{node}(state, context, event_queue)'
    if len(indent) + len(line) <= 100:
        return line
    return f'state["{node}"] = await self._step_{node}(\n{indent}    state, context, event_queue\n{indent})'


def _loop_driver(arch: Architecture) -> list[str]:
    """Statements that walk the steps in ``_run_pattern``, by topology."""
    names = [n for n, _ in arch.steps]
    ind = " " * 8
    out: list[str] = []
    if arch.topology in ("loop", "cycle") and len(names) >= 2:
        head = names if arch.topology == "loop" else names[:-2]
        body = names if arch.topology == "loop" else names[-2:]
        what = "all steps" if arch.topology == "loop" else f"`{body[0]}` and `{body[1]}`"
        for n in head if arch.topology == "cycle" else []:
            out.append(ind + _step_call(n, ind))
        out.append(ind + f"# {arch.topology}: repeat {what} until the result is good enough.")
        out.append(ind + "for _ in range(MAX_ITERATIONS):")
        for n in body:
            out.append(ind + "    " + _step_call(n, ind + "    "))
        out.append(ind + "    # TODO(author): stop when the result is good enough.")
        out.append(ind + f'    if state.get("{body[-1]}") is None:')
        out.append(ind + "        break")
    elif arch.topology == "parallel" and len(names) >= 2:
        first, rest = names[0], names[1:]
        if len(names) > 2:
            out.append(ind + _step_call(first, ind))
            fan, rest = rest[0], rest[1:]
        else:
            fan, rest = first, rest
        out.append(ind + f"# parallel: run `{fan}` NUM_SAMPLES times concurrently, then aggregate.")
        out.append(ind + "runs = await asyncio.gather(")
        out.append(ind + f"    *(self._step_{fan}(state, context, event_queue) for _ in range(NUM_SAMPLES))")
        out.append(ind + ")")
        out.append(ind + f'state["{fan}"] = list(runs)')
        for n in rest:
            out.append(ind + _step_call(n, ind))
    elif arch.topology == "tree" and len(names) >= 3:
        out.append(ind + _step_call(names[0], ind))
        out.append(ind + f"# tree: `{names[0]}` fans out; `{names[1]}` handles each branch.")
        out.append(ind + "# TODO(author): run one branch per sub-task (e.g. asyncio.gather).")
        for n in names[1:]:
            out.append(ind + _step_call(n, ind))
    else:
        for n in names:
            out.append(ind + _step_call(n, ind))
    return out


def render_native_pattern(arch: Architecture, catalog: Catalog | None = None) -> str:
    """Class-body code for a ``PrometheusAgent`` subclass: ``_run_pattern`` plus one method per step.

    Every step returns ``None`` until the author implements it, so the
    generated agent runs, passes its tests and lints clean from the start.
    """
    cat = catalog or load_catalog()
    fam = cat.family_of(arch)
    lines = [
        "    # ------------------------------------------------------------------",
        f"    # Design pattern: {arch.name} ({fam.name} family, {arch.topology} topology).",
        f"    # {arch.description}",
        "    # Steps: " + " -> ".join(n for n, _ in arch.steps) + ". See README.md for the diagram.",
        "    # ------------------------------------------------------------------",
        "",
        "    async def _run_pattern(",
        "        self, input_data: Any, context: RequestContext, event_queue: EventQueue",
        "    ) -> dict[str, Any]:",
        f'        """Run the {arch.name} steps on one request and return the state they built."""',
        '        state: dict[str, Any] = {"input_data": input_data}',
        *_loop_driver(arch),
        "        return state",
    ]
    for node, desc in arch.steps:
        lines.append("")
        lines.append(_step_method(arch, node, desc).rstrip("\n"))
    return "\n".join(lines) + "\n"


def pattern_constants(arch: Architecture) -> str:
    """Module-level constants the native pattern code uses."""
    out = []
    if arch.topology in ("loop", "cycle"):
        out.append("# Upper bound on loop iterations for the design pattern below.\nMAX_ITERATIONS = 3")
    if arch.topology == "parallel":
        out.append("# Independent runs the design pattern fans out to before aggregating.\nNUM_SAMPLES = 5")
    return "\n\n".join(out)


def pattern_readme(arch: Architecture, plan: Plan, catalog: Catalog | None = None) -> str:
    """README section describing the chosen pattern, with its Mermaid diagram."""
    cat = catalog or load_catalog()
    fam = cat.family_of(arch)
    steps = "\n".join(f"{i}. **`{n}`**: {d}" for i, (n, d) in enumerate(arch.steps, start=1))
    supporting = ", ".join(cat.architectures[s].name for s in plan.supporting) or "none"
    fw = "PrometheusAgent (native)" if plan.framework == NATIVE_FRAMEWORK else cat.frameworks[plan.framework].name
    ref = f"\n\nFurther reading: {arch.reference}" if arch.reference else ""
    return (
        f"## Design pattern: {arch.name}\n\n"
        f"- **Family:** {fam.name}. {fam.description}\n"
        f"- **When to use:** {arch.when_to_use}\n"
        f"- **Topology:** {arch.topology}\n"
        f"- **Supporting patterns:** {supporting}\n"
        f"- **Framework:** {fw}\n"
        f"- **Chosen by:** {plan.source}. {plan.rationale}\n\n"
        f"`_execute` calls `_run_pattern`, which walks these steps; each is a "
        f"`_step_<name>` method with a `TODO(author)`:\n\n{steps}\n\n"
        f"```mermaid\n{render_mermaid(arch)}\n```{ref}\n"
    )
