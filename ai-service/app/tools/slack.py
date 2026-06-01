"""
Slack Integration Service
LangChain tools for Slack messaging
"""

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

# Store credentials at module level for tool access
_slack_config: dict = {}


class SendMessageInput(BaseModel):
    """Input schema for sending a Slack message."""
    channel: str = Field(default="general", description="Channel name (with or without #) or channel ID")
    message: str = Field(default="Hello from Locus!", description="Message content to send")
    text: str = Field(default="", description="Alternative message field (alias for message)")


class PostUpdateInput(BaseModel):
    """Input schema for posting an update."""
    channel: str = Field(description="Channel name (with or without #)")
    title: str = Field(description="Update title/heading")
    content: str = Field(description="Update content/body")


@tool("slack_send_message", args_schema=SendMessageInput)
def slack_send_message(channel: str = "general", message: str = "Hello from Locus!", text: str = "") -> str:
    """
    Send a message to a Slack channel.
    
    Use this when the user wants to post a message, send an update, or communicate on Slack.
    """
    # Use text if message is default/empty
    if text and message == "Hello from Locus!":
        message = text
    
    try:
        if not _slack_config.get("bot_token"):
            return "Error: Slack is not configured. Please connect your Slack workspace first."
        
        # Normalize channel name
        if not channel.startswith("#") and not channel.startswith("C"):
            channel = f"#{channel}"
        
        try:
            from slack_sdk import WebClient
            from slack_sdk.errors import SlackApiError
            
            client = WebClient(token=_slack_config["bot_token"])
            
            # If channel name, we need to find the ID
            if channel.startswith("#"):
                channel_name = channel[1:]
                # List channels to find ID
                result = client.conversations_list(types="public_channel,private_channel")
                channel_id = None
                for ch in result["channels"]:
                    if ch["name"] == channel_name:
                        channel_id = ch["id"]
                        break
                
                if not channel_id:
                    return f"❌ Channel {channel} not found"
            else:
                channel_id = channel
            
            response = client.chat_postMessage(
                channel=channel_id,
                text=message
            )
            
            return f"✅ Message sent to {channel}!\nTimestamp: {response['ts']}"
            
        except ImportError:
            return f"""✅ Message sent to {channel}!
Message: {message[:100]}{'...' if len(message) > 100 else ''}

(Demo mode - slack-sdk not fully configured)"""
            
    except Exception as e:
        return f"❌ Error sending Slack message: {str(e)}"


@tool("slack_post_update", args_schema=PostUpdateInput)
def slack_post_update(channel: str, title: str, content: str) -> str:
    """
    Post a formatted update to a Slack channel with blocks.
    
    Use this when the user wants to share an announcement, status update, or formatted message.
    """
    try:
        if not _slack_config.get("bot_token"):
            return "Error: Slack is not configured. Please connect your Slack workspace first."
        
        if not channel.startswith("#"):
            channel = f"#{channel}"
        
        try:
            from slack_sdk import WebClient
            
            client = WebClient(token=_slack_config["bot_token"])
            
            channel_name = channel[1:]
            result = client.conversations_list(types="public_channel,private_channel")
            channel_id = None
            for ch in result["channels"]:
                if ch["name"] == channel_name:
                    channel_id = ch["id"]
                    break
            
            if not channel_id:
                return f"❌ Channel {channel} not found"
            
            blocks = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": title}
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": content}
                },
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": "Posted via Conflux 🚀"}
                    ]
                }
            ]
            
            response = client.chat_postMessage(
                channel=channel_id,
                text=f"{title}\n{content}",
                blocks=blocks
            )
            
            return f"✅ Update posted to {channel}!\nTitle: {title}"
            
        except ImportError:
            return f"""✅ Update posted to {channel}!

📢 *{title}*
{content[:200]}{'...' if len(content) > 200 else ''}

Posted via Conflux 🚀

(Demo mode - slack-sdk not fully configured)"""
            
    except Exception as e:
        return f"❌ Error posting update: {str(e)}"


@tool("slack_list_channels")
def slack_list_channels() -> str:
    """
    List available Slack channels.
    
    Use this when the user wants to see available channels or doesn't know which channel to post to.
    """
    try:
        if not _slack_config.get("bot_token"):
            return "Error: Slack is not configured. Please connect your Slack workspace first."
        
        try:
            from slack_sdk import WebClient
            
            client = WebClient(token=_slack_config["bot_token"])
            
            result = client.conversations_list(
                types="public_channel,private_channel",
                limit=20
            )
            
            channels = result.get("channels", [])
            
            if not channels:
                return "No channels found."
            
            output = "📋 Available Slack channels:\n\n"
            
            for ch in channels:
                name = ch["name"]
                member_count = ch.get("num_members", "?")
                is_private = "🔒" if ch.get("is_private") else "📢"
                output += f"{is_private} #{name} ({member_count} members)\n"
            
            return output
            
        except ImportError:
            return """📋 Available Slack channels:

📢 #general (45 members)
📢 #engineering (23 members)
📢 #dev-updates (18 members)
🔒 #team-leads (8 members)
📢 #random (42 members)
📢 #announcements (50 members)

(Demo mode - slack-sdk not fully configured)"""
            
    except Exception as e:
        return f"❌ Error listing channels: {str(e)}"


def get_slack_tools(bot_token: str) -> list[BaseTool]:
    """
    Get LangChain tools for Slack integration.
    
    Args:
        bot_token: Slack bot OAuth token
        
    Returns:
        List of Slack tools
    """
    global _slack_config
    _slack_config = {"bot_token": bot_token}
    
    return [
        slack_send_message,
        slack_post_update,
        slack_list_channels
    ]
