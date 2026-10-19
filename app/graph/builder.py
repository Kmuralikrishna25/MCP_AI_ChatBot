
from langgraph.graph import StateGraph, START
from langgraph.prebuilt import ToolNode, tools_condition

from .state import ChatState
from .nodes import create_chatbot_node


def build_graph(checkpointer, tools):
    workflow = StateGraph(ChatState)

    workflow.add_node(
        "chatbot",
        create_chatbot_node(tools),
    )

    workflow.add_node(
        "tools",
        ToolNode(tools),
    )

    workflow.add_edge(START, "chatbot")

    workflow.add_conditional_edges(
        "chatbot",
        tools_condition,
    )

    workflow.add_edge("tools", "chatbot")

    return workflow.compile(
        checkpointer=checkpointer
    )
