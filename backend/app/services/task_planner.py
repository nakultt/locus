"""
Task Planner Service
Parses user messages to extract individual tasks and plan execution order.
Uses LLM to intelligently identify and structure tasks from natural language.
"""

from dataclasses import dataclass, field
from typing import Optional, Any
from enum import Enum
import json
import os

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate


class TaskStatus(str, Enum):
    """Status of a task in the execution plan."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PlannedTask:
    """Represents a single task extracted from user request."""
    id: str
    service: str  # slack, jira, calendar, gmail, notion, etc.
    action: str   # send_message, create_issue, create_event, etc.
    description: str  # Human-readable description
    tool_name: str  # Actual tool function name
    parameters: dict = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    depends_on: list[str] = field(default_factory=list)  # Task IDs this depends on
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "task_id": self.id,
            "service": self.service,
            "action": self.action,
            "description": self.description,
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "depends_on": self.depends_on,
        }


@dataclass  
class TaskPlan:
    """Complete execution plan for a user request."""
    tasks: list[PlannedTask] = field(default_factory=list)
    total: int = 0
    completed: int = 0
    failed: int = 0
    current_task_id: Optional[str] = None
    task_results: dict[str, Any] = field(default_factory=dict)  # Store results for chaining
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "tasks": [t.to_dict() for t in self.tasks],
            "total": self.total,
            "completed": self.completed,
            "failed": self.failed,
            "current_task_id": self.current_task_id,
        }
    
    def get_pending_tasks(self) -> list[PlannedTask]:
        """Get tasks that are still pending."""
        return [t for t in self.tasks if t.status == TaskStatus.PENDING]
    
    def get_next_task(self) -> Optional[PlannedTask]:
        """Get the next task to execute, respecting dependencies."""
        for task in self.tasks:
            if task.status != TaskStatus.PENDING:
                continue
            
            # Check if all dependencies are satisfied
            deps_satisfied = all(
                any(t.id == dep_id and t.status == TaskStatus.COMPLETED for t in self.tasks)
                for dep_id in task.depends_on
            )
            
            if deps_satisfied:
                return task
        
        return None
    
    def update_task_status(
        self, 
        task_id: str, 
        status: TaskStatus, 
        result: Optional[str] = None,
        error: Optional[str] = None
    ):
        """Update a task's status and optionally its result/error."""
        for task in self.tasks:
            if task.id == task_id:
                task.status = status
                if result:
                    task.result = result
                    self.task_results[task_id] = result
                if error:
                    task.error = error
                
                if status == TaskStatus.COMPLETED:
                    self.completed += 1
                elif status == TaskStatus.FAILED:
                    self.failed += 1
                elif status == TaskStatus.IN_PROGRESS:
                    self.current_task_id = task_id
                
                break


# Service to tool mapping
SERVICE_TOOL_MAP = {
    "slack": {
        "send_message": "slack_send_message",
        "post_update": "slack_post_update",
        "list_channels": "slack_list_channels",
    },
    "jira": {
        "create_issue": "jira_create_issue",
        "create_bug": "jira_create_issue",
        "search": "jira_search_issues",
        "add_comment": "jira_add_comment",
    },
    "calendar": {
        "create_event": "calendar_create_event",
        "create_meeting": "calendar_create_event",
        "update_event": "calendar_update_event",
        "delete_event": "calendar_delete_event",
    },
    "gmail": {
        "send_email": "gmail_send_email",
        "read_emails": "gmail_read_latest_emails",
    },
    "notion": {
        "search": "notion_search",
        "create_page": "notion_create_page",
        "append_content": "notion_append_content",
        "get_page": "notion_get_page",
    },
    "docs": {
        "create_document": "docs_create_document",
        "append_content": "docs_append_content",
    },
    "sheets": {
        "create_spreadsheet": "sheets_create_spreadsheet",
        "add_rows": "sheets_add_rows",
    },
    "bugasura": {
        "create_issue": "bugasura_create_issue",
        "list_issues": "bugasura_list_issues",
    },
    "github": {
        "list_repos": "github_list_repos",
        "get_repo": "github_get_repo",
        "create_repo": "github_create_repo",
        "list_issues": "github_list_issues",
        "create_issue": "github_create_issue",
        "update_issue": "github_update_issue",
        "add_comment": "github_add_issue_comment",
        "list_prs": "github_list_prs",
        "create_pr": "github_create_pr",
        "merge_pr": "github_merge_pr",
    },
    "linear": {
        "list_teams": "linear_list_teams",
        "list_issues": "linear_list_issues",
        "get_issue": "linear_get_issue",
        "create_issue": "linear_create_issue",
        "update_issue": "linear_update_issue",
        "add_comment": "linear_add_comment",
        "list_states": "linear_list_states",
    },
}


TASK_PLANNING_PROMPT = """You are a task planning assistant. Analyze the user's message and extract ALL individual tasks they want to perform.

User message: {message}

Available services and their actions:
- slack: send_message, post_update, list_channels
- jira: create_issue, create_bug, search, add_comment
- calendar: create_event, create_meeting, update_event
- gmail: send_email, read_emails
- notion: search, create_page, append_content, get_page
- docs: create_document, append_content
- sheets: create_spreadsheet, add_rows
- bugasura: create_issue, list_issues
- github: list_repos, get_repo, create_repo, list_issues, create_issue, update_issue, add_comment, list_prs, create_pr, merge_pr
- linear: list_teams, list_issues, get_issue, create_issue, update_issue, add_comment, list_states

For EACH task in the message, extract:
1. service: which service to use
2. action: what action to perform
3. description: human-readable description of the task
4. parameters: any parameters mentioned (channel name, email address, time, etc.)
5. depends_on: list of task IDs this task depends on (e.g., email about meeting depends on calendar task)

IMPORTANT RULES:
- Extract ALL tasks, not just the first one
- If an email needs to mention a meeting link, that email task depends on the calendar task
- If a Notion page should summarize actions, it depends on all other tasks
- Order tasks so dependencies come first

Return ONLY valid JSON array. Example format:
[
  {{
    "id": "task_1",
    "service": "calendar",
    "action": "create_meeting",
    "description": "Create a meeting tomorrow at 11pm for 1 hour",
    "parameters": {{"title": "Meeting", "start_datetime": "tomorrow 11pm", "duration": "1 hour"}},
    "depends_on": []
  }},
  {{
    "id": "task_2",
    "service": "gmail",
    "action": "send_email",
    "description": "Send email about the meeting",
    "parameters": {{"to": "user@example.com", "subject": "Meeting Details"}},
    "depends_on": ["task_1"]
  }}
]

Return ONLY the JSON array, no other text."""


def parse_tasks_from_message(message: str, available_services: list[str]) -> TaskPlan:
    """
    Use LLM to parse user message and extract individual tasks.
    
    Args:
        message: User's natural language request
        available_services: List of services the user has connected
        
    Returns:
        TaskPlan with extracted tasks
    """
    google_api_key = os.getenv("GOOGLE_API_KEY")
    
    if not google_api_key:
        # Fallback: simple keyword-based extraction
        return _fallback_parse_tasks(message, available_services)
    
    try:
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key=google_api_key,
            temperature=0,
        )
        
        prompt = ChatPromptTemplate.from_template(TASK_PLANNING_PROMPT)
        chain = prompt | llm
        
        result = chain.invoke({"message": message})
        
        # Parse JSON response
        content = result.content
        if isinstance(content, str):
            # Clean up response - remove markdown code blocks if present
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1]  # Remove first line
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
            
            tasks_data = json.loads(content)
        else:
            tasks_data = content
        
        # Convert to PlannedTask objects
        plan = TaskPlan()
        for task_data in tasks_data:
            service = task_data.get("service", "").lower()
            action = task_data.get("action", "").lower()
            
            # Skip if service not available
            if service not in available_services:
                continue
            
            # Get actual tool name
            tool_name = SERVICE_TOOL_MAP.get(service, {}).get(action, f"{service}_{action}")
            
            task = PlannedTask(
                id=task_data.get("id", f"task_{len(plan.tasks) + 1}"),
                service=service,
                action=action,
                description=task_data.get("description", ""),
                tool_name=tool_name,
                parameters=task_data.get("parameters", {}),
                depends_on=task_data.get("depends_on", []),
            )
            plan.tasks.append(task)
        
        plan.total = len(plan.tasks)
        return plan
        
    except Exception as e:
        print(f"Error parsing tasks with LLM: {e}")
        return _fallback_parse_tasks(message, available_services)


def _fallback_parse_tasks(message: str, available_services: list[str]) -> TaskPlan:
    """
    Fallback keyword-based task extraction when LLM is not available.
    """
    plan = TaskPlan()
    message_lower = message.lower()
    task_counter = 0
    
    # Slack detection
    if "slack" in available_services and any(k in message_lower for k in ["slack", "post", "channel"]):
        task_counter += 1
        # Extract channel name
        channel = "general"
        if "#" in message:
            import re
            match = re.search(r"#(\w+)", message)
            if match:
                channel = match.group(1)
        
        plan.tasks.append(PlannedTask(
            id=f"task_{task_counter}",
            service="slack",
            action="send_message",
            description=f"Send message to #{channel}",
            tool_name="slack_send_message",
            parameters={"channel": channel},
        ))
    
    # Calendar detection
    if "calendar" in available_services and any(k in message_lower for k in ["meeting", "calendar", "schedule", "event"]):
        task_counter += 1
        plan.tasks.append(PlannedTask(
            id=f"task_{task_counter}",
            service="calendar",
            action="create_event",
            description="Create calendar event",
            tool_name="calendar_create_event",
            parameters={},
        ))
    
    # Gmail detection
    if "gmail" in available_services and any(k in message_lower for k in ["email", "mail", "send mail"]):
        task_counter += 1
        # Extract email address
        import re
        email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", message)
        to_email = email_match.group(0) if email_match else ""
        
        # Check if this depends on calendar task
        depends_on = []
        if any(t.service == "calendar" for t in plan.tasks):
            depends_on = [t.id for t in plan.tasks if t.service == "calendar"]
        
        plan.tasks.append(PlannedTask(
            id=f"task_{task_counter}",
            service="gmail",
            action="send_email",
            description=f"Send email to {to_email}",
            tool_name="gmail_send_email",
            parameters={"to": to_email},
            depends_on=depends_on,
        ))
    
    # Jira detection
    if "jira" in available_services and any(k in message_lower for k in ["jira", "ticket", "issue", "bug"]):
        task_counter += 1
        # Extract project key if mentioned
        import re
        project_match = re.search(r"project\s+(\w+)", message_lower)
        project_key = project_match.group(1).upper() if project_match else "PROJ"
        
        plan.tasks.append(PlannedTask(
            id=f"task_{task_counter}",
            service="jira",
            action="create_issue",
            description=f"Create Jira issue in {project_key}",
            tool_name="jira_create_issue",
            parameters={"project_key": project_key},
        ))
    
    # Notion detection
    if "notion" in available_services and any(k in message_lower for k in ["notion", "summarize", "summary", "document"]):
        task_counter += 1
        # Notion summary depends on all other tasks
        depends_on = [t.id for t in plan.tasks]
        
        plan.tasks.append(PlannedTask(
            id=f"task_{task_counter}",
            service="notion",
            action="append_content",
            description="Summarize actions in Notion",
            tool_name="notion_append_content",
            parameters={},
            depends_on=depends_on,
        ))
    
    plan.total = len(plan.tasks)
    return plan
