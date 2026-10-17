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
    python setup_agent.py --env-only <agent_directory>

Arguments given on the command line are not prompted for; everything else
is (press Enter to accept a default). With no arguments, every value is
prompted for.

Example:
    python setup_agent.py "Plant Analysis" ./plant-agent
    python setup_agent.py "Data Validator"
    python setup_agent.py
    python setup_agent.py --env-only ../../my-team-agent

--env-only writes only the .env of an agent you already have (for example a
clone of a teammate's agent repo), from this clone's ../platform/.env.
"""

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

PLATFORM_ENV_PATH = Path(__file__).resolve().parent.parent / "platform" / ".env"
PLATFORM_SECRET_KEYS = (
    "AGENT_SECRET",
    "REDIS_PASSWORD",
    "LITELLM_MASTER_KEY",
    # Multi-user identity (RS256, verification-side only -- never the private
    # key). ISS/AUD are copied too since a mismatch here silently fails
    # verification even with a correct public key.
    "USER_IDENTITY_PUBLIC_KEY",
    "USER_IDENTITY_ISS",
    "USER_IDENTITY_AUD",
    # Not a secret, but copied for the same reason as ISS/AUD: a scaffolded
    # agent should inherit the platform's inference routing rather than
    # silently defaulting to `registry` when the platform uses something else.
    "LLM_CONFIG_PROFILE",
    # Every profile reads its provider key from LLM_API_KEY, so the agent can
    # call the same provider the platform does; embeddings may need their own.
    "LLM_API_KEY",
    "EMBEDDING_API_KEY",
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


def get_user_input(prompt: str, default: str = "") -> str:
    """Get user input with optional default value."""
    if default:
        response = input(f"{prompt} [{default}]: ").strip()
        return response if response else default
    return input(f"{prompt}: ").strip()


def confirm_action(prompt: str, default: str = "yes") -> bool:
    """Prompt the user for a yes/no confirmation."""
    return get_user_input(prompt, default).lower() in {"yes", "y"}


def collect_agent_info(agent_name: str | None = None, output_dir: str | None = None) -> dict[str, str]:
    """Interactively collect agent information from the user.

    ``agent_name`` and ``output_dir`` come from the command line; when given,
    they are used as-is instead of being prompted for.
    """
    print("\n" + "=" * 70)
    print("  Agent Template Setup")
    print("=" * 70)
    print("\nThis script will help you create a new agent from the template.")
    print("Please provide the following information:\n")

    # Get agent name
    if agent_name:
        print(f"Agent name: {agent_name}")
    while not agent_name:
        agent_name = get_user_input("Agent name (e.g., 'Plant Analysis', 'Data Validator')")
        if not agent_name:
            print("Error: Agent name is required.\n")

    # Generate default values
    default_slug = to_kebab_case(agent_name)
    default_class = to_pascal_case(agent_name)

    # Get description
    description = get_user_input(
        "\nAgent description (brief summary of what it does)", f"A specialized agent for {agent_name.lower()}"
    )

    # Get slug (for directories, files, etc.)
    slug = get_user_input("\nAgent slug (used for directories and Docker)", default_slug)

    # Get class name
    class_name = get_user_input(
        "\nAgent class name (PascalCase, without an 'Agent' suffix — it is appended automatically)",
        default_class,
    )

    # Get skill information
    print("\n" + "-" * 70)
    print("  Primary Skill Configuration")
    print("-" * 70)

    skill_id = get_user_input("\nPrimary skill ID (snake_case)", f"{to_snake_case(agent_name)}_analysis")

    skill_name = get_user_input("\nPrimary skill name", f"{agent_name} Analysis")

    skill_description = get_user_input("\nPrimary skill description", f"Performs analysis using {agent_name.lower()}")

    # Get output directory
    if not output_dir:
        output_dir = get_user_input("\nOutput directory", f"../{slug}")

    # Keep comments in the copied agent.py
    trim_comments = get_user_input(prompt="\nTrim agent.py comments", default="False")

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
    print(f"Output Directory:  {output_dir}")
    print(f"Trim Comments:     {trim_comments}")
    print()

    confirm = get_user_input("Proceed with these settings? (yes/no)", "yes")
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
        content = content.replace(placeholder, value)
    return content


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
    selected = {key: assignments[key] for key in PLATFORM_SECRET_KEYS if key in assignments}

    for key, value in assignments.items():
        if key.startswith("DEEPLYNX_"):
            selected[key] = value

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


def create_env_from_platform_if_requested(output_dir: Path) -> None:
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
        "DEEPLYNX_*, AGENT_SECRET, REDIS_PASSWORD, LITELLM_MASTER_KEY, "
        "LLM_CONFIG_PROFILE, LLM_API_KEY, EMBEDDING_API_KEY, and USER_IDENTITY_* values"
        f"{' (and the locally built base image, LOCAL_SDK=true)' if local_sdk else ''}? (yes/no)",
        "yes",
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
        overwrite = confirm_action(f"\nWarning: '{env_path}' already exists. Replace it? (yes/no)", "no")
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
            "#REGISTRY_URL=http://prometheus.host.internal:9977",
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


def create_agent(replacements: dict[str, str]) -> None:
    """Create a new agent from the template."""
    template_dir = Path(__file__).parent / "agent_template"
    output_dir = Path(replacements["OUTPUT_DIR"])

    # Check if template exists
    if not template_dir.exists():
        print(f"\nError: Template directory '{template_dir}' not found.")
        sys.exit(1)

    # Check if output directory already exists
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
        if file_path.name != ".env.example" and any(part.startswith(".") for part in relative_parts):
            continue
        if "__pycache__" in file_path.parts:
            continue
        if file_path.suffix in [".pyc", ".pyo", ".pyd", ".so", ".dll"]:
            continue

        process_file(file_path, replacements, output_dir)

    # Strip comments from agent.py if requested
    if replacements["TRIM_COMMENTS"].strip().lower() in {"true", "yes", "y", "1"}:
        agent_py = output_dir / "agent.py"
        if agent_py.exists():
            with open(agent_py, encoding="utf-8") as f:
                content = f.read()
            with open(agent_py, "w", encoding="utf-8") as f:
                f.write(strip_comments(content))
            print("  ✓ Trimmed comments from agent.py")

    create_env_from_platform_if_requested(output_dir)

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
    args = parser.parse_args(argv)
    if args.env_only and (args.agent_name or args.output_directory):
        parser.error("--env-only takes no other arguments")
    return args


def main(argv: list[str] | None = None):
    """Main entry point."""
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if args.env_only:
        write_env_only(Path(args.env_only).expanduser())
        return

    # Collect agent information
    replacements = collect_agent_info(args.agent_name, args.output_directory)

    # Create the agent
    create_agent(replacements)


if __name__ == "__main__":
    main()
