"""Prometheus Platform launcher for the Muninn specialist agent."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from muninn.prometheus.runtime import RavenPrometheusAgent

_CONFIG_TEMPLATE = Path(__file__).with_name("muninn.config.template.yaml")
_CONFIG_PATH = Path("/app/.moosenger.yaml")
_CARD_PATH = Path(__file__).with_name("agent_card.json")
_DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"
_DEFAULT_EMBEDDINGS_MODEL = "text-embedding-3-small"


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required for the Muninn platform package.")
    return value


def _optional_env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def _render_config() -> None:
    model_name = _required_env("MODEL_NAME")
    _required_env("OPENAI_API_KEY")

    openai_base = _optional_env("OPENAI_API_BASE", _DEFAULT_OPENAI_BASE)
    preconditioner = _optional_env("MUNINN_PRECONDITIONER_MODEL", model_name)
    embeddings = _optional_env(
        "MUNINN_EMBEDDINGS_MODEL",
        _DEFAULT_EMBEDDINGS_MODEL,
    )
    raven_mcp_url = _optional_env(
        "MUNINN_RAVEN_MCP_URL",
        "http://host.docker.internal:18111",
    )
    raven_mcp_timeout = _optional_env("MUNINN_RAVEN_MCP_TIMEOUT", "120")

    rendered = (
        _CONFIG_TEMPLATE.read_text(encoding="utf-8")
        .replace("__MODEL_NAME__", model_name)
        .replace("__OPENAI_API_BASE__", openai_base)
        .replace("__PRECONDITIONER_MODEL__", preconditioner)
        .replace("__EMBEDDINGS_MODEL__", embeddings)
        .replace("__RAVEN_MCP_URL__", raven_mcp_url)
        .replace("__RAVEN_MCP_TIMEOUT__", raven_mcp_timeout)
    )
    _CONFIG_PATH.write_text(rendered, encoding="utf-8")


def main() -> None:
    """Start the platform-packaged Muninn Prometheus runtime."""
    try:
        _render_config()
    except Exception as exc:
        print(f"Muninn startup configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    RavenPrometheusAgent(
        current_dir=Path("/app"),
        agent_name="Muninn",
        agent_card_path=str(_CARD_PATH),
        config_path=_CONFIG_PATH,
    ).run()


if __name__ == "__main__":
    main()
