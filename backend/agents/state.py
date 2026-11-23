from typing import Annotated, NotRequired, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages


class AgentState(TypedDict):
    """Conversation state, saved per session by the LangGraph checkpointer.

    `last_search` and `filters` are written by the search/filter tools (via
    Command updates) so follow-ups like "only Samsung under ₹1500" refine the
    previous results instead of searching again.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    last_search: NotRequired[dict]  # {"query", "category", "groups": [...]}
    filters: NotRequired[dict]  # accumulated refinements: brand, max_price, keywords, ...
    focus_product_id: NotRequired[int]  # the product currently being discussed
