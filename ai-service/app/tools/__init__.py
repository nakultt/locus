import json
import structlog
from typing import Dict, Any, List
from langchain_core.tools import BaseTool

logger = structlog.get_logger()

# Import all tool factory functions
from .jira import get_jira_tools
from .gmail import get_gmail_tools
from .calendar import get_calendar_tools
from .slack import get_slack_tools
from .notion import get_notion_tools
from .github import get_github_tools
from .linear import get_linear_tools
from .bugasura import get_bugasura_tools
from .google_docs import get_docs_tools as get_google_docs_tools
from .google_sheets import get_sheets_tools as get_google_sheets_tools
from .google_slides import get_slides_tools as get_google_slides_tools
from .google_drive import get_drive_tools as get_google_drive_tools
from .google_forms import get_forms_tools as get_google_forms_tools
from .google_meet import get_meet_tools as get_google_meet_tools

def get_all_tools(configs: Dict[str, Any]) -> List[BaseTool]:
    """
    Initialize and return all available tools based on the provided integration configs.
    """
    tools = []
    
    for provider, config_data in configs.items():
        try:
            # If config_data is a JSON string, parse it
            if isinstance(config_data, str):
                config = json.loads(config_data)
            else:
                config = config_data
                
            if provider == "jira":
                tools.extend(get_jira_tools(
                    api_token=config.get("api_token", config.get("api_key", "")),
                    email=config.get("email", ""),
                    url=config.get("url", "")
                ))
            elif provider == "github":
                tools.extend(get_github_tools(
                    token=config.get("access_token", config.get("api_key", ""))
                ))
            elif provider == "linear":
                tools.extend(get_linear_tools(
                    api_key=config.get("api_key", config.get("access_token", ""))
                ))
            elif provider == "notion":
                tools.extend(get_notion_tools(
                    integration_token=config.get("api_key", "")
                ))
            elif provider == "slack":
                tools.extend(get_slack_tools(
                    bot_token=config.get("bot_token", config.get("api_key", ""))
                ))
            elif provider == "bugasura":
                tools.extend(get_bugasura_tools(
                    api_key=config.get("api_key", "")
                ))
            # Google Workspace tools
            elif provider in ["gmail", "calendar", "google_docs", "google_sheets", "google_slides", "google_drive", "google_forms", "google_meet"]:
                # Note: Assuming all google tools take the same OAuth token dictionary
                if provider == "gmail":
                    tools.extend(get_gmail_tools(credentials=config))
                elif provider == "calendar":
                    tools.extend(get_calendar_tools(credentials=config))
                elif provider == "google_docs":
                    tools.extend(get_google_docs_tools(credentials=config))
                elif provider == "google_sheets":
                    tools.extend(get_google_sheets_tools(credentials=config))
                elif provider == "google_slides":
                    tools.extend(get_google_slides_tools(credentials=config))
                elif provider == "google_drive":
                    tools.extend(get_google_drive_tools(credentials=config))
                elif provider == "google_forms":
                    tools.extend(get_google_forms_tools(credentials=config))
                elif provider == "google_meet":
                    tools.extend(get_google_meet_tools(credentials=config))
                    
        except Exception as e:
            logger.error("failed_to_initialize_tools", provider=provider, error=str(e))
            
    # Always return at least an empty list so LangGraph doesn't crash if no tools
    return tools
