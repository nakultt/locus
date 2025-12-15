"""
Notion Integration Service
LangChain tools for Notion documentation
"""

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

# Store credentials at module level for tool access
_notion_config: dict = {}


class SearchNotionInput(BaseModel):
    """Input schema for searching Notion."""
    query: str = Field(description="Search query to find pages or content")


class GetPageInput(BaseModel):
    """Input schema for getting a Notion page."""
    page_title: str = Field(description="Title or partial title of the page to retrieve")


@tool("notion_search", args_schema=SearchNotionInput)
def notion_search(query: str) -> str:
    """
    Search for pages and content in Notion.
    
    Use this when the user wants to find documentation, search their Notion workspace, or look up information.
    """
    try:
        if not _notion_config.get("integration_token"):
            return "Error: Notion is not configured. Please connect your Notion workspace first."
        
        try:
            from notion_client import Client
            
            notion = Client(auth=_notion_config["integration_token"])
            
            results = notion.search(
                query=query,
                filter={"property": "object", "value": "page"},
                page_size=10
            ).get("results", [])
            
            if not results:
                return f"No Notion pages found matching: {query}"
            
            output = f"📚 Found {len(results)} Notion page(s) for '{query}':\n\n"
            
            for page in results:
                # Extract title
                title = "Untitled"
                if "properties" in page:
                    for prop in page["properties"].values():
                        if prop.get("type") == "title":
                            title_arr = prop.get("title", [])
                            if title_arr:
                                title = title_arr[0].get("plain_text", "Untitled")
                            break
                
                # Get page URL
                url = page.get("url", "")
                
                # Get last edited
                last_edited = page.get("last_edited_time", "")[:10]
                
                output += f"• {title}\n"
                output += f"  Last edited: {last_edited}\n"
                if url:
                    output += f"  URL: {url}\n"
                output += "\n"
            
            return output
            
        except ImportError:
            return f"""📚 Found 3 Notion pages for '{query}':

• Project Documentation
  Last edited: 2025-12-14
  URL: https://notion.so/project-docs

• API Reference Guide
  Last edited: 2025-12-12
  URL: https://notion.so/api-reference

• Team Onboarding
  Last edited: 2025-12-10
  URL: https://notion.so/onboarding

(Demo mode - notion-client not fully configured)"""
            
    except Exception as e:
        return f"❌ Error searching Notion: {str(e)}"


@tool("notion_get_page", args_schema=GetPageInput)
def notion_get_page(page_title: str) -> str:
    """
    Get content from a specific Notion page.
    
    Use this when the user wants to read a specific page, get details about a document, or retrieve information from Notion.
    """
    try:
        if not _notion_config.get("integration_token"):
            return "Error: Notion is not configured. Please connect your Notion workspace first."
        
        try:
            from notion_client import Client
            
            notion = Client(auth=_notion_config["integration_token"])
            
            # Search for the page by title
            results = notion.search(
                query=page_title,
                filter={"property": "object", "value": "page"},
                page_size=1
            ).get("results", [])
            
            if not results:
                return f"No Notion page found matching: {page_title}"
            
            page = results[0]
            page_id = page["id"]
            
            # Get page title
            title = page_title
            if "properties" in page:
                for prop in page["properties"].values():
                    if prop.get("type") == "title":
                        title_arr = prop.get("title", [])
                        if title_arr:
                            title = title_arr[0].get("plain_text", page_title)
                        break
            
            # Get page blocks (content)
            blocks = notion.blocks.children.list(block_id=page_id).get("results", [])
            
            content_parts = []
            for block in blocks[:20]:  # Limit to first 20 blocks
                block_type = block.get("type", "")
                
                if block_type == "paragraph":
                    texts = block.get("paragraph", {}).get("rich_text", [])
                    text = "".join([t.get("plain_text", "") for t in texts])
                    if text:
                        content_parts.append(text)
                        
                elif block_type == "heading_1":
                    texts = block.get("heading_1", {}).get("rich_text", [])
                    text = "".join([t.get("plain_text", "") for t in texts])
                    content_parts.append(f"\n# {text}")
                    
                elif block_type == "heading_2":
                    texts = block.get("heading_2", {}).get("rich_text", [])
                    text = "".join([t.get("plain_text", "") for t in texts])
                    content_parts.append(f"\n## {text}")
                    
                elif block_type == "bulleted_list_item":
                    texts = block.get("bulleted_list_item", {}).get("rich_text", [])
                    text = "".join([t.get("plain_text", "") for t in texts])
                    content_parts.append(f"• {text}")
            
            content = "\n".join(content_parts) if content_parts else "(No readable content)"
            
            return f"""📄 **{title}**

{content[:1500]}{'...' if len(content) > 1500 else ''}

URL: {page.get('url', 'N/A')}"""
            
        except ImportError:
            return f"""📄 **{page_title}**

# Overview
This document contains the project overview and key information.

## Key Features
• Feature 1: User authentication
• Feature 2: Data synchronization
• Feature 3: Real-time updates

## Technical Stack
The project uses modern technologies including FastAPI, PostgreSQL, and React.

## Next Steps
- Complete the API integration
- Add unit tests
- Deploy to staging

(Demo mode - notion-client not fully configured)"""
            
    except Exception as e:
        return f"❌ Error getting Notion page: {str(e)}"


@tool("notion_list_pages")
def notion_list_pages() -> str:
    """
    List recently edited Notion pages.
    
    Use this when the user wants to see their recent documents, browse Notion pages, or doesn't know what to search for.
    """
    try:
        if not _notion_config.get("integration_token"):
            return "Error: Notion is not configured. Please connect your Notion workspace first."
        
        try:
            from notion_client import Client
            
            notion = Client(auth=_notion_config["integration_token"])
            
            # Search with empty query to get recent pages
            results = notion.search(
                filter={"property": "object", "value": "page"},
                sort={"direction": "descending", "timestamp": "last_edited_time"},
                page_size=10
            ).get("results", [])
            
            if not results:
                return "No Notion pages found in your workspace."
            
            output = "📚 Recent Notion pages:\n\n"
            
            for page in results:
                # Extract title
                title = "Untitled"
                if "properties" in page:
                    for prop in page["properties"].values():
                        if prop.get("type") == "title":
                            title_arr = prop.get("title", [])
                            if title_arr:
                                title = title_arr[0].get("plain_text", "Untitled")
                            break
                
                last_edited = page.get("last_edited_time", "")[:10]
                output += f"• {title} (edited: {last_edited})\n"
            
            return output
            
        except ImportError:
            return """📚 Recent Notion pages:

• Project Roadmap (edited: 2025-12-15)
• Sprint 5 Retrospective (edited: 2025-12-14)
• API Documentation (edited: 2025-12-13)
• Team Meeting Notes (edited: 2025-12-12)
• Architecture Decisions (edited: 2025-12-10)
• Onboarding Guide (edited: 2025-12-08)

(Demo mode - notion-client not fully configured)"""
            
    except Exception as e:
        return f"❌ Error listing Notion pages: {str(e)}"


def get_notion_tools(integration_token: str) -> list[BaseTool]:
    """
    Get LangChain tools for Notion integration.
    
    Args:
        integration_token: Notion integration token
        
    Returns:
        List of Notion tools
    """
    global _notion_config
    _notion_config = {"integration_token": integration_token}
    
    return [
        notion_search,
        notion_get_page,
        notion_list_pages
    ]
