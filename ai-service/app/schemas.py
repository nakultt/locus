from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    user_id: str
    message: str
    integration_configs: Dict[str, Any] = Field(default_factory=dict)
    conversation_id: Optional[str] = None
    smart_mode: Optional[bool] = False
    
class ActionTaken(BaseModel):
    tool_name: str
    input: Dict[str, Any]
    output: Any

class ChatResponse(BaseModel):
    response: str
    actions_taken: List[ActionTaken] = Field(default_factory=list)
