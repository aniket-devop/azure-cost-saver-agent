"""DEPRECATED (Phase 5): legacy module kept temporarily; do not use in new code.

Superseded by the azure_finops_agent package (run: azure-finops run). The new LangGraph
workflow never imports this module. Known problems: hardcoded or guessed figures and no
partial-result handling. Scheduled for removal once the Azure Functions entry point is
migrated.
"""
import warnings

warnings.warn(
    "agent.py is deprecated; use the azure_finops_agent package (azure-finops run)",
    DeprecationWarning,
    stacklevel=2,
)

import os
import sys
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode

from teams_sender import send_to_teams

SYSTEM = (
    "You are an Azure cost assistant. Use the tools to get the last 7 days cost and to find "
    "idle resources. Then write a short plain-text summary (max 6 lines, no markdown): total "
    "cost, idle resources found, and total estimated monthly savings in INR. If nothing is idle, "
    "say usage looks clean. You only report. Never suggest automatic deletion."
)


async def run_agent() -> str:
    client = MultiServerMCPClient({
        "azure_cost": {
            "command": sys.executable,
            "args": [os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_server.py")],
            "transport": "stdio",
            "env": dict(os.environ),
        }
    })
    tools = await client.get_tools()

    llm = AzureChatOpenAI(
        azure_deployment="gpt-mini",
        api_version="2024-10-21",
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_KEY"],
        temperature=0,
    ).bind_tools(tools)

    async def agent(state: MessagesState):
        reply = await llm.ainvoke([SystemMessage(content=SYSTEM)] + state["messages"])
        return {"messages": [reply]}

    def route(state: MessagesState):
        return "tools" if state["messages"][-1].tool_calls else "send"

    def send(state: MessagesState):
        summary = state["messages"][-1].content
        if os.environ.get("TEAMS_WEBHOOK_URL"):
            send_to_teams(summary)
        else:
            print("TEAMS_WEBHOOK_URL not set, skipping Teams")
        return {"messages": []}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(tools))
    graph.add_node("send", send)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, {"tools": "tools", "send": "send"})
    graph.add_edge("tools", "agent")
    graph.add_edge("send", END)
    app = graph.compile()

    final = None
    seen = 0
    async for state in app.astream(
        {"messages": [HumanMessage(content="Prepare today's Azure cost report.")]},
        config={"recursion_limit": 10},
        stream_mode="values",
    ):
        for m in state["messages"][seen:]:
            m.pretty_print()
        seen = len(state["messages"])
        final = state
    return final["messages"][-1].content
