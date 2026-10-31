#!/usr/bin/env python3
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

"""
Agent Template Setup Script

This script creates a new agent from the template by replacing all template
placeholders with your custom values.

Usage:
    python setup_agent.py [agent_name] [output_directory]
    python setup_agent.py --yes <agent_name> [output_directory]
    python setup_agent.py --env-only <agent_directory>
    python setup_agent.py --list-patterns

Design pattern: the agent's _execute is scaffolded to one agentic design
pattern (reflection, RAG, planning, ReAct, multi-agent, ...; see
patterns.json). The scaffolder suggests one from the description; --pattern
picks it, --llm asks the platform's LLM for the suggestion, and --framework
also writes the pattern with an agent framework (LangGraph, CrewAI, ...).

Arguments given on the command line are not prompted for; everything else
is (press Enter to accept a default). With no arguments, every value is
prompted for. --yes accepts every default without prompting, for scripts and
CI; it needs the agent name, and fails if the output directory exists.

Example:
    python setup_agent.py "Plant Analysis" ./plant-agent
    python setup_agent.py "Data Validator"
    python setup_agent.py --yes "Data Validator" /tmp/data-validator
    python setup_agent.py --yes --pattern corrective_rag --framework langgraph "Doc QA"
    python setup_agent.py
    python setup_agent.py --env-only ../../my-team-agent

--env-only writes only the .env of an agent you already have (for example a
clone of a teammate's agent repo), from this clone's ../platform/.env.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import frameworks
import patterns

PLATFORM_ENV_PATH = Path(__file__).resolve().parent.parent / "platform" / ".env"
PLATFORM_SECRET_KEYS = (
    "AGENT_SECRET",
    "REDIS_PASSWORD",
    # Multi-user identity (RS256, verification-side only -- never the private
    # key). ISS/AUD are copied too since a mismatch here silently fails
    # verification even with a correct public key.
    "USER_IDENTITY_PUBLIC_KEY",
    "USER_IDENTITY_ISS",
    "USER_IDENTITY_AUD",
    # Not a secret, but copied for the same reason as ISS/AUD: a scaffolded
    # agent must use the platform's profile; the template has no default.
    "LLM_CONFIG_PROFILE",
    # Every profile reads its provider key from LLM_API_KEY, so the agent can
    # call the same provider the platform does; embeddings may need their own.
    "LLM_API_KEY",
    "EMBEDDING_API_KEY",
)
# The DeepLynx client settings an agent reads (agent_template/docker-compose.yml).
# Not a DEEPLYNX_ prefix: the platform .env also holds the local DeepLynx
# server's own secrets (DB password, JWT and encryption keys), which an
# agent must never get.
PLATFORM_DEEPLYNX_KEYS = (
    "DEEPLYNX_BASE_URL",
    "DEEPLYNX_KEY",
    "DEEPLYNX_SECRET",
    "DEEPLYNX_JWT_TOKEN",
    "DEEPLYNX_ORG_ID",
    "DEEPLYNX_PROJECT_ID",
    "DEEPLYNX_DATA_SOURCE_ID",
)
ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SECRET_GITIGNORE_ENTRIES = (".env",)


def to_snake_case(text: str) -> str:
    """Convert text to snake_case."""
    # Replace spaces and special chars with underscores
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "_", text)
    return text.lower()


def to_pascal_case(text: str) -> str:
    """Convert text to PascalCase."""
    # Remove special characters except spaces and hyphens
    text = re.sub(r"[^\w\s-]", "", text)
    # Split on spaces and hyphens, capitalize each word
    words = re.split(r"[-\s]+", text)
    return "".join(word.capitalize() for word in words if word)


def to_kebab_case(text: str) -> str:
    """Convert text to kebab-case."""
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text.lower()


def get_user_input(prompt: str, default: str = "", assume_defaults: bool = False) -> str:
    """Get user input with optional default value.

    With ``assume_defaults`` (--yes), the default is used without reading stdin.
    """
    if assume_defaults:
        print(f"{prompt}: {default}")
        return default
    if default:
        response = input(f"{prompt} [{default}]: ").strip()
        return response if response else default
    return input(f"{prompt}: ").strip()


def confirm_action(prompt: str, default: str = "yes", assume_defaults: bool = False) -> bool:
    """Prompt the user for a yes/no confirmation."""
    return get_user_input(prompt, default, assume_defaults).lower() in {"yes", "y"}


def choose_pattern(
    description: str,
    pattern: str | None = None,
    framework: str | None = None,
    use_llm: bool = False,
    assume_defaults: bool = False,
) -> patterns.Plan:
    """Pick the agent's design pattern and framework.

    A ``pattern`` or ``framework`` given on the command line is used as-is.
    Otherwise the pattern is suggested from the description (by keywords, or by
    the platform's LLM with ``use_llm``) and the user may accept it, or pick
    another from the catalog. With ``assume_defaults`` (--yes) the suggestion
    is taken without prompting. The framework defaults to native.
    """
    catalog = patterns.load_catalog()
    print("\n" + "-" * 70)
    print("  Design Pattern")
    print("-" * 70)

    if pattern:
        plan = patterns.repair_plan(patterns.Plan(architecture=pattern, source="user"), catalog)
    else:
        plan = patterns.suggest_with_llm(description, catalog) if use_llm else patterns.suggest(description, catalog)
    arch = catalog.architectures[plan.architecture]
    family = catalog.family_of(arch)
    print(f"\nSuggested pattern: {arch.name} ({family.name}) [{arch.slug}]")
    print(f"  {arch.description}")
    print(f"  Steps: {' -> '.join(n for n, _ in arch.steps)}  ({arch.topology})")
    if plan.rationale:
        print(f"  Why: {plan.rationale}")
    for note in plan.repairs:
        print(f"  Note: {note}")

    if not pattern and not confirm_action("\nUse this pattern? (yes/no)", "yes", assume_defaults):
        print("\nAvailable patterns (enter the slug):")
        print(list_patterns_text(catalog))
        while True:
            choice = get_user_input("\nPattern slug", arch.slug, assume_defaults).strip()
            if choice in catalog.architectures:
                plan = patterns.Plan(architecture=choice, source="user")
                break
            print(f"Unknown pattern {choice!r}; enter one of the slugs above.")

    if framework is None:
        options = ", ".join([patterns.NATIVE_FRAMEWORK, *catalog.frameworks])
        framework = get_user_input(f"\nAgent framework ({options})", patterns.NATIVE_FRAMEWORK, assume_defaults)
    seen = len(plan.repairs)
    plan.framework = framework
    plan = patterns.repair_plan(plan, catalog)
    for note in plan.repairs[seen:]:
        print(f"  Note: {note}")
    return plan


def list_patterns_text(catalog: patterns.Catalog | None = None) -> str:
    """The catalog as text: families, then each architecture's slug and when to use it."""
    cat = catalog or patterns.load_catalog()
    lines = []
    for fam in cat.families.values():
        lines.append(f"\n{fam.name}: {fam.description}")
        for arch in cat.architectures.values():
            if arch.family == fam.slug:
                lines.append(f"  {arch.slug:<24} {arch.name}: {arch.when_to_use}")
    lines.append("\nFrameworks (--framework): " + ", ".join([patterns.NATIVE_FRAMEWORK, *cat.frameworks]))
    return "\n".join(lines)


def collect_agent_info(
    agent_name: str | None = None,
    output_dir: str | None = None,
    assume_defaults: bool = False,
    pattern: str | None = None,
    framework: str | None = None,
    use_llm: bool = False,
) -> dict[str, str]:
    """Interactively collect agent information from the user.

    ``agent_name`` and ``output_dir`` come from the command line; when given,
    they are used as-is instead of being prompted for. With ``assume_defaults``
    (--yes), every other value takes its default. ``pattern``, ``framework``
    and ``use_llm`` drive the design-pattern step (see :func:`choose_pattern`).
    """

    def ask(prompt: str, default: str = "") -> str:
        return get_user_input(prompt, default, assume_defaults)

    print("\n" + "=" * 70)
    print("  Agent Template Setup")
    print("=" * 70)
    print("\nThis script will help you create a new agent from the template.")
    print("Please provide the following information:\n")

    # Get agent name
    if agent_name:
        print(f"Agent name: {agent_name}")
    while not agent_name:
        agent_name = ask("Agent name (e.g., 'Plant Analysis', 'Data Validator')")
        if not agent_name:
            print("Error: Agent name is required.\n")

    # Generate default values
    default_slug = to_kebab_case(agent_name)
    default_class = to_pascal_case(agent_name)

    # Get description
    description = ask(
        "\nAgent description (brief summary of what it does)", f"A specialized agent for {agent_name.lower()}"
    )

    # Get slug (for directories, files, etc.)
    slug = ask("\nAgent slug (used for directories and Docker)", default_slug)

    # Get class name
    class_name = ask(
        "\nAgent class name (PascalCase, without an 'Agent' suffix — it is appended automatically)",
        default_class,
    )

    # Get skill information
    print("\n" + "-" * 70)
    print("  Primary Skill Configuration")
    print("-" * 70)

    skill_id = ask("\nPrimary skill ID (snake_case)", f"{to_snake_case(agent_name)}_analysis")

    skill_name = ask("\nPrimary skill name", f"{agent_name} Analysis")

    skill_description = ask("\nPrimary skill description", f"Performs analysis using {agent_name.lower()}")

    # Pick the design pattern _execute is scaffolded to
    plan = choose_pattern(description, pattern, framework, use_llm, assume_defaults)

    # Get output directory
    if not output_dir:
        output_dir = ask("\nOutput directory", f"../{slug}")

    # Keep comments in the copied agent.py
    trim_comments = ask("\nTrim agent.py comments", "False")

    # Confirm
    print("\n" + "=" * 70)
    print("  Configuration Summary")
    print("=" * 70)
    print(f"\nAgent Name:        {agent_name}")
    print(f"Description:       {description}")
    print(f"Slug:              {slug}")
    print(f"Class Name:        {class_name}")
    print(f"Primary Skill ID:  {skill_id}")
    print(f"Primary Skill:     {skill_name}")
    print(f"Design Pattern:    {plan.architecture}")
    print(f"Framework:         {plan.framework}")
    print(f"Output Directory:  {output_dir}")
    print(f"Trim Comments:     {trim_comments}")
    print()

    confirm = ask("Proceed with these settings? (yes/no)", "yes")
    if confirm.lower() not in ["yes", "y"]:
        print("\nSetup cancelled.")
        sys.exit(0)

    return {
        "TEMPLATE_NAME": agent_name,
        "TEMPLATE_DESCRIPTION": description,
        "TEMPLATE_SLUG": slug,
        "TEMPLATE_CLASS": class_name,
        "TEMPLATE_SKILL_ID": skill_id,
        "TEMPLATE_SKILL_NAME": skill_name,
        "TEMPLATE_SKILL_DESCRIPTION": skill_description,
        "OUTPUT_DIR": output_dir,
        "TRIM_COMMENTS": trim_comments,
        "PATTERN": plan.architecture,
        "PATTERN_SUPPORTING": ",".join(plan.supporting),
        "PATTERN_SOURCE": plan.source,
        "PATTERN_RATIONALE": plan.rationale,
        "FRAMEWORK": plan.framework,
    }


def strip_comments(content: str) -> str:
    """Remove comment lines and inline comments from Python source, then collapse excess blank lines."""
    lines = content.splitlines()
    result = []
    for line in lines:
        stripped = line.lstrip()
        # Remove full-line comments (but keep shebangs)
        if stripped.startswith("#") and not stripped.startswith("#!"):
            continue
        # Remove inline comments (naive but sufficient for template code)
        code_part = line.split(" #")[0].rstrip() if " #" in line else line
        result.append(code_part)

    # Collapse runs of 3+ blank lines down to 2
    collapsed = []
    blank_count = 0
    for line in result:
        if line.strip() == "":
            blank_count += 1
            if blank_count <= 2:
                collapsed.append(line)
        else:
            blank_count = 0
            collapsed.append(line)

    return "\n".join(collapsed) + "\n"


def replace_placeholders(content: str, replacements: dict[str, str]) -> str:
    """Replace all template placeholders in content."""
    for placeholder, value in replacements.items():
        if placeholder.startswith("TEMPLATE_"):
            content = content.replace(placeholder, value)
    return content


def replace_marked_block(content: str, marker: str, body: str) -> str:
    """Replace the lines between ``# >>> <marker>`` and ``# <<< <marker>`` (markers included).

    The template's agent.py keeps a valid default between the markers, so the
    unscaffolded template still runs and lints; the scaffolder swaps in the
    chosen pattern's code.
    """
    pattern = re.compile(
        rf"^[ \t]*# >>> {re.escape(marker)}\b[^\n]*\n.*?^[ \t]*# <<< {re.escape(marker)}[^\n]*\n",
        re.DOTALL | re.MULTILINE,
    )
    if not pattern.search(content):
        raise ValueError(f"marker block {marker!r} not found")
    return pattern.sub(lambda _m: body, content, count=1)


def apply_design_pattern(output_dir: Path, replacements: dict[str, str]) -> None:
    """Write the chosen design pattern into the scaffolded agent.

    Fills agent.py's marked pattern blocks, appends the pattern section to
    README.md, and for a framework variant writes ``pattern_<framework>.py``
    and adds the framework's package to pyproject.toml.
    """
    catalog = patterns.load_catalog()
    plan = patterns.repair_plan(
        patterns.Plan(
            architecture=replacements.get("PATTERN", patterns.DEFAULT_ARCHITECTURE),
            supporting=[s for s in replacements.get("PATTERN_SUPPORTING", "").split(",") if s],
            framework=replacements.get("FRAMEWORK", patterns.NATIVE_FRAMEWORK),
            rationale=replacements.get("PATTERN_RATIONALE", ""),
            source=replacements.get("PATTERN_SOURCE", "default"),
        ),
        catalog,
    )
    arch = catalog.architectures[plan.architecture]

    agent_py = output_dir / "agent.py"
    content = agent_py.read_text(encoding="utf-8")
    if plan.framework == patterns.NATIVE_FRAMEWORK:
        body = patterns.render_native_pattern(arch, catalog)
        constants = patterns.pattern_constants(arch)
    else:
        fw = catalog.frameworks[plan.framework]
        body = frameworks.render_framework_bridge(arch, fw)
        constants = ""
        module = frameworks.render_framework_module(
            arch, fw, replacements["TEMPLATE_NAME"], replacements["TEMPLATE_DESCRIPTION"]
        )
        module_path = output_dir / f"pattern_{fw.slug}.py"
        module_path.write_text(module, encoding="utf-8")
        format_python(module_path)
        add_dependency(output_dir / "pyproject.toml", fw.pip_install)
        print(f"  ✓ pattern_{fw.slug}.py ({fw.name})")
    content = replace_marked_block(content, "design pattern constants", constants + "\n\n" if constants else "")
    # The constants block sits right after the imports; keep exactly one blank
    # line there (ruff's isort) whether or not the pattern has constants.
    content = re.sub(r"(RequestContext\n)\n+", r"\1\n", content, count=1)
    content = replace_marked_block(content, "design pattern", body)
    agent_py.write_text(content, encoding="utf-8")

    readme = output_dir / "README.md"
    if readme.exists():
        text = readme.read_text(encoding="utf-8").rstrip("\n")
        readme.write_text(text + "\n\n" + patterns.pattern_readme(arch, plan, catalog), encoding="utf-8")

    card_path = output_dir / "agent_card.json"
    if card_path.exists():
        # A Prometheus card extension, like `workflows` and `endpoints`: the SDK
        # parses the card with ignore_unknown_fields and keeps the raw card (this
        # key included) for registry registration and /api/agent-card.
        card = json.loads(card_path.read_text(encoding="utf-8"))
        card["designPattern"] = {
            "architecture": arch.slug,
            "family": arch.family,
            "topology": arch.topology,
            "supporting": plan.supporting,
            "framework": plan.framework,
        }
        card_path.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  ✓ Design pattern: {arch.name} ({plan.framework})")


def format_python(path: Path) -> None:
    """Format a generated module with ruff, using the agent's own ruff config.

    The framework modules are generated with long call lines; ruff wraps them
    to the agent's line length. Skipped (with a note) when ruff is not on PATH;
    the module is still valid Python, just not ruff-formatted.
    """
    ruff = shutil.which("ruff")
    if ruff is None:
        print(f"  ! ruff not found; run `ruff format {path.name}` in the agent")
        return
    subprocess.run([ruff, "format", "-q", path.name], cwd=path.parent, check=False)
    subprocess.run([ruff, "check", "-q", "--fix", "--select", "I", path.name], cwd=path.parent, check=False)


def add_dependency(pyproject: Path, requirement: str) -> None:
    """Add ``requirement`` to ``[project].dependencies`` in a scaffolded pyproject.toml."""
    text = pyproject.read_text(encoding="utf-8")
    new, count = re.subn(r"(^dependencies = \[\n)", rf'\1    "{requirement}",\n', text, count=1, flags=re.MULTILINE)
    if count == 0:
        raise ValueError(f"no dependencies list in {pyproject}")
    pyproject.write_text(new, encoding="utf-8")


def read_env_assignments(env_path: Path) -> dict[str, str]:
    """Read simple KEY=VALUE assignments from an env file."""
    assignments: dict[str, str] = {}
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in line:
                continue

            key_part, value = line.split("=", 1)
            key = key_part.strip()
            if not ENV_KEY_PATTERN.fullmatch(key):
                continue

            assignments[key] = value.strip()

    return assignments


def platform_uses_local_sdk(assignments: dict[str, str]) -> bool:
    """Whether the platform builds with LOCAL_SDK=true.

    Mirrors platform/Makefile precedence: a LOCAL_SDK line in platform/.env
    wins, otherwise the shell environment (e.g. `export LOCAL_SDK=true`).
    """
    return assignments.get("LOCAL_SDK", os.environ.get("LOCAL_SDK")) == "true"


def select_platform_env_values(env_path: Path) -> dict[str, str]:
    """Select the platform env values that are useful to a generated agent."""
    assignments = read_env_assignments(env_path)
    selected = {key: assignments[key] for key in PLATFORM_SECRET_KEYS + PLATFORM_DEEPLYNX_KEYS if key in assignments}

    # A platform built with LOCAL_SDK=true has no registry access; the agent
    # Makefile then builds FROM the base image the platform built locally.
    if platform_uses_local_sdk(assignments):
        selected["LOCAL_SDK"] = "true"

    return selected


def ensure_secret_gitignore_entries(output_dir: Path) -> None:
    """Ensure generated secret files are ignored by git."""
    gitignore_path = output_dir / ".gitignore"
    existing = ""
    existing_lines: set[str] = set()

    if gitignore_path.exists():
        with open(gitignore_path, encoding="utf-8") as f:
            existing = f.read()
        existing_lines = {line.strip() for line in existing.splitlines()}

    missing_entries = [entry for entry in SECRET_GITIGNORE_ENTRIES if entry not in existing_lines]
    if not missing_entries:
        return

    content = existing
    if content and not content.endswith("\n"):
        content += "\n"
    if content:
        content += "\n"
    content += "# Local secrets\n" + "\n".join(missing_entries) + "\n"

    with open(gitignore_path, "w", encoding="utf-8") as f:
        f.write(content)

    print("  ✓ .gitignore")


def create_env_from_platform_if_requested(output_dir: Path, assume_defaults: bool = False) -> None:
    """Create an agent .env from selected platform secrets if requested."""
    if not PLATFORM_ENV_PATH.exists():
        return

    selected_values = select_platform_env_values(PLATFORM_ENV_PATH)
    if not selected_values:
        print(f"\nFound '{PLATFORM_ENV_PATH}', but none of the requested platform values were present.")
        return

    local_sdk = "LOCAL_SDK" in selected_values
    create_env = confirm_action(
        f"\nFound '{PLATFORM_ENV_PATH}'. Create '{output_dir / '.env'}' with "
        "DeepLynx client (DEEPLYNX_KEY, ...), AGENT_SECRET, REDIS_PASSWORD, "
        "LLM_CONFIG_PROFILE, LLM_API_KEY, EMBEDDING_API_KEY, and USER_IDENTITY_* values"
        f"{' (and the locally built base image, LOCAL_SDK=true)' if local_sdk else ''}? (yes/no)",
        "yes",
        assume_defaults,
    )
    if not create_env:
        if local_sdk:
            print(
                "\nNote: the platform uses LOCAL_SDK=true. Set LOCAL_SDK=true in the "
                "agent's .env, or its build pulls the base image from the registry."
            )
        return

    env_path = output_dir / ".env"
    if env_path.exists():
        overwrite = confirm_action(
            f"\nWarning: '{env_path}' already exists. Replace it? (yes/no)", "no", assume_defaults
        )
        if not overwrite:
            return

    write_agent_env(output_dir, selected_values)


def write_agent_env(output_dir: Path, selected_values: dict[str, str]) -> None:
    """Write the agent .env from the selected platform values and gitignore it."""
    lines = [
        "# Created by setup_agent.py from ../platform/.env.",
        "# Contains shared platform secrets needed by this agent.",
        "",
    ]
    lines.extend(f"{key}={value}" for key, value in selected_values.items())
    lines.extend(
        [
            "",
            "# Uncomment this for external network mode",
            "#EXTERNAL_AGENT_HOST=prometheus.host.internal",
            "#EXTERNAL_AGENT_PORT=8042",
            "#REGISTRY_URL=http://prometheus.host.internal:8600",
            "#REDIS_URL=redis://prometheus.host.internal:6379",
        ]
    )

    with open(output_dir / ".env", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    ensure_secret_gitignore_entries(output_dir)
    print("  ✓ .env")


def write_env_only(agent_dir: Path) -> None:
    """Write only the .env of an existing agent directory from ../platform/.env."""
    if not (agent_dir / "agent_card.json").is_file():
        print(f"\nError: '{agent_dir}' has no agent_card.json; is it an agent directory?")
        sys.exit(1)
    if not PLATFORM_ENV_PATH.exists():
        print(f"\nError: '{PLATFORM_ENV_PATH}' not found. Run `make init-env` in platform/ first.")
        sys.exit(1)
    selected_values = select_platform_env_values(PLATFORM_ENV_PATH)
    if not selected_values:
        print(f"\nError: '{PLATFORM_ENV_PATH}' has none of the values an agent needs.")
        sys.exit(1)
    if (agent_dir / ".env").exists():
        print(f"\nReplacing '{agent_dir / '.env'}'.")
    write_agent_env(agent_dir, selected_values)


def process_file(file_path: Path, replacements: dict[str, str], output_dir: Path) -> None:
    """Process a single file, replacing placeholders."""
    # Read the file
    with open(file_path, encoding="utf-8") as f:
        content = f.read()

    # Replace placeholders
    new_content = replace_placeholders(content, replacements)

    # Determine output path
    relative_path = file_path.relative_to(Path(__file__).parent / "agent_template")
    output_path = output_dir / relative_path

    # Create output directory if needed
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write the file
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"  ✓ {relative_path}")


def create_agent(replacements: dict[str, str], assume_defaults: bool = False) -> None:
    """Create a new agent from the template.

    With ``assume_defaults`` (--yes), an existing output directory is an error
    rather than a prompt to overwrite it.
    """
    template_dir = Path(__file__).parent / "agent_template"
    output_dir = Path(replacements["OUTPUT_DIR"])

    # Check if template exists
    if not template_dir.exists():
        print(f"\nError: Template directory '{template_dir}' not found.")
        sys.exit(1)

    # Check if output directory already exists
    if output_dir.exists() and assume_defaults:
        print(f"\nError: Directory '{output_dir}' already exists; --yes never overwrites it.")
        sys.exit(1)
    if output_dir.exists():
        overwrite = get_user_input(
            f"\nWarning: Directory '{output_dir}' already exists.\n"
            f"Overwriting DELETES everything in it, including any code you have written. Overwrite? (yes/no)",
            "no",
        )
        if overwrite.lower() not in ["yes", "y"]:
            print("\nSetup cancelled.")
            sys.exit(0)
        shutil.rmtree(output_dir)

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nCreating agent in '{output_dir}'...")
    print()

    # Process all files in template
    for file_path in template_dir.rglob("*"):
        # Skip directories, hidden files, and Python cache files
        if not file_path.is_file():
            continue
        relative_parts = file_path.relative_to(template_dir).parts
        if file_path.name not in {".dockerignore", ".env.example", ".python-version"} and any(
            part.startswith(".") for part in relative_parts
        ):
            continue
        if "__pycache__" in file_path.parts:
            continue
        if file_path.suffix in [".pyc", ".pyo", ".pyd", ".so", ".dll"]:
            continue
        # Locks the template's own name; the new agent's first uv sync locks its own
        if file_path.name == "uv.lock":
            continue

        process_file(file_path, replacements, output_dir)

    apply_design_pattern(output_dir, replacements)

    # Strip comments from agent.py if requested
    if replacements["TRIM_COMMENTS"].strip().lower() in {"true", "yes", "y", "1"}:
        agent_py = output_dir / "agent.py"
        if agent_py.exists():
            with open(agent_py, encoding="utf-8") as f:
                content = f.read()
            with open(agent_py, "w", encoding="utf-8") as f:
                f.write(strip_comments(content))
            print("  ✓ Trimmed comments from agent.py")

    create_env_from_platform_if_requested(output_dir, assume_defaults)

    print()
    message_file = Path(__file__).parent / "success_message.txt"
    with open(message_file, encoding="utf-8") as f:
        message = f.read().format(output_dir=output_dir, slug=replacements["TEMPLATE_SLUG"])
    print(message)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse the optional positional agent name and output directory."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        usage=argparse.SUPPRESS,
    )
    parser.add_argument("agent_name", nargs="?", help="agent name, e.g. 'Plant Analysis'")
    parser.add_argument("output_directory", nargs="?", help="where to create the agent (default: ../<slug>)")
    parser.add_argument(
        "--env-only",
        metavar="AGENT_DIR",
        help="only write AGENT_DIR/.env from ../platform/.env (for an agent you already have)",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="accept every default without prompting (needs agent_name; never overwrites)",
    )
    parser.add_argument("--pattern", metavar="SLUG", help="design pattern to scaffold (see --list-patterns)")
    parser.add_argument(
        "--framework",
        metavar="SLUG",
        help=f"also build the pattern with an agent framework: {', '.join(frameworks.framework_slugs())}",
    )
    parser.add_argument("--llm", action="store_true", help="ask the platform's LLM to suggest the pattern")
    parser.add_argument("--list-patterns", action="store_true", help="list the design patterns and exit")
    args = parser.parse_args(argv)
    if args.list_patterns:
        return args
    pattern_flags = args.pattern or args.framework or args.llm
    if args.env_only and (args.agent_name or args.output_directory or args.yes or pattern_flags):
        parser.error("--env-only takes no other arguments")
    if args.yes and not args.agent_name:
        parser.error("--yes needs the agent name")
    catalog = patterns.load_catalog()
    if args.pattern and args.pattern not in catalog.architectures:
        parser.error(f"unknown --pattern {args.pattern!r}; see --list-patterns")
    if args.framework and args.framework not in {patterns.NATIVE_FRAMEWORK, *catalog.frameworks}:
        parser.error(f"unknown --framework {args.framework!r}; see --list-patterns")
    return args


def main(argv: list[str] | None = None):
    """Main entry point."""
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if args.list_patterns:
        print(list_patterns_text())
        return

    if args.env_only:
        write_env_only(Path(args.env_only).expanduser())
        return

    # Collect agent information
    replacements = collect_agent_info(
        args.agent_name, args.output_directory, args.yes, args.pattern, args.framework, args.llm
    )

    # Create the agent
    create_agent(replacements, args.yes)


if __name__ == "__main__":
    main()
