from app.agent.graph import build_traffic_agent_graph
from app.services.llm_service import LLMService
from app.tools.simulation_tools import (
    get_completed_order_count,
    get_simulation_duration,
    get_created_order_count,
)
from langgraph.types import Command
from langchain_core.messages import HumanMessage
from typing import Any
QUERY_TOOLS = [
    get_simulation_duration,
    get_created_order_count,
    get_completed_order_count,
]

class TrafficReActAgent:
    """对外调用入口"""
    def __init__(self):
        llm = LLMService()
        query_model_with_tools = llm.bind_tools(
            QUERY_TOOLS,
        )
        self.graph = build_traffic_agent_graph(
            query_model_with_tools=query_model_with_tools,
            query_tools=QUERY_TOOLS
        )

    async def ainvoke(
        self,
        message: str,
        thread_id: str,
        attachments: dict[str,str] | None = None
    ) -> dict[str, Any]:
        state = {
            "messages": [
                HumanMessage(content=message)
            ],
            "attachments": attachments or {},
            "audit_events": [],
        }
        config = {
            "configurable":{
                "thread_id": thread_id,
            }
        }
        return await self.graph.ainvoke(
            state,
            config=config
        )

    async def resume(
        self,
        thread_id: str,
        approved: bool,
    ) -> dict[str, Any]:
        config = {
            "configurable": {
                "thread_id": thread_id,
            }
        }
        return await self.graph.ainvoke(
            Command(
                resume={
                    "approved": approved
                }
            ),
            config=config
        )