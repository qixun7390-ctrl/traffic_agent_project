from typing import TypedDict, Any, Annotated, Literal
from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage
from dataclasses import dataclass
import operator
from app.schemas.agent import AgentOperation

@dataclass(frozen=True)
class AgentRuntimeContext:
    """
    每次运行固定的上下文
    """
    user_id: str

class TrafficAgentState(TypedDict,total=False):
    """LangGraph节点之间传递并由 checkpointer保存的状态"""
    #用户对话和审计日志（不同节点返回事件会被追加）
    messages: Annotated[list[AnyMessage],add_messages]
    audit_events: Annotated[list[dict[str, Any]],operator.add]

    user_id: str

    #用户上传JSON的路径
    attachments: dict[str, str]

    #控制流
    operation: AgentOperation | None
    confirmation_status: Literal["pending","approved","rejected"] | None

    #业务数据
    request_params: dict[str, Any]
    pending_action: dict[str, Any] | None
    last_result: dict[str, Any] | None
    missing_attachments: list[str]

    #异常
    error: dict[str, Any] | None