from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from artifact_handling import merge_artifact_catalogs, summarize_artifacts_for_context
from capability_cache import get_capability_cache
from tool_discovery import discover_agents

from . import runtime
from .models import ConversationRequest, ConversationResponse


def _parse_slash_command(query: Optional[str]) -> Optional[Tuple[str, str]]:
    """Return (command, args) when the user query is a slash command."""
    text = str(query or "").lstrip()
    if not text.startswith("/"):
        return None
    token, _, args = text.partition(" ")
    command = token[1:].strip().lower()
    if not command:
        command = "help"
    return command, args.strip()


def _is_slash_command_query(query: Optional[str]) -> bool:
    return _parse_slash_command(query) is not None


def _format_debug_skill(skill: Dict[str, Any]) -> str:
    skill_id = str(skill.get("skill_id") or skill.get("id") or "").strip()
    skill_name = str(skill.get("skill_name") or skill.get("name") or "").strip()
    if skill_id and skill_name and skill_name != skill_id:
        return f"{skill_id} ({skill_name})"
    return skill_id or skill_name or "unnamed-skill"


async def _collect_registered_agent_debug_entries() -> Tuple[List[Dict[str, Any]], List[str]]:
    """Collect registered agents and advertised skills without invoking an LLM."""
    entries_by_id: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []

    try:
        for agent in await discover_agents():
            if not isinstance(agent, dict):
                continue
            agent_id = str(agent.get("agent_id") or agent.get("agent_name") or "").strip()
            if not agent_id:
                continue
            card = agent.get("agent_card_params") if isinstance(agent.get("agent_card_params"), dict) else {}
            skills = []
            for skill in card.get("skills") or []:
                if isinstance(skill, dict):
                    skills.append(
                        {
                            "skill_id": str(skill.get("id") or "").strip(),
                            "skill_name": str(skill.get("name") or skill.get("id") or "").strip(),
                        }
                    )
            entries_by_id[agent_id] = {
                "agent_id": agent_id,
                "name": str(agent.get("name") or card.get("name") or agent_id),
                "url": str(agent.get("url") or card.get("url") or ""),
                "skills": skills,
            }
    except Exception as exc:
        errors.append(f"agent discovery failed: {exc}")

    try:
        capabilities = await get_capability_cache().get_capabilities()
        for cap in capabilities:
            agent_id = str(getattr(cap, "agent_id", "") or "").strip()
            if not agent_id:
                continue
            entry = entries_by_id.setdefault(
                agent_id,
                {
                    "agent_id": agent_id,
                    "name": str(getattr(cap, "agent_name", None) or agent_id),
                    "url": str(getattr(cap, "agent_url", "") or ""),
                    "skills": [],
                },
            )
            if not entry.get("name"):
                entry["name"] = str(getattr(cap, "agent_name", None) or agent_id)
            if not entry.get("url"):
                entry["url"] = str(getattr(cap, "agent_url", "") or "")
            skill_id = str(getattr(cap, "skill_id", "") or "").strip()
            if not skill_id:
                continue
            known_skill_ids = {str(skill.get("skill_id") or "") for skill in entry["skills"]}
            if skill_id not in known_skill_ids:
                entry["skills"].append(
                    {
                        "skill_id": skill_id,
                        "skill_name": str(getattr(cap, "skill_name", "") or skill_id),
                    }
                )
    except Exception as exc:
        errors.append(f"capability cache failed: {exc}")

    entries = list(entries_by_id.values())
    entries.sort(key=lambda item: (str(item.get("name") or "").lower(), str(item.get("agent_id") or "")))
    for entry in entries:
        entry["skills"] = sorted(
            entry.get("skills") or [],
            key=lambda skill: str(skill.get("skill_id") or skill.get("skill_name") or "").lower(),
        )
    return entries, errors


def _format_agents_debug_response(entries: List[Dict[str, Any]], errors: List[str]) -> str:
    lines = [f"Registered agents ({len(entries)})"]
    if not entries:
        lines.append("")
        lines.append("No registered agents were found.")
    for entry in entries:
        name = str(entry.get("name") or entry.get("agent_id") or "unnamed-agent")
        agent_id = str(entry.get("agent_id") or "").strip()
        header = f"- {name}"
        if agent_id and agent_id != name:
            header += f" ({agent_id})"
        lines.append(header)
        if entry.get("url"):
            lines.append(f"  url: {entry['url']}")
        skills = entry.get("skills") or []
        if skills:
            lines.append("  skills: " + ", ".join(_format_debug_skill(skill) for skill in skills))
        else:
            lines.append("  skills: none advertised")
    if errors:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"- {error}" for error in errors)
    return "\n".join(lines)


def _collect_conversation_artifacts_for_debug(
    request_artifacts: List[Dict[str, Any]],
    existing_state: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    state_artifacts: List[Dict[str, Any]] = []
    if isinstance(existing_state, dict):
        context = existing_state.get("context") if isinstance(existing_state.get("context"), dict) else {}
        state_artifacts = summarize_artifacts_for_context((context or {}).get("artifacts"))
    return merge_artifact_catalogs(request_artifacts, state_artifacts)


def _format_artifact_size(size_bytes: Any) -> Optional[str]:
    try:
        size = int(size_bytes)
    except Exception:
        return None
    if size < 0:
        return None
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _format_artifacts_debug_response(artifacts: List[Dict[str, Any]]) -> str:
    lines = [f"Conversation artifacts ({len(artifacts)})"]
    if not artifacts:
        lines.append("")
        lines.append("No artifacts are registered for this conversation.")
        return "\n".join(lines)

    for artifact in artifacts:
        name = str(artifact.get("name") or "unnamed-artifact")
        artifact_id = str(artifact.get("artifact_id") or "").strip()
        lines.append(f"- {name}")
        if artifact_id:
            lines.append(f"  id: {artifact_id}")
        if artifact.get("mime_type"):
            lines.append(f"  type: {artifact['mime_type']}")
        size = _format_artifact_size(artifact.get("size_bytes"))
        if size:
            lines.append(f"  size: {size}")
        if artifact.get("uri"):
            lines.append(f"  uri: {artifact['uri']}")
        metadata = artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}
        if metadata.get("deeplynx_file_id") is not None:
            lines.append(f"  deeplynx_file_id: {metadata['deeplynx_file_id']}")
        if metadata.get("source"):
            lines.append(f"  source: {metadata['source']}")
        description = str(artifact.get("description") or "").strip()
        if description:
            lines.append(f"  description: {description}")
    return "\n".join(lines)


async def _maybe_handle_slash_command(
    request: ConversationRequest,
    conv_id: str,
    existing_state: Optional[Dict[str, Any]],
    request_artifacts: List[Dict[str, Any]],
) -> Optional[ConversationResponse]:
    parsed = _parse_slash_command(request.query)
    if parsed is None:
        return None

    command, _args = parsed
    if command == "agents":
        entries, errors = await _collect_registered_agent_debug_entries()
        message = _format_agents_debug_response(entries, errors)
        runtime.store_status_update(conv_id, "Handled /agents slash command.", final=True)
        return ConversationResponse(
            conversation_id=conv_id,
            status="answer",
            message=message,
            response_text=message,
            message_metadata={
                "slash_command": "agents",
                "agents": entries,
                "warnings": errors,
            },
        )

    if command == "artifacts":
        artifacts = _collect_conversation_artifacts_for_debug(request_artifacts, existing_state)
        message = _format_artifacts_debug_response(artifacts)
        runtime.store_status_update(conv_id, "Handled /artifacts slash command.", final=True)
        return ConversationResponse(
            conversation_id=conv_id,
            status="answer",
            message=message,
            response_text=message,
            artifacts=artifacts,
            message_metadata={
                "slash_command": "artifacts",
                "artifacts": artifacts,
            },
        )

    supported = "/agents, /artifacts"
    message = f"Unknown slash command '/{command}'. Supported commands: {supported}."
    runtime.store_status_update(conv_id, f"Unknown slash command '/{command}'.", final=True)
    return ConversationResponse(
        conversation_id=conv_id,
        status="answer",
        message=message,
        response_text=message,
        message_metadata={
            "slash_command": command,
            "supported_commands": ["agents", "artifacts"],
        },
    )
