import asyncio
import contextlib
import uuid

import chainlit as cl
from typing import Dict, Optional

# Import plugins early so JSX components are copied to public/elements/
# before Chainlit starts serving custom elements.
import plugins as _visualization_plugins  # noqa: F401

from utils.settings import settings
from utils.conversation_state_client import ConversationStateClient
from components.message_handler import message_handler, run_task_notifier
from components.settings_handler import configure_settings, settings_debug_options

# cl.user_session key holding the per-session background-task notifier asyncio.Task.
_TASK_NOTIFIER_KEY = "task_notifier"

_conversation_state_client = ConversationStateClient(settings.redis_url)

@cl.oauth_callback
def oauth_callback(
    provider_id: str,
    token: str,
    raw_user_data: Dict[str, str],
    default_user: cl.User,
) -> Optional[cl.User]:
    # For OIDC/OAuth2 providers, prefer the 'sub' claim as the canonical user_id
    # since it is stable across token refreshes.  Fall back to the default identifier
    # (typically email or username depending on the provider) if sub is absent.
    sub = raw_user_data.get("sub") or raw_user_data.get("user_id")
    if sub:
        return cl.User(
            identifier=sub,
            metadata={
                "display_name": raw_user_data.get("name") or raw_user_data.get("email") or sub,
                "email": raw_user_data.get("email", ""),
                "provider": provider_id,
            },
        )
    return default_user


@cl.password_auth_callback
def auth_callback(username: str, password: str):
    for user in settings.local_users:
        if user.get("username") == username and user.get("password") == password:
            return cl.User(identifier=username, metadata={"role": user.get("role", "user"), "provider": "credentials"})
    return None


@cl.on_message
async def on_message(message: cl.Message):
    content = message.content.strip()

    # Handle /history command
    if content.lower().startswith("/history"):
        await _handle_conversation_history()
        return

    await message_handler(message)


@cl.on_settings_update
async def on_settings_update(settings):
    await settings_debug_options(ui_settings=settings)

@cl.set_chat_profiles
async def chat_profile():
    return [
        cl.ChatProfile(
            name="Beginner Chat",
            markdown_description="This profile provides some suggestions on how to get started.",
            icon="https://picsum.photos/id/29/200",
        ),
        cl.ChatProfile(
            name="Advanced Chat",
            markdown_description="This profile doesn't provide any suggestions.",
            icon="https://picsum.photos/id/28/200",
        ),
    ]

@cl.on_chat_start
async def on_chat_start():
    # Initialize conversation state for A2A multi-turn
    conversation_id = str(uuid.uuid4())
    cl.user_session.set("conversation_id", conversation_id)
    cl.user_session.set("artifacts", [])

    # Capture the authenticated user_id for identity propagation.
    # cl.user_session.get("user") is set by Chainlit after authentication;
    # it is a cl.User object with an .identifier attribute.
    user = cl.user_session.get("user")
    user_id: Optional[str] = getattr(user, "identifier", None) if user else None
    cl.user_session.set("user_id", user_id)

    # Start the single per-session subscriber that posts background-task results
    # out-of-band on completion. Started here so it inherits a live session, and
    # retained in user_session as a strong ref so it isn't garbage-collected.
    notifier = asyncio.create_task(run_task_notifier(cl.context.session, conversation_id))
    cl.user_session.set(_TASK_NOTIFIER_KEY, notifier)

    await configure_settings()

    chat_profile = cl.user_session.get("chat_profile")
    if chat_profile == "Beginner Chat":
        suggestions = cl.CustomElement(
            name="FollowUpSuggestions",
            props={"suggestions": settings.workflow_suggestions, "title": settings.chat_suggestion_title},
        )

        await cl.Message(content=settings.chat_intro, elements=[suggestions]).send()
    else:
        ...


@cl.on_chat_end
async def on_chat_end():
    # Stop the per-session background-task notifier so subscribers don't leak.
    notifier = cl.user_session.get(_TASK_NOTIFIER_KEY)
    if notifier is not None:
        notifier.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await notifier


async def _handle_conversation_history():
    """Display recent conversation history from Redis.

    Scoped to the current user when a user_id is available so that one user
    cannot browse another user's conversation history.
    """
    if not _conversation_state_client.available:
        await cl.Message(content="History unavailable (Redis not connected).").send()
        return

    user_id: Optional[str] = cl.user_session.get("user_id")
    conversations = _conversation_state_client.get_conversation_history(
        limit=20,
        user_id=user_id,
    )
    if not conversations:
        await cl.Message(content="No conversation history found.").send()
        return

    lines = [f"**Recent Conversations ({len(conversations)}):**\n"]
    for conv in conversations:
        conv_id = conv.get("conversation_id", "?")[:8]
        query = conv.get("query", "—")
        status = conv.get("status", "—")
        material = conv.get("material_id") or ""
        timestamp = conv.get("timestamp", "")
        if timestamp:
            timestamp = timestamp[:19]

        status_icon = {"completed": "done", "executing": "running", "plan_ready": "pending"}.get(status, status)
        material_tag = f" | `{material}`" if material else ""
        lines.append(f"**`{conv_id}`** [{status_icon}]{material_tag}")
        if query:
            lines.append(f"> {query[:120]}{'...' if len(query) > 120 else ''}")
        if timestamp:
            lines.append(f"*{timestamp}*")
        lines.append("")

    await cl.Message(content="\n".join(lines)).send()
