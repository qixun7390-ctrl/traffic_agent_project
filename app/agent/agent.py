from app.agent.graph import build_traffic_agent_graph
from app.services.llm_service import LLMService
from app.tools.simulation_tools import (
    get_simulation_duration,
    get_simulation_order_summary,
    get_simulation_vehicle_summary,
)
from langgraph.types import Command
from langchain_core.messages import HumanMessage
from typing import Any
from contextlib import AsyncExitStack
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from app.core.config import settings

QUERY_TOOLS = [
    get_simulation_duration,
    get_simulation_order_summary,
    get_simulation_vehicle_summary,
]

_agent_runtime: "TrafficReActAgent | None" = None
_agent_exit_stack = AsyncExitStack()

class TrafficReActAgent:
    """对外调用入口"""
    def __init__(self, checkpointer):
        llm = LLMService()
        query_model_with_tools = llm.bind_tools(
            QUERY_TOOLS,
        )
        self.graph = build_traffic_agent_graph(
            query_model_with_tools=query_model_with_tools,
            query_tools=QUERY_TOOLS,
            checkpointer=checkpointer
        )

    async def ainvoke(
        self,
        user_id: str,
        message: str,
        thread_id: str,
        attachments: dict[str,str] | None = None,
        upload_batch_id: str | None = None,
        history_context: str | None = None,
    ) -> dict[str, Any]:
        """用户发送消息，用户id，附件，审计文件传入Graph中"""
        messages = [
            HumanMessage(content=message)
        ]

        state = {
            "messages": messages,
            "user_id": user_id,
            "attachments": attachments or {},
            "upload_batch_id": upload_batch_id,
            "audit_events": [],
            "history_context": history_context,
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

    async def astream(
        self,
        user_id: str,
        message: str,
        thread_id: str,
        attachments: dict[str, str] | None = None,
        upload_batch_id: str | None = None,
        history_context: str | None = None,
    ):
        """流式输出方法"""
        messages = [
            HumanMessage(content=message)
        ]

        state = {
            "messages": messages,
            "user_id": user_id,
            "attachments": attachments or {},
            "upload_batch_id": upload_batch_id,
            "audit_events": [],
            "history_context": history_context,
        }

        config = {
            "configurable": {
                "thread_id": thread_id,
            }
        }

        async for event in self.graph.astream(
            state,
            config=config,
            stream_mode="updates",
        ):
            yield event

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

    async def resume_stream(
        self,
        thread_id: str,
        approved: bool,
    ):
        config = {
            "configurable": {
                "thread_id": thread_id,
            }
        }

        async for event in self.graph.astream(
            Command(
                resume={
                    "approved": approved
                }
            ),
            config=config,
            stream_mode="updates",
        ):
            yield event

async def init_agent_runtime() -> None:
    """FastAPI 启动时初始化Agent和PostgreSQL Checkpointer"""
    global  _agent_runtime, _agent_exit_stack

    if _agent_runtime is not None:
        return

    try:
        #创建Checkpointer from_context_string 返回异步上下文管理器
        checkpointer_context = AsyncPostgresSaver.from_conn_string(
            settings.LANGGRAPH_CHECKPOINT_DATABASE_URL,
        )

        #进入上下文，获得checkpointer实例
        #同时将资源注册到退出栈,应用关闭时自动清理
        checkpointer = await _agent_exit_stack.enter_async_context(
            checkpointer_context
        )

        #初始化数据库表
        await checkpointer.setup()

        #实例创建
        _agent_runtime = TrafficReActAgent(
            checkpointer = checkpointer
        )

    except Exception as e:
        #如果初始化失败,清理已注册的资源
        await _agent_exit_stack.aclose()
        #重新创建退出栈
        _agent_exit_stack = AsyncExitStack()

        raise RuntimeError(f"Agent初始化失败:{e}")

def get_agent_runtime() -> TrafficReActAgent:
    """FastAPI 接口里获取已经初始化好的Agent"""
    if _agent_runtime is None:
        raise RuntimeError("Agent runtime尚未初始化")
    return _agent_runtime

async def close_agent_runtime() -> None:
    """FastAPI关闭时释放Checkpointer 连接"""
    global _agent_runtime
    global _agent_exit_stack

    _agent_runtime = None

    await _agent_exit_stack.aclose()
    _agent_exit_stack = AsyncExitStack()
