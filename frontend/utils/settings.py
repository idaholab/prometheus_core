import argparse
import os
from typing import Any
from pydantic_settings import BaseSettings
import yaml
from pathlib import Path

CONFIG_PATH = os.environ.get(
    "PROMETHEUS_CONFIG_PATH",
    str(Path(__file__).parent.parent / "config.yml"),
)
MAX_UPLOAD_BYTES_ENV = "PROMETHEUS_MAX_UPLOAD_BYTES"
DEFAULT_MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def read_config(config_file_path: str):
    try:
        with open(config_file_path, "r") as f:
            data = yaml.safe_load(f) or {}
        return data
    except FileNotFoundError:
        raise FileNotFoundError(f"Config file not found: {config_file_path}")
    except yaml.YAMLError as e:
        raise RuntimeError(f"Invalid YAML: {e}")


def _positive_int(value: Any, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def get_max_upload_bytes(data: dict[str, Any]) -> int:
    env_value = os.environ.get(MAX_UPLOAD_BYTES_ENV)
    if env_value is not None and env_value.strip():
        return _positive_int(env_value, MAX_UPLOAD_BYTES_ENV)
    return _positive_int(data.get("max-upload-bytes", DEFAULT_MAX_UPLOAD_BYTES), "max-upload-bytes")


class Settings(BaseSettings):
    data: dict[str, Any] = read_config(CONFIG_PATH)
    local_users: list[dict[str, str]] = data.get("local-users", [])
    workflow_suggestions: list[str] = data["workflow-suggestions"]
    chat_suggestion_title: str = data["chat-suggestion-title"]
    chat_intro: str = data["chat-intro"]
    ifc_data_dir: Path = Path(__file__).parent.parent / "public" / "ifc-data"
    mesh_data_dir: Path = Path(__file__).parent.parent / "public" / "mesh-data"
    agent_url: str = os.environ.get("CLIENT_AGENT_URL", data.get("agent-url", "http://localhost:8001"))
    agent_secret: str = os.environ.get("AGENT_SECRET", data.get("agent-secret", ""))
    redis_url: str = os.environ.get("REDIS_URL", data.get("redis-url", "redis://localhost:6379"))
    max_upload_bytes: int = get_max_upload_bytes(data)
    debug: bool = data.get("debug", True)
    auto_approve_steps: bool = data.get("auto-approve-steps", False)
    # Identity settings: the frontend mints a short-lived internal JWT for every
    # turn and attaches it to the A2A request.  Agents verify this token.
    user_identity_secret: str = os.environ.get("USER_IDENTITY_SECRET", "")
    user_identity_alg: str = os.environ.get("USER_IDENTITY_ALG", "HS256")
    user_identity_iss: str = os.environ.get("USER_IDENTITY_ISS", "prometheus-platform")
    user_identity_aud: str = os.environ.get("USER_IDENTITY_AUD", "prometheus-agents")
    user_identity_ttl: int = int(os.environ.get("USER_IDENTITY_TTL", "7200"))

settings = Settings()


def parse_args() -> argparse.Namespace: ...
