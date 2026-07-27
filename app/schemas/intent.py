"""
三类意图与二级动作识别
"""
from enum import Enum
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

class AgentIntent(str, Enum):
    """Traffic Agent的三个意图"""
    SIMULATION_TRANSACTION = "simulation_transaction"
    CHAT = "chat"
    AGENT_SKILL = "agent_skill"


class IntentRecognizeRequest(BaseModel):
    """前端提交的自然语言请求"""
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1,max_length=2000)


class SimulationOperation(str,Enum):
    CREATE = "create"

class IntentDecision(BaseModel):
    """意图识别服务的标准输出"""
    model_config = ConfigDict(extra="forbid")
    intent: AgentIntent
    simulation_operation: Optional[SimulationOperation] = None