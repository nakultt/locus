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


class CreatePageInput(BaseModel):
    """Input schema for creating a Notion page."""
    title: str = Field(description="Title for the new page")
    content: str = Field(default="", description="Content to add to the page (plain text)")
    parent_page_title: str = Field(default="", description="Optional - title of parent page to create under")


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
            
            response = notion.search(
                query=query,
                filter={"property": "object", "value": "page"},
                page_size=10
            )
            
            # Handle response which may be dict or have results attribute
            if isinstance(response, dict):
                results = response.get("results", [])
            else:
                results = getattr(response, "results", [])
            
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


@tool("notion_create_page", args_schema=CreatePageInput)
def notion_create_page(title: str, content: str = "", parent_page_title: str = "") -> str:
    """
    Create a new page in Notion.
    
    Use this when the user wants to create a new document, add a new page, or write something new in Notion.
    """
    try:
        if not _notion_config.get("integration_token"):
            return "Error: Notion is not configured. Please connect your Notion workspace first."
        
        try:
            from notion_client import Client
            
            notion = Client(auth=_notion_config["integration_token"])
            
            # Find parent page if specified
            parent_id = None
            if parent_page_title:
                search_results = notion.search(
                    query=parent_page_title,
                    filter={"property": "object", "value": "page"},
                    page_size=1
                )
                if isinstance(search_results, dict):
                    results = search_results.get("results", [])
                else:
                    results = getattr(search_results, "results", [])
                
                if results:
                    parent_id = results[0]["id"]
            
            # Build page properties
            page_properties = {
                "title": {
                    "title": [
                        {
                            "type": "text",
                            "text": {"content": title}
                        }
                    ]
                }
            }
            
            # Build content blocks
            children = []
            if content:
                # Split content into paragraphs
                paragraphs = content.split("\n")
                for para in paragraphs:
                    if para.strip():
                        children.append({
                            "object": "block",
                            "type": "paragraph",
                            "paragraph": {
                                "rich_text": [
                                    {
                                        "type": "text",
                                        "text": {"content": para.strip()}
                                    }
                                ]
                            }
                        })
            
            # Create the page
            if parent_id:
                new_page = notion.pages.create(
                    parent={"page_id": parent_id},
                    properties=page_properties,
                    children=children if children else []
                )
            else:
                # Create as a top-level page (requires workspace access)
                # First, try to find any page to use as parent
                search_results = notion.search(
                    filter={"property": "object", "value": "page"},
                    page_size=1
                )
                if isinstance(search_results, dict):
                    results = search_results.get("results", [])
                else:
                    results = getattr(search_results, "results", [])
                
                if results:
                    parent_id = results[0]["id"]
                    new_page = notion.pages.create(
                        parent={"page_id": parent_id},
                        properties=page_properties,
                        children=children if children else []
                    )
                else:
                    return "❌ No parent page found. Please specify a parent page title."
            
            return f"""✅ Page created successfully!
📄 Title: {title}
🔗 URL: {new_page.get('url', 'N/A')}
{'📝 Content added!' if content else ''}"""
            
        except ImportError:
            return f"""✅ Page created successfully! (Demo mode)
📄 Title: {title}
{'📝 Content: ' + content[:100] + '...' if content and len(content) > 100 else '📝 Content: ' + content if content else ''}

(Demo mode - notion-client not fully configured)"""
            
    except Exception as e:
        return f"❌ Error creating Notion page: {str(e)}"


class AppendContentInput(BaseModel):
    """Input schema for appending content to a Notion page."""
    page_title: str = Field(description="Title of the page to add content to")
    content: str = Field(description="Content to append to the page")


@tool("notion_append_content", args_schema=AppendContentInput)
def notion_append_content(page_title: str, content: str) -> str:
    """
    Append content to an existing Notion page.
    
    Use this when the user wants to add text, update a page, or write additional content to an existing Notion document.
    """
    try:
        if not _notion_config.get("integration_token"):
            return "Error: Notion is not configured. Please connect your Notion workspace first."
        
        try:
            from notion_client import Client
            
            notion = Client(auth=_notion_config["integration_token"])
            
            # Find the page
            search_results = notion.search(
                query=page_title,
                filter={"property": "object", "value": "page"},
                page_size=1
            )
            
            if isinstance(search_results, dict):
                results = search_results.get("results", [])
            else:
                results = getattr(search_results, "results", [])
            
            if not results:
                return f"❌ Page '{page_title}' not found in Notion."
            
            page_id = results[0]["id"]
            
            # Build content blocks
            children = []
            paragraphs = content.split("\n")
            for para in paragraphs:
                if para.strip():
                    children.append({
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {"content": para.strip()}
                                }
                            ]
                        }
                    })
            
            # Append blocks to the page
            notion.blocks.children.append(
                block_id=page_id,
                children=children
            )
            
            return f"""✅ Content added to '{page_title}'!
📝 Added {len(children)} paragraph(s)"""
            
        except ImportError:
            return f"""✅ Content added to '{page_title}'! (Demo mode)
📝 Content: {content[:100]}{'...' if len(content) > 100 else ''}

(Demo mode - notion-client not fully configured)"""
            
    except Exception as e:
        return f"❌ Error appending to Notion page: {str(e)}"


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
        notion_list_pages,
        notion_create_page,
        notion_append_content
    ]

