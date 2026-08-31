from app.agent.nodes import (
    build_query_agent_node,
    create_confirmation_node,
    create_execute_node,
    delete_confirmation_node,
    delete_execute_node,
    extract_create_params_node,
    extract_delete_params_node,
    extract_query_params_node,
    chat_node,
    intent_node,
    route_after_confirmation,
    route_after_param_extraction,
    route_by_operation,
    should_continue_query, query_ownership_check_node, delete_ownership_check_node,
    build_locked_query_tools_node
)

from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langgraph.graph import END,START,StateGraph

from app.agent.state import TrafficAgentState

from typing import Any


def build_traffic_agent_graph(
    query_model_with_tools: Runnable,
    query_tools: list[BaseTool],
    checkpointer: Any,
):
    graph = StateGraph(TrafficAgentState)

    graph.add_node("intent", intent_node)

    graph.add_node(
        "extract_query_params",
        extract_query_params_node,
    )
    graph.add_node(
        "extract_create_params",
        extract_create_params_node,
    )
    graph.add_node(
        "extract_delete_params",
        extract_delete_params_node,
    )
    graph.add_node(
        "query_ownership_check",
        query_ownership_check_node,
    )
    graph.add_node(
        "delete_ownership_check",
        delete_ownership_check_node,
    )
    graph.add_node(
        "query_agent",
        build_query_agent_node(query_model_with_tools),
    )
    graph.add_node(
        "query_tools",
        build_locked_query_tools_node(query_tools),
    )
    graph.add_node("chat", chat_node)

    graph.add_node(
        "create_confirmation",
        create_confirmation_node,
    )
    graph.add_node(
        "delete_confirmation",
        delete_confirmation_node,
    )
    graph.add_node("create_execute",create_execute_node)
    graph.add_node("delete_execute",delete_execute_node)
    graph.add_edge(START,"intent")
    graph.add_conditional_edges(
        "intent",
        route_by_operation,
        {
            "query": "extract_query_params",
            "create": "extract_create_params",
            "delete": "extract_delete_params",
            "chat": "chat",
            "error": END,
        },
    )
    graph.add_conditional_edges(
        "extract_query_params",
        route_after_param_extraction,
        {
            "ok": "query_ownership_check",
            "error": END,
        }
    )

    graph.add_conditional_edges(
        "query_ownership_check",
        route_after_param_extraction,
        {
            "ok": "query_agent",
            "error": END,
        }
    )

    graph.add_conditional_edges(
        "query_agent",
        should_continue_query,
        {
            "tools": "query_tools",
            "end": END,
        }
    )

    graph.add_conditional_edges(
        "extract_create_params",
        route_after_param_extraction,
        {
            "ok": "create_confirmation",
            "error": END,
        }
    )

    graph.add_conditional_edges(
        "extract_delete_params",
        route_after_param_extraction,
        {
            "ok": "delete_ownership_check",
            "error": END,
        }
    )

    graph.add_conditional_edges(
        "delete_ownership_check",
        route_after_param_extraction,
        {
            "ok": "delete_confirmation",
            "error": END,
        }
    )

    graph.add_conditional_edges(
        "create_confirmation",
        route_after_confirmation,
        {
            "execute": "create_execute",
            "end": END
        }
    )
    graph.add_conditional_edges(
        "delete_confirmation",
        route_after_confirmation,
        {
            "execute": "delete_execute",
            "end": END,
        }
    )

    graph.add_edge("query_tools", "query_agent")
    graph.add_edge("chat", END)
    graph.add_edge("create_execute", END)
    graph.add_edge("delete_execute", END)

    return graph.compile(checkpointer=checkpointer)

