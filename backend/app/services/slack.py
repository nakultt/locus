"""
Slack Integration Service
LangChain tools for reading and writing Slack.

Tools are built as closures over the caller's credentials. Nothing is stored at
module level: tool objects are shared across requests, so a module global would
let one user's agent execute with another user's token.

Two tokens are used:
  - bot token  (xoxb-) posts messages and reads channels the bot has joined
  - user token (xoxp-) searches history; bot tokens cannot call search.messages
"""

import logging

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)


# ============== Input schemas ==============

class SendMessageInput(BaseModel):
    channel: str = Field(default="general", description="Channel name (with or without #) or channel ID")
    message: str = Field(description="Message content to send")


class PostUpdateInput(BaseModel):
    channel: str = Field(description="Channel name (with or without #)")
    title: str = Field(description="Update title/heading")
    content: str = Field(description="Update content/body")


class ReadChannelInput(BaseModel):
    channel: str = Field(description="Channel name (with or without #)")
    limit: int = Field(default=20, description="How many recent messages to read (max 100)")


class ReadThreadInput(BaseModel):
    channel: str = Field(description="Channel name (with or without #)")
    thread_ts: str = Field(description="Timestamp of the thread's parent message")


class SearchInput(BaseModel):
    query: str = Field(description="Search terms, e.g. a ticket key or topic")
    count: int = Field(default=10, description="Maximum matches to return (max 20)")


# ============== Helpers ==============

def _resolve_channel_id(client: WebClient, channel: str, cache: dict[str, str]) -> str | None:
    """Map a channel name to its ID, caching the lookup for this tool set."""
    channel = channel.lstrip("#")

    # Already an ID.
    if channel.startswith(("C", "G", "D")) and channel.isupper():
        return channel

    if channel in cache:
        return cache[channel]

    cursor = None
    while True:
        result = client.conversations_list(
            types="public_channel,private_channel", limit=200, cursor=cursor
        )
        for ch in result.get("channels", []):
            cache[ch["name"]] = ch["id"]
        if channel in cache:
            return cache[channel]

        cursor = result.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            return None


def _build_user_resolver(client: WebClient):
    """
    Return a function mapping user IDs to display names.

    The whole user list is fetched once and cached. Calling users.info per
    message exhausts the rate limit quickly on any busy channel.
    """
    cache: dict[str, str] = {}
    loaded = False

    def resolve(user_id: str) -> str:
        nonlocal loaded
        if not user_id:
            return "unknown"
        if not loaded:
            try:
                cursor = None
                while True:
                    result = client.users_list(limit=200, cursor=cursor)
                    for member in result.get("members", []):
                        profile = member.get("profile", {})
                        cache[member["id"]] = (
                            profile.get("display_name")
                            or profile.get("real_name")
                            or member.get("name", member["id"])
                        )
                    cursor = result.get("response_metadata", {}).get("next_cursor")
                    if not cursor:
                        break
            except SlackApiError as e:
                logger.warning("Could not load Slack user list: %s", e)
            loaded = True
        return cache.get(user_id, user_id)

    return resolve


# ============== Tool factory ==============

def get_slack_tools(bot_token: str, user_token: str = "") -> list[BaseTool]:
    """
    Build Slack tools bound to one user's credentials.

    Args:
        bot_token: Bot token (xoxb-) for posting and channel reads
        user_token: User token (xoxp-) for search. Without it, the search tool
            is not offered at all, so the agent cannot try and silently fail.

    Returns:
        LangChain tools closed over these credentials.
    """
    if not bot_token:
        return []

    client = WebClient(token=bot_token)
    channel_cache: dict[str, str] = {}
    resolve_user = _build_user_resolver(client)

    @tool("slack_send_message", args_schema=SendMessageInput)
    def slack_send_message(channel: str = "general", message: str = "") -> str:
        """Send a message to a Slack channel."""
        if not message:
            return "Error: message is empty."
        try:
            channel_id = _resolve_channel_id(client, channel, channel_cache)
            if not channel_id:
                return f"Error: channel #{channel.lstrip('#')} not found."

            response = client.chat_postMessage(channel=channel_id, text=message)
            return f"Message sent to #{channel.lstrip('#')} (ts {response['ts']})."
        except SlackApiError as e:
            return f"Error sending Slack message: {e.response.get('error', e)}"
        except Exception as e:
            return f"Error sending Slack message: {e}"

    @tool("slack_post_update", args_schema=PostUpdateInput)
    def slack_post_update(channel: str, title: str, content: str) -> str:
        """Post a formatted update with a heading to a Slack channel."""
        try:
            channel_id = _resolve_channel_id(client, channel, channel_cache)
            if not channel_id:
                return f"Error: channel #{channel.lstrip('#')} not found."

            blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": title}},
                {"type": "section", "text": {"type": "mrkdwn", "text": content}},
            ]
            client.chat_postMessage(
                channel=channel_id, text=f"{title}\n{content}", blocks=blocks
            )
            return f"Update '{title}' posted to #{channel.lstrip('#')}."
        except SlackApiError as e:
            return f"Error posting update: {e.response.get('error', e)}"
        except Exception as e:
            return f"Error posting update: {e}"

    @tool("slack_list_channels")
    def slack_list_channels() -> str:
        """List Slack channels the workspace has, with member counts."""
        try:
            result = client.conversations_list(
                types="public_channel,private_channel", limit=100
            )
            channels = result.get("channels", [])
            if not channels:
                return "No channels found."

            lines = []
            for ch in channels:
                marker = "private" if ch.get("is_private") else "public"
                lines.append(
                    f"#{ch['name']} ({marker}, {ch.get('num_members', '?')} members)"
                )
            return "Slack channels:\n" + "\n".join(lines)
        except SlackApiError as e:
            return f"Error listing channels: {e.response.get('error', e)}"
        except Exception as e:
            return f"Error listing channels: {e}"

    @tool("slack_read_channel", args_schema=ReadChannelInput)
    def slack_read_channel(channel: str, limit: int = 20) -> str:
        """
        Read recent messages from a Slack channel.

        Use this to catch up on a discussion or find what a team said about a topic.
        """
        try:
            channel_id = _resolve_channel_id(client, channel, channel_cache)
            if not channel_id:
                return f"Error: channel #{channel.lstrip('#')} not found."

            result = client.conversations_history(
                channel=channel_id, limit=min(limit, 100)
            )
            messages = result.get("messages", [])
            if not messages:
                return f"No recent messages in #{channel.lstrip('#')}."

            lines = []
            for msg in reversed(messages):
                author = resolve_user(msg.get("user", ""))
                text = (msg.get("text", "") or "").replace("\n", " ")
                reply_count = msg.get("reply_count", 0)
                suffix = f" [{reply_count} replies, thread_ts={msg['ts']}]" if reply_count else ""
                lines.append(f"{author}: {text}{suffix}")

            return f"Recent messages in #{channel.lstrip('#')}:\n" + "\n".join(lines)
        except SlackApiError as e:
            error = e.response.get("error", str(e))
            if error == "not_in_channel":
                return (
                    f"Error: the bot is not a member of #{channel.lstrip('#')}. "
                    "Invite it to the channel first."
                )
            return f"Error reading channel: {error}"
        except Exception as e:
            return f"Error reading channel: {e}"

    @tool("slack_read_thread", args_schema=ReadThreadInput)
    def slack_read_thread(channel: str, thread_ts: str) -> str:
        """
        Read a full Slack thread, given its parent message timestamp.

        Get thread_ts from slack_read_channel or slack_search first.
        """
        try:
            channel_id = _resolve_channel_id(client, channel, channel_cache)
            if not channel_id:
                return f"Error: channel #{channel.lstrip('#')} not found."

            result = client.conversations_replies(channel=channel_id, ts=thread_ts)
            messages = result.get("messages", [])
            if not messages:
                return "Thread not found or empty."

            lines = [
                f"{resolve_user(m.get('user', ''))}: {(m.get('text', '') or '').replace(chr(10), ' ')}"
                for m in messages
            ]
            return f"Thread in #{channel.lstrip('#')}:\n" + "\n".join(lines)
        except SlackApiError as e:
            return f"Error reading thread: {e.response.get('error', e)}"
        except Exception as e:
            return f"Error reading thread: {e}"

    tools: list[BaseTool] = [
        slack_send_message,
        slack_post_update,
        slack_list_channels,
        slack_read_channel,
        slack_read_thread,
    ]

    # search.messages requires a user token. Only expose the tool when we have
    # one -- an agent offered a tool that always fails wastes turns on it.
    if user_token:
        search_client = WebClient(token=user_token)

        @tool("slack_search", args_schema=SearchInput)
        def slack_search(query: str, count: int = 10) -> str:
            """
            Search Slack message history across the workspace.

            Use this to find discussions about a ticket key, a PR, or any topic.
            """
            try:
                result = search_client.search_messages(
                    query=query, count=min(count, 20)
                )
                matches = result.get("messages", {}).get("matches", [])
                if not matches:
                    return f"No Slack messages found for '{query}'."

                lines = []
                for match in matches:
                    channel = match.get("channel", {}).get("name", "unknown")
                    author = match.get("username") or resolve_user(match.get("user", ""))
                    text = (match.get("text", "") or "").replace("\n", " ")[:300]
                    lines.append(f"#{channel} — {author}: {text}")

                return f"Slack results for '{query}':\n" + "\n".join(lines)
            except SlackApiError as e:
                error = e.response.get("error", str(e))
                if error == "missing_scope":
                    return (
                        "Error: the Slack user token is missing the search:read scope. "
                        "Reinstall the Slack app with that scope."
                    )
                return f"Error searching Slack: {error}"
            except Exception as e:
                return f"Error searching Slack: {e}"

        tools.append(slack_search)
    else:
        logger.info(
            "Slack connected without a user token; search tool disabled. "
            "Add a user token (xoxp-) to enable message search."
        )

    return tools
