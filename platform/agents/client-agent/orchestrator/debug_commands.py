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

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import task_graph
from artifact_handling import merge_artifact_catalogs, summarize_artifacts_for_context
from capability_cache import get_capability_cache
from tool_discovery import discover_agents
from workflow_library import get_workflow_registry, workflow_slug

from . import runtime
from .models import ConversationRequest, ConversationResponse

SLASH_COMMAND_DESCRIPTIONS = {
    "agents": "List registered agents and their advertised skills.",
    "artifacts": "List artifacts registered for this conversation.",
    "forget": "Forget stored OSTI knowledge facts.",
    "help": "List all available commands.",
    "tasks": "List tasks, or inspect one with /tasks <id>.",
    "workflows": "List all currently registered workflows.",
}
SUPPORTED_SLASH_COMMANDS = list(SLASH_COMMAND_DESCRIPTIONS)

_OSTI_KNOWLEDGE_KEY_PATTERNS = (
    ("facts", "osti:factoid:*"),
    ("indexes", "osti:paper:*:facts"),
    ("indexes", "osti:topic:*:factoids"),
)
_REDIS_DELETE_BATCH_SIZE = 500

_STATE_ICONS = {
    "submitted": "•",
    "working": "⏳",
    "input-required": "⌨",
    "completed": "✓",
    "failed": "✗",
    "canceled": "⊘",
    "rejected": "⊘",
}


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


def _is_supported_slash_command_query(query: Optional[str]) -> bool:
    parsed = _parse_slash_command(query)
    return parsed is not None and parsed[0] in SUPPORTED_SLASH_COMMANDS


def _delete_osti_knowledge() -> Dict[str, int]:
    redis_client = runtime._get_status_redis_client()
    deleted = {"facts": 0, "indexes": 0}

    for category, pattern in _OSTI_KNOWLEDGE_KEY_PATTERNS:
        batch = []
        for key in redis_client.scan_iter(match=pattern, count=_REDIS_DELETE_BATCH_SIZE):
            batch.append(key)
            if len(batch) == _REDIS_DELETE_BATCH_SIZE:
                deleted[category] += redis_client.delete(*batch)
                batch.clear()
        if batch:
            deleted[category] += redis_client.delete(*batch)

    return deleted


def _format_debug_skill(skill: Dict[str, Any]) -> str:
    skill_id = str(skill.get("skill_id") or skill.get("id") or "").strip()
    skill_name = str(skill.get("skill_name") or skill.get("name") or "").strip()
    if not skill_id:
        return skill_name or "unnamed-skill"
    if skill_name and skill_name != skill_id:
        return f"`{skill_id}` ({skill_name})"
    return f"`{skill_id}`"


def _agent_sort_key(entry: Dict[str, Any]) -> Tuple[str, str]:
    agent_id = str(entry.get("agent_id") or "")
    display_name = str(entry.get("name") or agent_id)
    return display_name.casefold(), agent_id.casefold()


async def _collect_registered_agent_debug_entries() -> Tuple[List[Dict[str, Any]], List[str]]:
    """Collect registered agents and advertised skills without invoking an LLM."""
    entries_by_id: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []

    # Always force a fresh registry pull so the capability cache used by subsequent
    # prompts reflects the current agent list.
    try:
        await get_capability_cache().refresh()
    except Exception as exc:
        errors.append(f"capability cache refresh failed: {exc}")

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
    entries.sort(key=_agent_sort_key)
    for entry in entries:
        entry["skills"] = sorted(
            entry.get("skills") or [],
            key=lambda skill: str(skill.get("skill_id") or skill.get("skill_name") or "").lower(),
        )
    return entries, errors


def _format_agents_debug_response(entries: List[Dict[str, Any]], errors: List[str]) -> str:
    lines = [f"**Registered agents ({len(entries)})**", ""]
    if not entries:
        lines.append("No registered agents were found.")
    else:
        lines.extend(["Sorted by name, A to Z.", ""])
    for index, entry in enumerate(entries, start=1):
        name = str(entry.get("name") or entry.get("agent_id") or "unnamed-agent")
        agent_id = str(entry.get("agent_id") or "").strip()
        marker = f"{index}. "
        indent = " " * len(marker)
        lines.append(f"{marker}**{name}**")
        if agent_id and agent_id != name:
            lines.append(f"{indent}- ID: `{agent_id}`")
        if entry.get("url"):
            lines.append(f"{indent}- URL: {entry['url']}")
        skills = entry.get("skills") or []
        if skills:
            lines.append(
                f"{indent}- Skills ({len(skills)}): " + ", ".join(_format_debug_skill(skill) for skill in skills)
            )
        else:
            lines.append(f"{indent}- Skills: none advertised")
    if errors:
        lines.extend(["", "**Warnings**", ""])
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


def _workflow_command_entries(catalog: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    entries_by_id: Dict[str, Dict[str, str]] = {}
    for workflow in catalog:
        workflow_id = str(workflow.get("id") or "").strip()
        if not workflow_id:
            continue
        entries_by_id[workflow_id] = {
            "command": workflow_slug(workflow_id),
            "workflow_id": workflow_id,
            "workflow_version": str(workflow.get("version") or ""),
            "display_name": str(workflow.get("display_name") or workflow_id),
        }
    return sorted(entries_by_id.values(), key=lambda entry: entry["command"])


def _format_workflows_response(catalog: List[Dict[str, Any]]) -> str:
    lines = [f"Registered workflows ({len(catalog)})"]
    if not catalog:
        lines.extend(["", "No workflows are currently registered."])
        return "\n".join(lines)

    groups = (
        ("Platform-owned workflows", [item for item in catalog if item.get("source") != "agent_card"]),
        ("Agent-owned workflows", [item for item in catalog if item.get("source") == "agent_card"]),
    )
    for heading, workflows in groups:
        lines.extend(["", f"{heading} ({len(workflows)})"])
        if not workflows:
            lines.append("- None")
            continue
        for workflow in workflows:
            workflow_id = str(workflow.get("id") or "unnamed-workflow")
            display_name = str(workflow.get("display_name") or workflow_id)
            lines.append(f"- {display_name} (`/{workflow_slug(workflow_id)}`)")
            version = str(workflow.get("version") or "unknown")
            details = f"  id: {workflow_id}@{version}"
            owner = str(workflow.get("owner") or "").strip()
            if owner:
                details += f" — owner: {owner}"
            lines.append(details)
            summary = str(workflow.get("summary") or "").strip()
            if summary:
                lines.append(f"  {summary}")
    return "\n".join(lines)


def _format_help_response(workflow_commands: List[Dict[str, str]]) -> str:
    total = len(SUPPORTED_SLASH_COMMANDS) + len(workflow_commands)
    lines = [f"Available commands ({total})", "", f"Built-in commands ({len(SUPPORTED_SLASH_COMMANDS)})"]
    lines.extend(
        f"- `/{command}` — {SLASH_COMMAND_DESCRIPTIONS[command]}"
        for command in SUPPORTED_SLASH_COMMANDS
    )
    lines.extend(["", f"Workflow commands ({len(workflow_commands)})"])
    if not workflow_commands:
        lines.append("- None currently registered")
    else:
        for entry in workflow_commands:
            workflow_ref = entry["workflow_id"]
            if entry["workflow_version"]:
                workflow_ref += f"@{entry['workflow_version']}"
            lines.append(
                f"- `/{entry['command']}` — {entry['display_name']} ({workflow_ref})"
            )
    return "\n".join(lines)


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _elapsed(node: Dict[str, Any]) -> Optional[str]:
    """Human-readable elapsed time for a node (start → finish or now)."""
    start = _parse_iso(node.get("started_at") or node.get("created_at"))
    if start is None:
        return None
    end = _parse_iso(node.get("finished_at")) or datetime.now(timezone.utc)
    seconds = max(0, int((end - start).total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"


def _node_label(node: Dict[str, Any]) -> str:
    state = str(node.get("state") or "unknown")
    icon = _STATE_ICONS.get(state, "•")
    title = str(node.get("title") or node.get("skill") or node.get("task_id") or "task")
    short_id = str(node.get("task_id") or "")[:10]
    parts = [f"{icon} {title}  [{state}]"]
    elapsed = _elapsed(node)
    if elapsed:
        parts.append(f"({elapsed})")
    if short_id:
        parts.append(f"<{short_id}>")
    line = "  ".join(parts)
    message = str(node.get("last_status_message") or "").strip()
    if message and state in ("working", "input-required"):
        line += f" — {message}"
    return line


def _render_tree_lines(node: Dict[str, Any], depth: int = 0) -> List[str]:
    indent = "  " * depth + ("└─ " if depth else "")
    lines = [indent + _node_label(node)]
    for child in node.get("children") or []:
        lines.extend(_render_tree_lines(child, depth + 1))
    return lines


def _format_tasks_list(trees: List[Dict[str, Any]]) -> str:
    active = sum(
        1
        for tree in trees
        if str(tree.get("state")) not in task_graph.TERMINAL_STATES
    )
    header = f"Tasks ({len(trees)} total, {active} active)"
    if not trees:
        return header + "\n\nNo tasks have run in this conversation yet."
    lines = [header, "", "```text"]
    for tree in trees:
        lines.extend(_render_tree_lines(tree))
    lines.append("```")
    lines.append("")
    lines.append("Use `/tasks <id>` to inspect a task.")
    return "\n".join(lines)


def _format_task_detail(conversation_id: str, task_id: str) -> str:
    # Allow short-id prefixes for convenience.
    node = task_graph.get_node(conversation_id, task_id)
    if node is None:
        for candidate in task_graph.list_nodes(conversation_id):
            if candidate.task_id.startswith(task_id):
                node = candidate
                break
    if node is None:
        return f"No task found matching '{task_id}' in this conversation."

    data = node.to_dict()
    lines = [f"Task {node.task_id}", "", "```text"]
    lines.append(f"  state:   {node.state}")
    if node.agent:
        lines.append(f"  agent:   {node.agent}")
    if node.skill:
        lines.append(f"  skill:   {node.skill}")
    if node.title:
        lines.append(f"  title:   {node.title}")
    elapsed = _elapsed(data)
    if elapsed:
        lines.append(f"  elapsed: {elapsed}")
    if node.last_status_message:
        lines.append(f"  status:  {node.last_status_message}")
    if node.waiting_on:
        lines.append(f"  waiting on: {', '.join(t[:10] for t in node.waiting_on)}")
    if node.result_ref:
        lines.append(f"  result:  {node.result_ref}")
    if node.error:
        lines.append(f"  error:   {node.error}")

    subtree = next(
        (t for t in task_graph.build_tree(conversation_id) if _find_in_tree(t, node.task_id)),
        None,
    )
    rendered = _subtree_for(subtree, node.task_id) if subtree else None
    if rendered and (rendered.get("children")):
        lines.append("")
        lines.append("  subtree:")
        for child in rendered["children"]:
            lines.extend("  " + ln for ln in _render_tree_lines(child, 1))
    lines.append("```")
    return "\n".join(lines)


def _find_in_tree(tree: Dict[str, Any], task_id: str) -> bool:
    if tree.get("task_id") == task_id:
        return True
    return any(_find_in_tree(c, task_id) for c in tree.get("children") or [])


def _subtree_for(tree: Optional[Dict[str, Any]], task_id: str) -> Optional[Dict[str, Any]]:
    if tree is None:
        return None
    if tree.get("task_id") == task_id:
        return tree
    for child in tree.get("children") or []:
        found = _subtree_for(child, task_id)
        if found is not None:
            return found
    return None


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
    if command == "help":
        catalog = get_workflow_registry().get_catalog() if runtime.ENABLE_WORKFLOW_LIBRARY else []
        workflow_commands = _workflow_command_entries(catalog)
        message = _format_help_response(workflow_commands)
        runtime.store_status_update(conv_id, "Handled /help slash command.", final=True)
        return ConversationResponse(
            conversation_id=conv_id,
            status="answer",
            message=message,
            response_text=message,
            message_metadata={
                "slash_command": "help",
                "supported_commands": list(SUPPORTED_SLASH_COMMANDS),
                "workflow_commands": workflow_commands,
            },
        )

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

    if command == "forget":
        deleted = await asyncio.to_thread(_delete_osti_knowledge)
        facts_deleted = deleted["facts"]
        fact_label = "fact" if facts_deleted == 1 else "facts"
        message = (
            f"Forgot {facts_deleted} stored OSTI knowledge {fact_label}. "
            "Cached papers and answers, task state, and conversation data were not changed."
        )
        runtime.store_status_update(conv_id, "Handled /forget slash command.", final=True)
        return ConversationResponse(
            conversation_id=conv_id,
            status="answer",
            message=message,
            response_text=message,
            message_metadata={
                "slash_command": "forget",
                "facts_deleted": facts_deleted,
                "index_keys_deleted": deleted["indexes"],
            },
        )

    if command == "tasks":
        if _args:
            message = _format_task_detail(conv_id, _args.split()[0])
            metadata: Dict[str, Any] = {"slash_command": "tasks", "task_id": _args.split()[0]}
        else:
            trees = task_graph.build_tree(conv_id)
            message = _format_tasks_list(trees)
            metadata = {"slash_command": "tasks", "tasks": trees}
        runtime.store_status_update(conv_id, "Handled /tasks slash command.", final=True)
        return ConversationResponse(
            conversation_id=conv_id,
            status="answer",
            message=message,
            response_text=message,
            message_metadata=metadata,
        )

    if command == "workflows":
        catalog = get_workflow_registry().get_catalog() if runtime.ENABLE_WORKFLOW_LIBRARY else []
        message = _format_workflows_response(catalog)
        runtime.store_status_update(conv_id, "Handled /workflows slash command.", final=True)
        return ConversationResponse(
            conversation_id=conv_id,
            status="answer",
            message=message,
            response_text=message,
            message_metadata={
                "slash_command": "workflows",
                "workflows": catalog,
            },
        )

    supported = ", ".join(f"/{cmd}" for cmd in SUPPORTED_SLASH_COMMANDS)
    message = f"Unknown slash command '/{command}'. Supported commands: {supported}."
    runtime.store_status_update(conv_id, f"Unknown slash command '/{command}'.", final=True)
    return ConversationResponse(
        conversation_id=conv_id,
        status="answer",
        message=message,
        response_text=message,
        message_metadata={
            "slash_command": command,
            "supported_commands": list(SUPPORTED_SLASH_COMMANDS),
        },
    )
