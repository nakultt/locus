from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field, field_validator

class ChatRequest(BaseModel):
    user_id: Union[str, int]
    message: str
    integration_configs: Dict[str, Any] = Field(default_factory=dict)
    conversation_id: Optional[Union[str, int]] = None
    smart_mode: Optional[bool] = False
    
    @field_validator('user_id', 'conversation_id')
    @classmethod
    def convert_to_str(cls, v):
        if v is not None:
            return str(v)
        return v
    
class ActionTaken(BaseModel):
    tool_name: str
    input: Dict[str, Any]
    output: Any

class ChatResponse(BaseModel):
    response: str
    actions_taken: List[ActionTaken] = Field(default_factory=list)
