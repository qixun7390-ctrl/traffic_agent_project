from datetime import datetime
import json
from pathlib import Path
from typing import Any, Literal
import re
from uuid import UUID
from app.agent.state import TrafficAgentState
from langchain_core.messages import AIMessage, HumanMessage,SystemMessage,ToolMessage

from langchain_core.tools import BaseTool
from langgraph.prebuilt import ToolNode
from langchain_core.runnables import Runnable, RunnableConfig

from app.core.database import AsyncSessionLocal
from app.services.simulation_run_service import SimulationRunService
from app.core.config import settings
from app.schemas.agent import AgentOperation, CreateParams
from app.services.llm_service import LLMService
from langgraph.types import  interrupt
from pydantic import ValidationError

from app.services.simulation_http_client import SimulationPlatformclient
from app.services.simulation_operation_lock_service import (
    SimulationOperationLockedError,
    simulation_operation_locks,
)

INTENT_SYSTEM_PROMPT = """
你是交通仿真平台的操作意图分析器。

你只能判断四种 operation：

1. query
用户想查询、分析、查看某个明确仿真的运行指标或结果，例如某个 simulation_id 的时长、订单完成率、车辆情况。

2. create
用户想创建、启动、新建仿真。

3. delete
用户想删除、移除某个仿真。

4. chat
用户的问题不属于查询仿真、创建仿真、删除仿真，或者只是普通闲聊、解释、帮助、学习提问。
用户问“你有哪些功能 / 你能做什么 / 我之前创建了哪些仿真 / 最近创建过哪些仿真 / 我刚刚做过什么”也属于 chat。

重要规则：
- 如果用户没有表达查询、创建、删除仿真的明确意图，operation 必须返回 chat。
- query 只用于查询某一个明确 simulation_id，或用户明确说“刚刚那个 / 上一个 / 这个仿真”的指标。
- 如果用户只是回顾历史创建记录，而不是查询某个仿真的指标，operation 必须返回 chat。
- 如果用户同时表达互相冲突的意图，例如“创建删除一个仿真”，operation 必须返回 chat。
- 不要为了凑业务流程而把普通问题强行归类为 query/create/delete。

且一次只能返回一种意图，只返回 JSON，不要解释。

返回格式：
{
  "operation": "query|create|delete|chat",
  "reason": "一句话说明判断依据"
}
"""

CHAT_RESPONSE = (
    "我目前可以帮你处理交通仿真的创建、查询和删除的任务。"
    "如果你要继续操作，请明确说明要创建、查询还是删除哪一个仿真。"
)

CHAT_SYSTEM_PROMPT = """
你是交通仿真平台的智能体助手。

你的任务是处理不需要进入创建、查询、删除工作流的普通对话。

你可以回答：
1. 你有哪些功能、如何使用系统。
2. 基于情景记忆摘要回答用户最近创建过哪些仿真、最近做过什么。

重要规则：
- 首先是一定要对应用户的问题进行回答,不能回答额外回答其他内容，就事论事。
- 不要调用查询工具，不要执行创建或删除操作。
- 不要编造情景记忆中不存在的 simulation_id。
- 如果用户问之前创建了哪些仿真，只能根据 recent_successful_simulations 回答。
- recent_successful_simulations 按时间从近到远排列。
- 如果情景记忆没有相关记录，就明确说当前没有查到相关历史记录。
- 如果用户真正想查询某个仿真的指标、创建仿真或删除仿真，请提醒用户明确输入对应操作。
- 回答要简洁，不要暴露内部 JSON。
- 同时回复用户的答案不要带有markdown，要生成结构化的回答，格式整齐工整
"""


QUERY_AGENT_SYSTEM_PROMPT = """
你是交通仿真查询助手，采用 ReAct 思路工作。

你的工作方式：
1. 先理解用户问题和已抽取参数。
2. 根据 metrics 选择必要工具。
3. 工具返回结果后，基于工具结果回答用户。
4. 如果已经拿到足够结果，直接总结，不要重复调用同一个工具。

当前可用工具：
- get_simulation_duration：查询仿真运行时长。
- get_simulation_order_summary：查询订单创建数、匹配数、上车数、完成数、匹配率、完成率。
- get_simulation_vehicle_summary：查询车辆总数、活跃车辆数、空闲车辆数、完成过订单的车辆数、总完成订单数、平均每辆活跃车完成订单数。

工具选择规则：
- metrics 包含 duration，只调用 get_simulation_duration。
- metrics 包含 order_summary，只调用 get_simulation_order_summary。
- metrics 包含 vehicle_summary，只调用 get_simulation_vehicle_summary。
- metrics 同时包含多个指标，可以调用多个工具。
- 不要调用 metrics 之外的工具。
- 同一个工具最多调用一次。

回答规则：
- 回答必须基于工具返回结果。
- 不要编造没有返回的字段,严格按照调用函数返回的结果回答用户问题,如果你遇到返回结果中没有直接能回答用户问题的字段,请你根据结果做出推测,但是你要把你的推测过程完整地写出来，公式是怎么样的,你是怎么根据公式进行推导的
- 如果工具返回 error 字段，直接说明该仿真已删除、不存在或暂无可查询数据，不要继续生成正常概览。
- 如果工具返回为空或缺少关键字段，要说明“当前没有查询到对应数据”。
- 数字尽量直接给出。
- 百分比可以用小数换算成百分比展示。
- 不要暴露内部 JSON。
- 不要使用 Markdown 格式。
- 不要使用 **、#、-、``` 这类 Markdown 标记。
- 多个指标必须分行展示，不要挤在一行。
- 第一行用“{simulation_id}号仿真概览”。
- 中间每个指标一行，格式为“指标名：数值”。
- 最后一行给出一句简短解释，说明这个结果意味着什么。
- 同时不要套用示例概览内容，一次性地把指标全部返回，特别是不要回答用户没有进行提问的指标，根据返回结果找出能回答用户问题的内容进行解答，而不是一次性全部展示给用户。
- 生成回答的格式要美观,要做到整体同时每一行要对齐

示例：

用户提问:17号仿真创建了多少个订单，匹配率如何,乘客上车了多少单,订单完成率

17号仿真概览

订单创建数：37 单
订单匹配数：36 单，匹配率 97.3%
乘客上车数：20 单
订单完成数：9 单，完成率 24.3%
(注意: 只根据用户提问的内容来进行回答,不要回答其他指标,同时概览格式要美观,不要一行接着一行地来)
整体来看，订单匹配率较高，但最终完成率偏低，可以继续查看车辆运行情况。
"""

QUERY_PARAMS_SYSTEM_PROMPT = """
你是交通仿真查询参数抽取器。

你的任务：从用户问题中抽取：
1. simulation_id
2. metrics

重要规则：
- 只有当用户明确说“刚刚那个 / 上一个 / 这个 / 那条仿真”等指代词时，才允许结合情景记忆摘要判断 simulation_id。
- 情景记忆里的 recent_successful_simulations 按时间从近到远排列，用户说“刚刚那个 / 上一个”时优先使用第一条的 simulation_id。
- 如果用户只是说“查询完成率 / 查询车辆情况”但没有明确 simulation_id，也没有明确指代词，simulation_id 必须返回 null。
- 如果用户明确说了某个 simulation_id，以用户新输入为准。

metrics 只能从下面选择：
- duration
- order_summary
- vehicle_summary

选择规则：
- 用户问“跑了多久 / 仿真时长 / 运行时长”，选择 duration。
- 用户问“创建多少订单 / 匹配多少订单 / 完成多少订单 / 订单完成率 / 订单整体情况”，选择 order_summary。
- 用户问“多少辆车 / 车辆完成情况 / 活跃车辆 / 空闲车辆 / 平均每辆车完成多少单”，选择 vehicle_summary。
- 用户问“整体情况 / 整体效果 / 仿真结果怎么样”，选择 duration、order_summary、vehicle_summary。
- 不要选择用户没有问到的指标，除非用户问整体情况。

你只返回 JSON，不要解释。

返回格式：
{
  "simulation_id": 283,
  "metrics": ["duration", "order_summary", "vehicle_summary"]
}
"""

CREATE_PARAMS_SYSTEM_PROMPT = """
你是交通仿真创建参数抽取器。

从用户自然语言中抽取创建仿真的参数：
- name
- running_time_step
- description
- use_random_match
- use_cost

不要抽取文件路径，文件路径来自系统 attachments。

如果用户没有明确提供：
- running_time_step 默认 3600
- description 默认空字符串
- use_random_match 默认 true
- use_cost 默认 true
- name 可以返回 null

只返回 JSON，不要解释。

返回格式：
{
  "name": null,
  "running_time_step": 3600,
  "description": "",
  "use_random_match": true,
  "use_cost": true
}
"""

DELETE_PARAMS_SYSTEM_PROMPT = """
你是交通仿真删除参数抽取器。

你的任务：从用户自然语言中抽取 simulation_id。

重要规则：
- 用户输入删除请求中可能是数字或者中文，但是都请转换为数字，比如用户说:"删除三十号仿真"或者"删除30号仿真"等,都请转换为对应数字，待删除simulation_id为30。
- 只能抽取用户明确给出的仿真编号，不要从历史上下文中猜测删除目标。
- 如果用户没有提供明确的仿真编号，simulation_id 返回 null。
- 如果用户提供 0、负数、小数、字母混合编号或其他不合规编号，simulation_id 返回 null。

你只返回 JSON，不要解释。

返回格式：
{
  "simulation_id": 46
}
"""

def get_working_messages(
    state: TrafficAgentState,
) -> list[Any]:
    """返回当前图线程的短期工作记忆，避免把无限增长的 messages 全量喂给 LLM。"""
    messages = state.get("messages", [])
    limit = settings.AGENT_WORKING_MEMORY_LIMIT
    if limit <= 0:
        return []
    return list(messages[-limit:])

def get_last_user_message(
    state: TrafficAgentState,
) -> str:
    messages = get_working_messages(state)

    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content)

    return ""

def parse_operation(
    raw_text: str,
) -> tuple[AgentOperation | None,str]:
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        return None, "LLM返回内容不是合法JSON"

    if not isinstance(data,dict):
        return None, "LLM返回内容不是JSON对象"

    operation = data.get("operation")
    reason = data.get("reason", "")

    if operation not in {"query", "create", "delete", "chat"}:
        return None, f"未知operation:{operation}"

    return operation,str(reason)

async def intent_node(
    state: TrafficAgentState,
) -> dict[str, Any]:
    user_message = get_last_user_message(state)
    if not user_message:
        return {
            "error": {
                "node": "intent_node",
                "message": "没有找到用户消息"
            }
        }

    llm = LLMService()
    raw_result = await llm.generate_response(
        system_prompt = INTENT_SYSTEM_PROMPT,
        user_message = user_message
    )

    operation, reason = parse_operation(raw_result)

    if operation is None:
        return {
            "error":{
                "node": "intent_node",
                "message": reason,
                "raw_result": raw_result
            }
        }

    return {
        "operation": operation,
        "audit_events": [
            {
                "node": "intent_node",
                "operation": operation,
                "reason": reason
            }
        ]
    }

async def chat_node(
    state: TrafficAgentState,
) -> dict[str, Any]:
    user_message = get_last_user_message(state)
    history_context = state.get("history_context")

    try:
        llm = LLMService()
        answer = await llm.generate_response(
            system_prompt=CHAT_SYSTEM_PROMPT,
            user_message=user_message,
            history_context=history_context,
        )
    except Exception:
        answer = CHAT_RESPONSE

    return {
        "last_result": {
            "operation": "chat",
            "message": answer,
        },
        "audit_events": [
            {
                "node": "chat_node",
                "message": answer,
            }
        ],
    }

def build_query_agent_node(
    model_with_tools: Runnable,
):
    async def query_agent_node(
        state: TrafficAgentState,
    ) -> dict[str, Any]:
        """"react查询节点,工作记忆限制为最近的100条并插入情景记忆"""
        request_params = state.get("request_params", {})
        episodic_context = state.get("history_context")

        system_content = (
                QUERY_AGENT_SYSTEM_PROMPT
                + "\n\n已抽取参数：\n"
                + json.dumps(request_params, ensure_ascii=False)
                + "\n请只调用 metrics 中需要的查询工具"
        )

        if episodic_context:
            system_content += "\n\n情景记忆摘要：\n" + episodic_context

        messages = [
            SystemMessage(content=system_content),
            *get_working_messages(state)
        ]

        response = await model_with_tools.ainvoke(messages)
        tool_calls = getattr(response,"tool_calls",[]) or []

        current_rounds = state.get("query_tool_call_rounds", 0) or 0
        max_rounds = settings.AGENT_QUERY_MAX_TOOL_CALL_ROUNDS
        if tool_calls and current_rounds >= max_rounds:
            return {
                "messages": [
                    AIMessage(
                        content="查询工具调用次数已达到上限，无法继续查询，请稍后重试。"
                    )
                ],
                "error": {
                    "node": "query_agent_node",
                    "message": "查询工具调用次数已达到上限，已停止重复调用",
                    "tool_call_rounds": current_rounds,
                    "max_tool_call_rounds": max_rounds,
                },
                "audit_events": [
                    {
                        "node": "query_agent_node",
                        "tool_calls": len(tool_calls),
                        "tool_call_rounds": current_rounds,
                        "stopped_by_tool_call_limit": True,
                    }
                ],
            }

        return {
            "messages": [response],
            "query_tool_call_rounds": (
                current_rounds + 1
                if tool_calls
                else current_rounds
            ),
            "audit_events": [
                {
                    "node": "query_agent_node",
                    "tool_calls": len(tool_calls),
                    "tool_call_rounds": current_rounds,
                }
            ],
        }

    return query_agent_node

async def create_confirmation_node(
    state: TrafficAgentState,
) -> dict[str, Any]:
    pending_action =  {
        "operation": "create",
        "summary": "创建仿真需要用户确认后执行",
        "arguments": state.get("request_params", {})
    }

    human_decision = interrupt(
        {
            "type": "confirmation",
            "operation": "create",
            "question": "是否确认创建该仿真?",
            "pending_action": pending_action,
        }
    )

    approved = (
        bool(human_decision.get("approved"))
        if isinstance(human_decision, dict)
        else bool(human_decision)
    )

    return {
        "confirmation_status": "approved" if approved else "rejected",
        "pending_action": pending_action,
        "audit_events": [
            {
                "node": "create_confirmation_node",
                "status": "approved" if approved else "rejected",
            }
        ],
    }


async def delete_confirmation_node(
    state: TrafficAgentState,
) -> dict[str, Any]:
    pending_action = {
        "operation": "delete",
        "summary": "删除仿真需要用户确认后执行",
        "arguments": state.get("request_params", {})
    }

    human_decision = interrupt(
        {
            "type": "confirmation",
            "operation": "delete",
            "question": "是否删除该仿真",
            "pending_action": pending_action
        }
    )

    approved = (
        bool(human_decision.get("approved"))
        if isinstance(human_decision, dict) else bool(human_decision)
    )

    return {
        "confirmation_status": "approved" if approved else "rejected",
        "pending_action": pending_action,
        "audit_events": [
            {
                "node": "delete_confirmation_node",
                "status": "approved" if approved else "rejected",
            }
        ]
    }

def route_after_confirmation(
    state: TrafficAgentState,
) -> Literal["execute","end"]:
    if state.get("confirmation_status") == "approved":
        return "execute"
    return "end"

async def create_execute_node(
    state: TrafficAgentState,
) -> dict[str, Any]:
    params = state.get("request_params", {})
    attachments = params.get("attachments", {})
    user_id = state.get("user_id")
    upload_batch_id_raw = state.get("upload_batch_id")

    if not user_id:
        return {
            "error": {
                "node": "create_execute_node",
                "message": "缺少user_id，无法保存仿真记录"
            }
        }
    if not upload_batch_id_raw:
        return {
            "error":{
                "node": "create_execute_node",
                "message": "缺少upload_batch_id，无法保存仿真记录",
            }
        }

    upload_batch_id = UUID(upload_batch_id_raw)
    suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = params.get("name") or "agent_area"

    area_name = f"{base_name}_{suffix}"
    simulation_name = f"{base_name}_{suffix}"
    async with SimulationPlatformclient(
        base_url=settings.SIMULATION_PLATFORM_BASE_URL,
        token=settings.SIMULATION_PLATFORM_TOKEN
    ) as client:
        area_id = await client.create_area(
            name=area_name,
            map_file=Path(attachments["map_file"]),
            signal_file=Path(attachments["signal_file"]),
            description=params.get("description", ""),
            border_file=(
                Path(attachments["border_file"])
                if attachments.get("border_file")
                else None
            ),
        )
        stop_data_id = await client.upload_stop_data(
            area_id = area_id,
            name=f"{area_name}_stops",
            file_path=Path(attachments["stop_file"]),
            description="Agent uploaded stop data"
        )
        order_data_id = await client.upload_order_data(
            area_id=area_id,
            stop_data_id=stop_data_id,
            name=f"{area_name}_stops",
            file_path=Path(attachments["order_file"]),
            description="Agent uploaded stop data"
        )
        bus_data_id = await client.upload_bus_data(
            area_id=area_id,
            name=f"{area_name}_buses",
            file_path=Path(attachments["bus_file"]),
            description="Agent uploaded bus data",
        )
        simulation_id = await client.create_offline_simulation(
            name=simulation_name,
            running_time_step=params.get("running_time_step", 3600),
            area_id=area_id,
            stop_data_id=stop_data_id,
            order_data_id=order_data_id,
            bus_data_id=bus_data_id,
            description=params.get("description", ""),
            use_random_match=params.get("use_random_match", True),
            use_cost=params.get("use_cost", True),
        )

    async with AsyncSessionLocal() as db:
        service = SimulationRunService(db)
        await service.create_run_for_user(
            user_id = UUID(user_id),
            platform_simulation_id = simulation_id,
            attachments = attachments,
            upload_batch_id=upload_batch_id,
        )
        result = {
            "area_id": area_id,
            "stop_data_id": stop_data_id,
            "bus_data_id": bus_data_id,
            "order_data_id": order_data_id,
            "simulation_id": simulation_id,
            "create_params": {
                "name": params.get("name"),
                "running_time_step": params.get("running_time_step", 3600),
                "description": params.get("description", ""),
                "use_random_match": params.get("use_random_match", True),
                "use_cost": params.get("use_cost", True),
            },
        }
        return {
            "last_result": result,
            "audit_events": [
                {
                    "node": "create_execute_node",
                    "result": result,
                }
            ]
        }

async def delete_execute_node(
    state: TrafficAgentState,
) -> dict[str, Any]:
    params = state.get("request_params",{})
    simulation_id = params.get("simulation_id")
    user_id = state.get("user_id")

    if not user_id:
        return {
            "error": {
                "node": "delete_execute_node",
                "message": "缺少user_id,无法删除仿真"
            }
        }

    try:
        async with simulation_operation_locks.lock(
            user_id=user_id,
            simulation_id=simulation_id,
        ):
            async with AsyncSessionLocal() as db:
                service = SimulationRunService(db)

                deleted = await service.delete_run_for_user(
                    user_id = UUID(user_id),
                    simulation_id = simulation_id,
                )
    except SimulationOperationLockedError as exc:
        return {
            "error": {
                "node": "delete_execute_node",
                "message": str(exc),
                "simulation_id": simulation_id,
            }
        }

    if not deleted:
        return {
            "error": {
                "node": "delete_execute_node",
                "message": "仿真不存在或无权删除",
                "simulation_id": simulation_id,
            }
        }
    result = {
        "simulation_id": simulation_id,
        "message": "删除成功",
    }

    return {
        "last_result": result,
        "audit_events": [
            {
                "node": "delete_execute_node",
                "result": result
            }
        ],
    }

def route_by_operation(
    state: TrafficAgentState
) -> Literal["query","create","delete","chat","error"]:
    if state.get("error"):
        return "error"

    operation = state.get("operation")
    if operation in {"query","create","delete","chat"}:
        return operation

    return "error"

def should_continue_query(
    state: TrafficAgentState,
) -> Literal["tools","end"]:
    messages = state.get("messages",[])
    if not messages:
        return "end"
    last_message = messages[-1]
    tool_calls = getattr(last_message, "tool_calls", None)
    if tool_calls:
        return "tools"

    return "end"

def extract_first_positive_int(
    text: str,
) -> tuple[int | None, str | None]:
    if re.search(r"-\s*\d+", text):
        return None, "simulation_id 必须是大于 0 的整数"

    match = re.search(r"(?<![A-Za-z0-9_.])\d+(?![A-Za-z0-9_.])", text)
    if not match:
        return None, "删除仿真需要提供 simulation_id"
    value = int(match.group())
    if value <= 0:
        return None, "simulation_id 必须是大于 0 的整数"
    return value, None

async def extract_query_params_node(
    state: TrafficAgentState
) -> dict[str, Any]:
    user_message = get_last_user_message(state)
    if re.search(r"-\s*\d+", user_message):
        return {
            "error": {
                "node": "extract_query_params_node",
                "message": "simulation_id 必须是大于 0 的整数",
            }
        }

    llm = LLMService()
    raw_result = await llm.generate_response(
        system_prompt=QUERY_PARAMS_SYSTEM_PROMPT,
        user_message=user_message,
        history_context=state.get("history_context"),
    )
    data = json.loads(raw_result)

    if data is None or not isinstance(data,dict):
        return {
            "error": {
                "node": "extract_query_params_node",
                "message": "查询参数抽取结果不是合法JSON对象",
                "raw_result": raw_result,
            }
        }

    simulation_id = data.get("simulation_id")
    metrics = data.get("metrics", [])

    if not isinstance(simulation_id,int) or simulation_id <= 0:
        return {
            "error": {
                "node": "extract_query_params_node",
                "message": "缺少有效的simulation_id"
            }
        }

    allowd_metrics = {
        "duration",
        "order_summary",
        "vehicle_summary",
    }
    if not isinstance(metrics,list):
        metrics = []

    metrics = [
        metric for metric in metrics if metric in allowd_metrics
    ]

    if not metrics:
        return {
            "error": {
                "node": "extract_query_params_node",
                "message": "缺少有效的查询指标",
            }
        }
    return {
        "request_params": {
            "simulation_id": simulation_id,
            "metrics": metrics,
        },
        "audit_events": [
            {
                "node": "extract_query_params_node",
                "simulation_id": simulation_id,
                "metrics": metrics
            }
        ]
    }

async def query_ownership_check_node(
    state: TrafficAgentState,
) -> dict[str, Any]:
    params = state.get("request_params", {})
    simulation_id = params.get("simulation_id")
    user_id = state.get("user_id")

    if not user_id:
        return {
            "error": {
                "node": "query_ownership_check_node",
                "message": "缺少user_id，无法查询仿真",
            }
        }

    async with AsyncSessionLocal() as db:
        service = SimulationRunService(db)
        run = await service.get_run_for_user(
            user_id=UUID(user_id),
            simulation_id=simulation_id,
        )

    if run is None:
        return {
            "error": {
                "node": "query_ownership_check_node",
                "message": "仿真已删除、不存在或无权查询，请刷新仿真列表后重试",
                "simulation_id": simulation_id,
            }
        }

    return {
        "audit_events": [
            {
                "node": "query_ownership_check_node",
                "simulation_id": simulation_id,
                "ownership_check": "passed",
            }
        ]
    }

async def delete_ownership_check_node(
    state: TrafficAgentState,
) -> dict[str, Any]:
    """删除的用户确认节点"""
    params = state.get("request_params", {})
    simulation_id = params.get("simulation_id")
    user_id = state.get("user_id")

    if not user_id:
        return {
            "error": {
                "node": "delete_ownership_check_node",
                "message": "缺少user_id，无法删除仿真",
            }
        }

    async with AsyncSessionLocal() as db:
        service = SimulationRunService(db)
        run = await service.get_run_for_user(
            user_id=UUID(user_id),
            simulation_id=simulation_id,
        )
    if run is None:
        return {
            "error": {
                "node": "delete_ownership_check_node",
                "message": "仿真已删除、不存在或无权删除，请刷新仿真列表后重试",
                "simulation_id": simulation_id,
            }
        }

    return {
        "audit_events": [
            {
                "node": "delete_ownership_check_node",
                "simulation_id": simulation_id,
                "ownership_check": "passed",
            }
        ]
    }

async def extract_delete_params_node(
    state: TrafficAgentState,
) -> dict[str, Any]:
    user_message = get_last_user_message(state)

    if re.search(r"-\s*\d+", user_message):
        return {
            "error": {
                "node": "extract_delete_params_node",
                "message": "simulation_id 必须是大于 0 的整数",
            }
        }

    llm = LLMService()
    raw_result = await llm.generate_response(
        system_prompt=DELETE_PARAMS_SYSTEM_PROMPT,
        user_message=user_message,
    )

    try:
        data = json.loads(raw_result)
    except json.JSONDecodeError:
        return {
            "error": {
                "node": "extract_delete_params_node",
                "message": "删除参数抽取结果不是合法JSON",
                "raw_result": raw_result,
            }
        }

    if data is None or not isinstance(data, dict):
        return {
            "error": {
                "node": "extract_delete_params_node",
                "message": "删除参数抽取结果不是合法JSON对象",
                "raw_result": raw_result,
            }
        }

    simulation_id = data.get("simulation_id")

    if not isinstance(simulation_id, int) or simulation_id <= 0:
        return {
            "error": {
                "node": "extract_delete_params_node",
                "message": "删除仿真需要提供有效的 simulation_id",
                "raw_result": raw_result,
            }
        }

    return {
        "request_params": {
            "simulation_id": simulation_id,
        },
        "audit_events": [
            {
                "node": "extract_delete_params_node",
                "simulation_id": simulation_id,
            }
        ],
    }


async def extract_create_params_node(
    state: TrafficAgentState,
) -> dict[str, Any]:
    user_message = get_last_user_message(state)
    attachments = state.get("attachments", {})
    upload_batch_id = state.get("upload_batch_id")
    llm = LLMService()
    raw_result = await llm.generate_response(
        system_prompt=CREATE_PARAMS_SYSTEM_PROMPT,
        user_message=user_message,
    )

    data = json.loads(raw_result)

    if data is None:
        return {
            "error": {
                "node": "extract_create_params_node",
                "message": "创建参数抽取结果不是合法JSON对象",
                "raw_result": raw_result,
            }
        }

    required_files = [
        "map_file",
        "signal_file",
        "stop_file",
        "order_file",
        "bus_file",
    ]

    if not upload_batch_id:
        return {
            "missing_attachments": required_files,
            "error": {
                "node": "extract_create_params_node",
                "message": "创建仿真前必须上传所有完整的文件",
                "missing_attachments": required_files,
            }
        }

    missing_attachments = [
        file_name
        for file_name in required_files
        if not attachments.get(file_name)
    ]

    if missing_attachments:
        return {
            "missing_attachments": missing_attachments,
            "error": {
                "node": "extract_create_params_node",
                "message": "创建仿真缺少必要附件",
                "missing_attachments": missing_attachments,
            },
        }

    request_params = {
        "name": data.get("name"),
        "running_time_step": data.get("running_time_step", 3600),
        "description": data.get("description", ""),
        "use_random_match": data.get("use_random_match", True),
        "use_cost": data.get("use_cost", True),
        "attachments": attachments,
    }

    try:
        request_params = CreateParams.model_validate(
            request_params
        ).model_dump()
    except ValidationError as e:
        return {
            "error": {
                "node": "extract_create_params_node",
                "message": "创建参数不合法，请检查仿真时长等参数",
                "details": e.errors(),
            }
        }

    return {
        "request_params": request_params,
        "missing_attachments": [],
        "audit_events": [
            {
                "node": "extract_create_params_node",
                "request_params": request_params,
            }
        ],
    }


def route_after_param_extraction(
    state: TrafficAgentState,
) -> Literal["ok","error"]:
    if state.get("error"):
        return "error"
    return "ok"

def build_locked_query_tools_node(query_tools: list[BaseTool]):
    tool_node = ToolNode(query_tools)

    async def query_tools_node(
        state: TrafficAgentState,
        config: RunnableConfig | None = None,
    ) -> dict[str, Any]:
        params = state.get("request_params", {})
        user_id = state.get("user_id")
        simulation_id = params.get("simulation_id")

        if not user_id or not isinstance(simulation_id, int):
            return {
                "error": {
                    "node": "query_tools",
                    "message": "缺少有效的用户或仿真参数，无法查询",
                }
            }

        try:
            async with simulation_operation_locks.lock(
                user_id=user_id,
                simulation_id=simulation_id,
            ):
                return await tool_node.ainvoke(state, config=config)
        except SimulationOperationLockedError as exc:
            messages = state.get("messages", [])
            last_message = messages[-1] if messages else None
            tool_calls = getattr(last_message, "tool_calls", []) or []

            return {
                "messages": [
                    ToolMessage(
                        content=json.dumps(
                            {
                                "simulation_id": simulation_id,
                                "error": str(exc),
                            },
                            ensure_ascii=False,
                        ),
                        tool_call_id=tool_call["id"],
                        name=tool_call.get("name", "query_tool"),
                    )
                    for tool_call in tool_calls
                ],
                "audit_events": [
                    {
                        "node": "query_tools",
                        "simulation_id": simulation_id,
                        "locked": True,
                    }
                ],
            }

    return query_tools_node