"""LangGraph ReAct workflow: agent -> (tools -> agent)* -> END."""

import logging
from datetime import date

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.types import RetryPolicy

from agents.prompts import SYSTEM_PROMPT, context_note
from agents.state import AgentState
from agents.tools import TOOLS
from core.llm import is_transient, make_chat_runnable

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 40


def trim_history(messages: list[AnyMessage], limit: int = MAX_HISTORY_MESSAGES) -> list[AnyMessage]:
    """Keep the most recent messages, always starting at a user message so no
    tool result is left without the tool call that produced it."""
    if len(messages) <= limit:
        return messages
    recent = messages[-limit:]
    for i, m in enumerate(recent):
        if isinstance(m, HumanMessage):
            return recent[i:]
    return messages[-1:]


def build_graph(checkpointer, llm: BaseChatModel | None = None):
    # A custom model is used as-is (tests); otherwise Gemini with model fallbacks
    llm_with_tools = llm.bind_tools(TOOLS) if llm is not None else make_chat_runnable(TOOLS)

    async def agent(state: AgentState) -> dict:
        system = SYSTEM_PROMPT.format(today=date.today().strftime("%d %B %Y")) + context_note(state)
        response = await llm_with_tools.ainvoke([SystemMessage(system), *trim_history(state["messages"])])
        return {"messages": [response]}

    graph = StateGraph(AgentState)
    # If every model is momentarily overloaded, try the whole chain once more after a pause
    graph.add_node(
        "agent",
        agent,
        retry_policy=RetryPolicy(max_attempts=2, initial_interval=2.0, jitter=True, retry_on=is_transient),
    )
    graph.add_node("tools", ToolNode(TOOLS, handle_tool_errors=True))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer)
