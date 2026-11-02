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

"""Create or complete the platform .env from .env.example.

1. Copy .env.example to .env if .env does not exist.
2. For every variable in .env.example whose comment block carries a
   ``python3 -c "..."`` one-liner, fill a blank value in .env by running it.
   Values that are already set are never touched.
3. If LLM_CONFIG_PROFILE, or the API key it needs, is blank, take it from the
   environment if it is set there (as in CI). Otherwise, if the script runs in
   a terminal, offer a profile menu (arrow keys, Enter) and prompt for that
   profile's key. Otherwise exit non-zero. There is no default profile.

Standard library only, so it runs before anything else is installed. Run from
anywhere; paths resolve relative to this file.
"""

from __future__ import annotations

import getpass
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / ".env.example"
ENV = ROOT / ".env"

ASSIGNMENT = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
ONE_LINER = re.compile(r'^#\s*python3 -c "(.+)"\s*$')

# One profile per YAML here.
LLM_CONFIGS = ROOT.parent / "sdk" / "prometheus_api" / "llm_configs"
# Installed by the SDK but unusable on this platform: "registry" sends LLM calls to
# REGISTRY_URL, which here is the backend's agent registry, not an LLM proxy.
UNSUPPORTED_PROFILES = {"registry"}

API_KEY_REF = re.compile(r"os\.environ/([A-Z][A-Z0-9_]*_API_KEY)")
# Shared by several profiles for embeddings only; never the key a profile needs.
EMBEDDING_KEY = "EMBEDDING_API_KEY"


def provider_key(yaml: Path) -> str | None:
    """The API key a config references most often, ignoring the embedding key."""
    refs = [k for k in API_KEY_REF.findall(yaml.read_text()) if k != EMBEDDING_KEY]
    return max(set(refs), key=refs.count) if refs else None


def description(yaml: Path) -> str:
    """The first sentence of the config's header comment, minus 'inference scaffold'."""
    first = next((line for line in yaml.read_text().splitlines() if line.startswith("#")), "#")
    sentence = first.lstrip("# ").split(". ")[0].rstrip(".")
    return re.sub(r"\s*inference scaffold$", "", sentence)


def profiles() -> dict[str, tuple[str | None, str]]:
    """LLM_CONFIG_PROFILE -> (provider key it cannot start without, description), alphabetically."""
    if not LLM_CONFIGS.is_dir():
        raise SystemExit(f"[ERROR] LLM config profiles not found at {LLM_CONFIGS}.")
    return {
        yaml.stem: (provider_key(yaml), description(yaml))
        for yaml in sorted(LLM_CONFIGS.glob("*.yaml"))
        if yaml.stem not in UNSUPPORTED_PROFILES
    }


def generators(example: str) -> dict[str, str]:
    """Map each variable to the one-liner in the comment block directly above it."""
    found: dict[str, str] = {}
    pending: str | None = None
    for line in example.splitlines():
        if m := ONE_LINER.match(line):
            pending = m.group(1)
        elif m := ASSIGNMENT.match(line):
            if pending:
                found[m.group(1)] = pending
            pending = None
        elif not line.startswith("#"):
            pending = None
    return found


def values(text: str) -> dict[str, str]:
    return {m.group(1): m.group(2).strip() for line in text.splitlines() if (m := ASSIGNMENT.match(line))}


def set_var(text: str, var: str, value: str) -> str:
    """Replace the first ``var=`` line, or append one if there is none."""
    if re.search(rf"^{var}=", text, flags=re.M):
        return re.sub(rf"^{var}=.*$", lambda _: f"{var}={value}", text, count=1, flags=re.M)
    return text.rstrip("\n") + f"\n{var}={value}\n"


def fill_secrets(text: str, gens: dict[str, str]) -> tuple[str, list[str]]:
    current = values(text)
    filled = []
    for var, code in gens.items():
        if current.get(var, ""):
            continue
        secret = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
        text = set_var(text, var, secret)
        filled.append(var)
    return text, filled


def missing_profile(env: dict[str, str]) -> bool:
    """True if neither LLM_CONFIG_PROFILE nor a custom LLM_CONFIG_FILE is set."""
    return not env.get("LLM_CONFIG_FILE") and not env.get("LLM_CONFIG_PROFILE")


def unknown_profile(env: dict[str, str]) -> str | None:
    """The selected LLM_CONFIG_PROFILE if no usable installed profile has that name."""
    if env.get("LLM_CONFIG_FILE") or not env.get("LLM_CONFIG_PROFILE"):
        return None  # a custom YAML replaces the profile; a blank one is missing_profile
    profile = env["LLM_CONFIG_PROFILE"]
    return None if profile in profiles() else profile


def missing_llm_key(env: dict[str, str]) -> str | None:
    """The blank provider key required by the selected profile, if any."""
    if env.get("LLM_CONFIG_FILE"):
        return None  # a custom YAML decides which keys it needs
    key, _ = profiles().get(env.get("LLM_CONFIG_PROFILE", ""), (None, ""))
    return key if key and not env.get(key) else None


def interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def choose(options: list[str], labels: list[str], default: int) -> str:
    """Arrow-key menu on the terminal; numbered prompt where termios is missing."""
    width = max(map(len, options))
    lines = [f"{o:<{width}}  {label}" for o, label in zip(options, labels, strict=True)]
    try:
        import termios
        import tty
    except ImportError:
        for i, line in enumerate(lines, 1):
            print(f"  {i}. {line}")
        answer = input(f"Choice [{default + 1}]: ").strip()
        return options[int(answer) - 1] if answer.isdigit() and 1 <= int(answer) <= len(options) else options[default]

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    index = default

    def draw(first: bool) -> None:
        if not first:
            sys.stdout.write(f"\x1b[{len(lines)}A")
        for i, line in enumerate(lines):
            marker = "\x1b[7m> " if i == index else "  "
            sys.stdout.write(f"\r\x1b[2K{marker}{line}\x1b[0m\n")
        sys.stdout.flush()

    sys.stdout.write("\x1b[?25l")  # hide cursor
    try:
        tty.setcbreak(fd)
        draw(first=True)
        while True:
            key = os.read(fd, 3)
            if key in (b"\r", b"\n"):
                return options[index]
            if key in (b"\x1b[A", b"k"):
                index = (index - 1) % len(options)
            elif key in (b"\x1b[B", b"j"):
                index = (index + 1) % len(options)
            draw(first=False)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()


def prompt_llm(text: str) -> str:
    """Ask for the LLM profile and its API key; return the updated .env text."""
    env = values(text)
    known = profiles()
    options = list(known)
    labels = [desc if key else f"{desc}  [no key]" for key, desc in known.values()]
    current = env.get("LLM_CONFIG_PROFILE", "")
    print("\nChoose an LLM profile (up/down, Enter):")
    profile = choose(options, labels, options.index(current) if current in options else 0)
    text = set_var(text, "LLM_CONFIG_PROFILE", profile)
    key, _ = known[profile]
    if key and not env.get(key):
        secret = getpass.getpass(f"{key} for {profile} (input hidden): ").strip()
        if secret:
            text = set_var(text, key, secret)
    return text


def main() -> int:
    if not ENV.exists():
        shutil.copyfile(EXAMPLE, ENV)
        # Owner-only before any secret is written to it. Later rewrites keep this mode. An
        # existing .env is left as it is
        ENV.chmod(0o600)
        print(f"Created {ENV.name} from {EXAMPLE.name}.")

    text, filled = fill_secrets(ENV.read_text(), generators(EXAMPLE.read_text()))
    if filled:
        ENV.write_text(text)
        print(f"Generated in {ENV.name}: {', '.join(filled)}")

    env = values(text)
    if missing_profile(env) and os.environ.get("LLM_CONFIG_PROFILE"):
        text = set_var(text, "LLM_CONFIG_PROFILE", os.environ["LLM_CONFIG_PROFILE"])
        ENV.write_text(text)
        env = values(text)
        print(f"Saved LLM_CONFIG_PROFILE from the environment in {ENV.name}.")
    if (key := missing_llm_key(env)) and os.environ.get(key):
        text = set_var(text, key, os.environ[key])
        ENV.write_text(text)
        env = values(text)
        print(f"Saved {key} from the environment in {ENV.name}.")
    if (missing_profile(env) or unknown_profile(env) or missing_llm_key(env)) and interactive():
        text = prompt_llm(text)
        ENV.write_text(text)
        env = values(text)
        print(f"Saved LLM_CONFIG_PROFILE={env['LLM_CONFIG_PROFILE']} in {ENV.name}.")
    if missing_profile(env):
        print(
            f"\n[ERROR] LLM_CONFIG_PROFILE is empty in {ENV}.\n"
            f"        Available profiles: {', '.join(profiles())}.\n"
            f"        Set it (or set LLM_CONFIG_FILE) and run make again.\n",
            file=sys.stderr,
        )
        return 1
    if profile := unknown_profile(env):
        reason = (
            "is not supported on this platform (it needs an LLM proxy at REGISTRY_URL)"
            if profile in UNSUPPORTED_PROFILES
            else "is not an installed profile"
        )
        print(
            f"\n[ERROR] LLM_CONFIG_PROFILE={profile} in {ENV} {reason}.\n"
            f"        Available profiles: {', '.join(profiles())}.\n"
            f"        Fix it (or set LLM_CONFIG_FILE) and run make again.\n",
            file=sys.stderr,
        )
        return 1
    if key := missing_llm_key(env):
        profile = env["LLM_CONFIG_PROFILE"]
        print(
            f"\n[ERROR] {key} is empty in {ENV}.\n"
            f"        LLM_CONFIG_PROFILE={profile} needs it; set it (or pick another profile)\n"
            f"        and run make again. See README.md, 'Choose an LLM profile'.\n",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
