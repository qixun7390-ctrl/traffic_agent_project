from datetime import datetime
import json
from pathlib import Path
from typing import Any, Literal
import re
from app.agent.state import TrafficAgentState
from langchain_core.messages import HumanMessage,SystemMessage
from langchain_core.runnables import Runnable
from uuid import UUID

from app.core.database import AsyncSessionLocal
from app.services.simulation_run_service import SimulationRunService
from app.core.config import settings
from app.schemas.agent import AgentOperation
from app.services.llm_service import LLMService
from langgraph.types import  interrupt

from app.services.simulation_http_client import SimulationPlatformclient

INTENT_SYSTEM_PROMPT = """
你是交通仿真平台的操作意图分析器。

你只能判断三种 operation：

1. query
用户想查询、分析、查看某个仿真。

2. create
用户想创建、启动、新建仿真。

3. delete
用户想删除、移除某个仿真。

且一次只能返回一种意图，只返回 JSON，不要解释。

返回格式：
{
  "operation": "query|create|delete",
  "reason": "一句话说明判断依据"
}
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
- 不要编造没有返回的字段。
- 如果工具返回为空或缺少关键字段，要说明“当前没有查询到对应数据”。
- 数字尽量直接给出。
- 百分比可以用小数换算成百分比展示。
- 回答简洁，不要暴露内部 JSON。
"""

QUERY_PARAMS_SYSTEM_PROMPT = """
你是交通仿真查询参数抽取器。

你的任务：从用户问题中抽取：
1. simulation_id
2. metrics

重要规则：
- 如果用户说“刚刚那个 / 上一个 / 这个 / 那条仿真”，必须结合上文摘要中的最近一次成功仿真来判断 simulation_id。
- 如果上文摘要里明确给出了最近成功仿真的 simulation_id，而用户没有重新指定新的 simulation_id，就直接使用那个值。
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

def get_last_user_message(
    state: TrafficAgentState,
) -> str:
    messages = state.get("messages",[])

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

    if operation not in {"query", "create", "delete"}:
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

def build_query_agent_node(
    model_with_tools: Runnable,
):
    async def query_agent_node(
        state: TrafficAgentState,
    ) -> dict[str, Any]:
        request_params = state.get("request_params", {})
        history_context = state.get("history_context")

        system_content = (
                QUERY_AGENT_SYSTEM_PROMPT
                + "\n\n已抽取参数：\n"
                + json.dumps(request_params, ensure_ascii=False)
                + "\n请只调用 metrics 中需要的查询工具"
        )

        if history_context:
            system_content += "\n\n历史摘要：\n" + history_context

        messages = [
            SystemMessage(content=system_content),
            *state.get("messages", [])
        ]

        response = await model_with_tools.ainvoke(messages)
        tool_calls = getattr(response,"tool_calls",[]) or []
        return {
            "messages": [response],
            "audit_events": [
                {
                    "node": "query_agent_node",
                    "tool_calls": len(tool_calls)
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
            "simulation_id": simulation_id
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

    async with AsyncSessionLocal() as db:
        service = SimulationRunService(db)

        deleted = await service.delete_run_for_user(
            user_id = UUID(user_id),
            simulation_id = simulation_id,
        )

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
) -> Literal["query","create","delete","error"]:
    if state.get("error"):
        return "error"

    operation = state.get("operation")
    if operation in {"query","create","delete"}:
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
) -> int | None:
    match = re.search(r"\d+", text)
    if not match:
        return None
    value = int(match.group())
    if value <= 0:
        return None
    return value

async def extract_query_params_node(
    state: TrafficAgentState
) -> dict[str, Any]:
    user_message = get_last_user_message(state)
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
        metrics = [
            "duration",
            "order_summary",
            "vehicle_summary",
        ]
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
                "message": "仿真不存在或无权查询",
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
                "message": "仿真不存在或无权删除",
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
    simulation_id = extract_first_positive_int(user_message)

    if simulation_id is None:
        return {
            "error": {
                "node": "extract_delete_params_node",
                "message": "删除仿真需要提供 simulation_id",
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
        history_context=state.get("history_context")
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