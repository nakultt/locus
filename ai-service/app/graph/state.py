from typing import TypedDict, Annotated, Sequence, Dict, Any, List
from langchain_core.messages import BaseMessage
from operator import add

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add]
    integration_configs: Dict[str, Any]
    actions_taken: List[Dict[str, Any]]
    current_task: str | None
